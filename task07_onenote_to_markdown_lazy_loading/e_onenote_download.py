"""Bronze 層 Extract：下載 OneNote 頁面 html、比對 hash、有變動才分區寫入 GCS。

執行流程：下載 OneNote 頁面 html → 算 html_sha_hash → 與 onenote_note_metadata 最新一筆 hash 比對 →
有變動才以 dt=<執行日> 分區寫入 GCS（html + _images），並 upsert onenote_note_metadata（status=bronze_stored、
含 attached_images 圖片血緣與 topic 初判）。
本層完全不呼叫 LLM；Silver enrichment 改由 UI on-demand 觸發。

Usage:
    poetry run python -m task07_onenote_to_markdown_lazy_loading.e_onenote_download

Required .env keys:
    ONENOTE_CLIENT_ID                Azure App Registration Client ID (public client, Notes.Read scope).
    ONENOTE_GCS_BUCKET               GCS bucket serving as the data lake.
    GCS_USER_CREDENTIALS   (On-premise only) GCS service account JSON.

Optional .env keys:
    ONENOTE_NOTEBOOK_IDS   JSON array of notebook IDs; interactive select if omitted.
"""

import json
import os
import re
import sys
import time
import uuid
from collections import deque
from datetime import date
from pathlib import Path

import msal
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from loguru import logger

from task07_common import gcs  # GCS 相關互動模組
from task07_common.audit_log import (  # 回傳現在 UTC 時間
    get_latest_version_meta,  # 取出每份筆記頁 (page) 的最新一筆 html_hash 值
    log_api_call,  # Insert request log to OneNote Graph API
    now_utc,
    upsert_version_meta,  # Upsert data lineage between html to md
)
from task07_common.hashing import html_source_hash  # 計算 html_sha_hash 用
from task07_common.topic import infer_topic  # bronze 以 page_title 初判 topic

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

CLIENT_ID = os.getenv("ONENOTE_CLIENT_ID", "")
AUTHORITY = "https://login.microsoftonline.com/consumers"
SCOPES = ["Notes.Read"]
CACHE_PATH = Path.home() / ".config" / "onenote-skill" / "token_cache.json"
REQUEST_TIMEOUT = (10, 60)  # (connect, read) 秒；無 timeout 時伺服器 hang 住會無限等待

EXT_MAP = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/tiff": ".tiff",
}

if not CLIENT_ID:
    logger.error("ONENOTE_CLIENT_ID is not set in .env")
    sys.exit(1)


# ── Auth ──────────────────────────────────────────────────────────────────────


def _build_msal_app() -> tuple[msal.PublicClientApplication, msal.SerializableTokenCache]:
    """建立可快取物件 cache 與 Microsoft 應用程式物件 app。不回傳 token。

    此函式會自動檢查全域變數 CACHE_PATH (Path 物件) 是否存在，
    若存在則會讀取並載入先前的快取紀錄。

    **Notes**:
        此函式本身不會將更新後的快取寫回硬碟，呼叫端需自行負責後續儲存。

    Returns:
        tuple[msal.PublicClientApplication, msal.SerializableTokenCache]:
            傳回設定好的 MSAL 應用程式實例與 Token 快取物件。
    """
    # 建立可被序列化（也就是能轉成文字存成檔案）的快取物件 cache
    cache = msal.SerializableTokenCache()
    # 檢查指定的路徑（CACHE_PATH, Path 物件）下有沒有先前存好的快取檔案
    # 本機測試可以考慮把 CACHE_PATH 建在 ~/.config/ 下
    if CACHE_PATH.exists():
        # 用 .deserialize() 把裡面的文字資料讀進記憶體的快取物件
        cache.deserialize(CACHE_PATH.read_text())

    # 建立 PublicClientApplication 物件
    # CLIENT_ID 為應用程式註冊識別碼，AUTHORITY 為微軟的身分驗證中心網址
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)
    return app, cache


def get_token() -> tuple[str, msal.PublicClientApplication, msal.SerializableTokenCache]:
    """Acquire access token; triggers device-flow login when no cached token exists."""
    # 1. 建立應用程式物件、快取物件
    app, cache = _build_msal_app()

    # 2. 從應用程式的快取中尋找是否有記錄著使用者帳號
    accounts = app.get_accounts()

    # 3. 嘗試在背景自動取得 Token。若有快取帳號且 Access Token 已過期，會自動用 Refresh Token 刷新。
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None

    # 4. 如果無法在背景靜態取得 Token（無帳號或快取提前失效），則觸發互動式登入
    if not result:
        # 啟動裝置驗證流程 (Device Flow)
        # initiate_device_flow() 跟 acquire_token_by_device_flow() 配合使用
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            logger.error(f"Device flow initiation failed: {flow}")
            sys.exit(1)
        print("\n" + flow["message"])
        print("等待瀏覽器授權完成...")
        result = app.acquire_token_by_device_flow(flow)

    # 5. 將最新的快取狀態序列化，寫回硬碟檔案中（確保下次能靜態自動更新）
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(cache.serialize())

    # 6. 若最後仍未成功取得 access_token，終止程式並記錄錯誤訊息
    if "access_token" not in result:
        logger.error(f"Auth failed: {result.get('error_description', result)}")
        sys.exit(1)

    return result["access_token"], app, cache


# ── Rate limiter ──────────────────────────────────────────────────────────────


class RateLimiter:
    """Sliding-window (滑動窗口演算法) limiter enforcing OneNote API caps (120/min, 400/hour)."""

    def __init__(self, per_minute: int = 115, per_hour: int = 380):
        self.per_minute = per_minute
        self.per_hour = per_hour
        self._min_q = deque()  # 紀錄一分鐘內的請求時間
        self._hour_q = deque()  # 紀錄一小時內的請求時間

    def acquire(self):
        while True:
            now = time.time()
            while self._min_q and now - self._min_q[0] > 60:
                self._min_q.popleft()
            while self._hour_q and now - self._hour_q[0] > 3600:
                self._hour_q.popleft()
            wait = 0
            if len(self._min_q) >= self.per_minute:
                # 預測下一次重置請求量的時間點，且扣除現在時間點，即可得到還要等多久才能觸達重置時間點。
                wait = max(wait, self._min_q[0] + 60 - now)
            if len(self._hour_q) >= self.per_hour:
                wait = max(wait, self._hour_q[0] + 3600 - now)
            if wait <= 0:
                break
            logger.info(
                f"[rate limiter] waiting {wait:.1f}s (min={len(self._min_q)}/115, hour={len(self._hour_q)}/380)"
            )
            # time.sleep() 實際表現出來的睡眠時間長度可能會有浮點數誤差，
            # +0.05 以確保迴圈下一輪一定可以走到 break
            time.sleep(wait + 0.05)
        now = time.time()
        self._min_q.append(now)
        self._hour_q.append(now)


# ── API helpers ───────────────────────────────────────────────────────────────


def api_get(
    url: str,
    headers: dict,
    limiter: RateLimiter,
    app: msal.PublicClientApplication,
    cache: msal.SerializableTokenCache,
    binary: bool = False,
    page_id: str | None = None,
    request_id: str | None = None,
) -> requests.Response:
    """對沒有分頁 (no pagination) 的單一 URL 請求所有資料，附設重試機制。

    此函式只會在發生「失敗的attempt時」將失敗紀錄寫入 Collection "onenote_graph_api_logs"；
    成功的請求 (含 html_hash、downloaded) 由 download_notebook() 在拿到 hash 決策後自行寫入。

    Args:
        url (str): 要請求的單一 Graph API endpoint URL（此函式不處理分頁）。
        headers (dict): HTTP 請求標頭，需含 `Authorization: Bearer <token>`；
            401 刷新 token 後會就地改寫本 dict。
        limiter (RateLimiter): 滑動窗口 rate limiter，每次送出請求前先 `acquire()` 遵守 API 上限。
        app (msal.PublicClientApplication): MSAL 應用程式物件，收到 401 時用以靜態刷新 token。
        cache (msal.SerializableTokenCache): MSAL token 快取；刷新後序列化寫回 CACHE_PATH。
        binary (bool, optional): 是否以 stream 方式下載二進位內容（如圖片）；預設 False（取文字）。
        page_id (str | None, optional): 該請求所屬的 OneNote page id，僅用於寫 log 關聯。Defaults to None.
        request_id (str | None, optional): 呼叫端可傳入共用的 request_id，讓 api_get 內部
            寫的失敗 attempt log 與呼叫端事後寫的結果 log 掛同一個 ID（同一邏輯請求可 join）；
            省略則自行生成（如 listing、圖片等各自獨立的請求）。

    Returns:
        requests.Response: 成功（2xx）的回應物件。

    Raises:
        RuntimeError: token 刷新失敗，或重試 10 次仍失敗。
        requests.exceptions.HTTPError: 遇到非暫時性的 4xx（400/403/404 等）錯誤。
    """
    request_id = request_id or uuid.uuid4().hex[:12]
    token_refreshed = False

    for attempt in range(1, 11):
        limiter.acquire()
        t0 = time.perf_counter()

        try:
            # 1. 發送請求；設 timeout 讓連線逾時 / 伺服器 hang 住會拋 Timeout 而非無限等待
            r = requests.get(url, headers=headers, stream=binary, timeout=REQUEST_TIMEOUT)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            # 2. 讓非 2xx 拋出 HTTPError，統一交給 except 分流
            r.raise_for_status()
            return r

        except requests.exceptions.HTTPError as e:
            r = e.response
            status_code = r.status_code

            # 401: Unauthorized → 換 token 後重試一次
            if status_code == 401 and not token_refreshed:
                log_api_call(
                    page_id=page_id,
                    request_id=request_id,
                    method="GET",
                    api_endpoint=url,
                    attempt_id=attempt,
                    status="failure",
                    status_code=401,
                    latency_ms=latency_ms,
                    html_hash=None,
                    downloaded=False,
                    error_msg=r.reason,
                )
                logger.warning("[401] token expired, refreshing...")
                accs = app.get_accounts()
                res = app.acquire_token_silent(SCOPES, account=accs[0])
                if not res or "access_token" not in res:
                    raise RuntimeError("Token refresh failed. Delete token cache and re-run.")
                CACHE_PATH.write_text(cache.serialize())
                headers["Authorization"] = f"Bearer {res['access_token']}"
                token_refreshed = True
                continue

            # 429: Rate-Limit
            elif status_code == 429:
                base = int(r.headers.get("Retry-After", 15))
                wait = base + min(2**attempt * 3, 60)
                log_api_call(
                    page_id=page_id,
                    request_id=request_id,
                    method="GET",
                    api_endpoint=url,
                    attempt_id=attempt,
                    status="failure",
                    status_code=429,
                    latency_ms=latency_ms,
                    html_hash=None,
                    downloaded=False,
                    error_msg=r.reason,
                )
                logger.warning(f"[429] waiting {wait}s (attempt {attempt}/10)...")
                time.sleep(wait)
                continue

            # 5xx: Server-related Errors
            elif status_code >= 500:
                wait = 2**attempt * 5
                log_api_call(
                    page_id=page_id,
                    request_id=request_id,
                    method="GET",
                    api_endpoint=url,
                    attempt_id=attempt,
                    status="failure",
                    status_code=status_code,
                    latency_ms=latency_ms,
                    html_hash=None,
                    downloaded=False,
                    error_msg=r.reason,
                )
                logger.warning(f"[{status_code}] server error, retrying in {wait}s...")
                time.sleep(wait)
                continue

            # 其他 HTTPError: 4xx（400/403/404 等）非暫時性錯誤，不重試，直接往上拋
            log_api_call(
                page_id=page_id,
                request_id=request_id,
                method="GET",
                api_endpoint=url,
                attempt_id=attempt,
                status="failure",
                status_code=status_code,
                latency_ms=latency_ms,
                html_hash=None,
                downloaded=False,
                error_msg=r.reason,
            )
            raise

        except requests.exceptions.RequestException as e:
            # 連線逾時 (Timeout)、DNS 解析失敗、連線中斷、endpoint 壞掉等傳輸層錯誤：
            # 此時可能連 r 都沒有，latency 算到出錯當下
            latency_ms = int((time.perf_counter() - t0) * 1000)
            wait = 2**attempt * 5
            log_api_call(
                page_id=page_id,
                request_id=request_id,
                method="GET",
                api_endpoint=url,
                attempt_id=attempt,
                status="failure",
                status_code=0,
                latency_ms=latency_ms,
                html_hash=None,
                downloaded=False,
                error_msg=str(e),
            )
            logger.error(f"[network] {e}, retrying in {wait}s (attempt {attempt}/10)...")
            time.sleep(wait)
            continue

    # retry 耗盡：補一筆 Collection onenote_graph_api_logs 收尾列
    log_api_call(
        page_id=page_id,
        request_id=request_id,
        method="GET",
        api_endpoint=url,
        attempt_id=attempt,
        status="failure",
        status_code=0,
        latency_ms=0,
        html_hash=None,
        downloaded=False,
        error_msg=f"Request failed after 10 retries: {url}",
    )
    raise RuntimeError(f"Request failed after 10 retries: {url}")


def get_all_from_an_api(
    url: str, headers: dict, limiter: RateLimiter, app: msal.PublicClientApplication, cache: msal.SerializableTokenCache
) -> list[dict]:
    """取得一個 API endpoint 所有分頁的資料（value；pagination by `@odata.nextLink`）。

    **Notes:**
        API endpoint 可以是 notebook URL、section URL 或 page URL。

    Args:
        url (str): 起始 API endpoint URL（notebook / section / page 皆可）。
        headers (dict): HTTP 請求標頭，需含 `Authorization: Bearer <token>`。
        limiter (RateLimiter): 滑動窗口 rate limiter，遵守 OneNote API 上限。
        app (msal.PublicClientApplication): MSAL 應用程式物件，供 401 時刷新 token。
        cache (msal.SerializableTokenCache): MSAL token 快取。

    Returns:
        list[dict]: List of returned data in dicts of all pages.
    """
    items = []
    while url:
        data = api_get(url, headers, limiter, app, cache).json()
        items.extend(data.get("value", []))
        # OneNote Graph API 採 OData (Open Data Protocol)
        url = data.get("@odata.nextLink")
    return items


# ── Notebook listing & interactive selection ──────────────────────────────────


def list_notebooks(
    headers: dict, limiter: RateLimiter, app: msal.PublicClientApplication, cache: msal.SerializableTokenCache
) -> list[dict]:
    """列出該帳號所有 notebook 清單 (含notebook id、 notebook name、section name)。

    Args:
        headers (dict): HTTP 請求標頭，需含 `Authorization: Bearer <token>`。
        limiter (RateLimiter): 滑動窗口 rate limiter，遵守 OneNote API 上限。
        app (msal.PublicClientApplication): MSAL 應用程式物件，供 401 時刷新 token。
        cache (msal.SerializableTokenCache): MSAL token 快取。

    Returns:
        list[dict]: 每個 notebook 一筆，含 `id`、`name`、`sections`（section 名稱清單）。
    """
    notebooks = get_all_from_an_api(
        "https://graph.microsoft.com/v1.0/me/onenote/notebooks", headers, limiter, app, cache
    )
    nb_sections_list = []
    for nb in notebooks:
        section_url = f"https://graph.microsoft.com/v1.0/me/onenote/notebooks/{nb['id']}/sections"
        sections = get_all_from_an_api(section_url, headers, limiter, app, cache)
        nb_sections_list.append(
            {
                "id": nb["id"],
                "name": nb["displayName"],
                "sections": [s["displayName"] for s in sections],
            }
        )
    return nb_sections_list


def prompt_selection(notebooks: list[dict]) -> list[str]:
    """以 CLI interactive 介面請使用者確定要下載哪些筆記本。

    Args:
        notebooks (list[dict]): `list_notebooks()` 回傳的 notebook 清單。

    Returns:
        list[str]: 使用者選定要下載的 notebook id 清單；輸入「全部/all」則回傳全部。
    """
    print("\n找到以下筆記本：\n")
    for i, nb in enumerate(notebooks, 1):
        sec_str = ", ".join(nb["sections"]) or "（無 section）"
        print(f"  [{i}] {nb['name']} — {len(nb['sections'])} 個 section（{sec_str}）")

    raw = input("請輸入要下載的編號（如 1 或 1,3，或輸入「全部」）：").strip()
    if raw.lower() in ("全部", "all"):
        return [nb["id"] for nb in notebooks]
    indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
    return [notebooks[i]["id"] for i in indices if 0 <= i < len(notebooks)]


# ── Helpers ───────────────────────────────────────────────────────────────────


def sanitize(name: str) -> str:
    r"""把作業系統（Windows/Mac/Linux）檔名不允許的特殊符號（例如 / \ : ? * 等）全部替換成底線 _。

    Args:
        name (str): 原始字串

    Returns:
        str: 清理後字串
    """
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "Untitled"


def _extract_user_account(sections: list[dict]) -> str | None:
    """Extract account name from the first section's self URL.

    e.g. 'https://.../users/abcd12345@gmail.com/onenote/...' → 'abcd12345'.

    Args:
        sections (list[dict]): list of data of all sections to treated.
        Sections can be the return values from function `get_all_from_an_api()`.

    Returns:
        str | None: name of user account without `@.domain.com`.
    """
    for sec in sections:
        # [^/]+  匹配"一個或多個不是斜線 / 的任意字元"
        match = re.search(r"/users/([^/]+)/onenote/", sec.get("self", ""))
        if match:
            return sanitize(match.group(1).split("@")[0])
    return None


# ── Bronze download（hash 判定 + GCS dt= 分區）────────────────────────────────


def _store_images(
    soup: BeautifulSoup,
    headers: dict,
    limiter: RateLimiter,
    app: msal.PublicClientApplication,
    cache: msal.SerializableTokenCache,
    page_id: str,
    img_prefix: str,
) -> tuple[list[str], list[str]]:
    """下載 html 引用的圖片，上傳 GCS _images/，並把 img src 改寫為相對路徑。

    回傳 (img_md5_list, img_path_list)。
    """
    img_md5: list[str] = []
    img_path: list[str] = []
    for img_tag in soup.find_all("img"):
        src = img_tag.get("src", "")
        if not src.startswith("https://"):
            continue

        # 取 resource_id
        match = re.search(r"/resources/([^/]+)/(?:content|\$value)", src)
        if not match:
            continue
        resource_id = match.group(1)

        # 取 ext
        ext = EXT_MAP.get(img_tag.get("data-src-type", "image/png"), ".png")

        # 拼出 image url 並請求後寫入 GCS
        blob_path = f"{img_prefix}/_images/{resource_id}{ext}"
        try:
            img_r = api_get(src, headers, limiter, app, cache, binary=True, page_id=page_id)
            md5 = gcs.upload_bytes(blob_path, img_r.content)
            img_tag["src"] = f"_images/{resource_id}{ext}"  # soup tag is copy-by-reference
            img_md5.append(md5)
            img_path.append(gcs.gs_uri(blob_path))
        except Exception as e:
            logger.warning(f"[image error] {e}")
    return img_md5, img_path


def download_notebooks(
    notebook_ids: list[str],
    headers: dict,
    limiter: RateLimiter,
    app: msal.PublicClientApplication,
    cache: msal.SerializableTokenCache,
    dt: str,
) -> int:
    """下載 OneNote Notebooks 的資料，且將成功下載的紀錄存於 Collection "onenote_graph_api_logs"。

    逐 notebook → section → page 下載 html，算 html_hash 與 metadata 最新一筆比對；
    有變動才 parsing、改寫圖片連結、以 dt= 分區寫入 GCS，並 upsert onenote_note_metadata。

    Args:
        notebook_ids (list[str]): 要下載的 notebook id 清單。
        headers (dict): HTTP 請求標頭，需含 `Authorization: Bearer <token>`。
        limiter (RateLimiter): 滑動窗口 rate limiter，遵守 OneNote API 上限。
        app (msal.PublicClientApplication): MSAL 應用程式物件，供 401 時刷新 token。
        cache (msal.SerializableTokenCache): MSAL token 快取。
        dt (str): 執行日期分區字串（`YYYY-MM-DD`），作為 GCS `dt=` 分區與 metadata 版本鍵。

    Returns:
        int: 本次實際偵測到 hash 變動並寫入 GCS 的新版本數。
    """
    new_versions = 0  # 計算這次下載了多少版本
    user_account: str | None = None  # 保留空間以後可改從資料庫取 user account

    for nb_id in notebook_ids:
        # 1. 取出一份 notebook 所有 sections
        nb_data = api_get(
            f"https://graph.microsoft.com/v1.0/me/onenote/notebooks/{nb_id}", headers, limiter, app, cache
        ).json()
        nb_name = sanitize(nb_data["displayName"])
        sections = get_all_from_an_api(
            f"https://graph.microsoft.com/v1.0/me/onenote/notebooks/{nb_id}/sections", headers, limiter, app, cache
        )
        logger.info(f"📓 {nb_name} ({len(sections)} sections)")

        # 2. section URL 字串包含 user account，可清理出
        if user_account is None:
            user_account = _extract_user_account(sections) or "unknown_user"
            logger.info(f"Detected account: {user_account}")

        for section in sections:
            # 3. 取出一本 section 所有的 pages
            sec_name = sanitize(section["displayName"])
            pages = get_all_from_an_api(
                f"https://graph.microsoft.com/v1.0/me/onenote/sections/{section['id']}/pages",
                headers,
                limiter,
                app,
                cache,
            )
            logger.info(f"📂 {sec_name} ({len(pages)} pages)")

            for page in pages:
                # 4. 取出一篇 page 的所有資料 (即 html 筆記內文本身)
                page_id = page["id"]
                title = sanitize(page.get("title") or "Untitled")
                request_id = uuid.uuid4().hex[:12]
                logger.info(f"{title}:")

                # 5. 下載 html 原始碼 (不 parsing) 並算 hash
                t0 = time.perf_counter()
                try:
                    raw_html = api_get(
                        f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page_id}/content",
                        headers,
                        limiter,
                        app,
                        cache,
                        page_id=page_id,
                        request_id=request_id,
                    ).text
                except Exception as e:
                    # 請求重試期間的 Error log 由 api_get() 負責寫入，
                    # 這裡僅負責在重試耗盡後，更新 collection "onenote_note_metadata"
                    upsert_version_meta(
                        page_id,
                        dt,
                        set_fields={
                            "onenote_user_id": user_account,
                            "notebook": nb_name,
                            "section": sec_name,
                            "page_title": title,
                            "topic": infer_topic([], title),
                            "status": "fetched_failed",
                            "error_msg": str(e),
                        },
                        set_on_insert_fields={
                            "enriched_md_path": None,
                            "md_md5_hash": None,
                            "enriched_md_exported_at": None,
                            "review_result": None,
                            "reviewed_by_role": None,
                            "reviewed_at": None,
                            "archived_md_path": None,
                            "archived_at": None,
                            "html_sha_hash": None,
                            "html_md5_hash": None,
                            "html_path": None,
                            "html_downloaded_at": None,
                            "attached_images": [],
                            "embedded_status": False,
                            "md_frontmatter": None,
                            "md_body": None,
                            "dismatched_img_count": None,
                            "md_has_dismatched_img": None,
                        },
                    )
                    continue

                latency_ms = int((time.perf_counter() - t0) * 1000)
                # 用 non-parsed html text 計算 html_hash
                html_hash = html_source_hash(raw_html)

                # 6. 與 Collection "onenote_note_metadata" 最新一筆 hash 比對
                latest = get_latest_version_meta(page_id)
                if latest.get("html_sha_hash") == html_hash:
                    logger.info("      ↳ hash 未變動，跳過（不存新版本）")
                    log_api_call(
                        page_id=page_id,
                        request_id=request_id,
                        method="GET",
                        api_endpoint=f".../pages/{page_id}/content",
                        attempt_id=1,
                        status="success",
                        status_code=200,
                        latency_ms=latency_ms,
                        html_hash=html_hash,
                        downloaded=False,
                        error_msg=None,
                    )
                    continue

                # 7. html hash 有變動，這時候才做 parsing，並改寫圖片連結、上傳 GCS（html + _images），取 md5
                raw_prefix = gcs.raw_note_prefix(user_account, nb_name, sec_name, dt)
                html_blob = f"{raw_prefix}/{title}.html"
                soup = BeautifulSoup(raw_html, "html.parser")
                img_md5, img_path = _store_images(soup, headers, limiter, app, cache, page_id, raw_prefix)
                # 兩個等長 list zip 成 attached_images Object 陣列（raw 端；archived 端由 gold 歸檔後回填）
                attached_images = [{"raw_image_path": p, "raw_image_md5": m} for p, m in zip(img_path, img_md5)]
                html_md5 = gcs.upload_text(html_blob, str(soup))  # 這裡的 soup 之 img tag 已被改寫過
                html_uri = gcs.gs_uri(html_blob)
                new_versions += 1
                logger.success(f"      ↳ 新版本已存 → {html_uri}")

                # 8. 更新 Collection "onenote_graph_api_logs" 下載成功紀錄
                # 與 upsert Collection "onenote_note_metadata"
                log_api_call(
                    page_id=page_id,
                    request_id=request_id,
                    method="GET",
                    api_endpoint=f".../pages/{page_id}/content",
                    attempt_id=1,
                    status="success",
                    status_code=200,
                    latency_ms=latency_ms,
                    html_hash=html_hash,
                    downloaded=True,
                    error_msg=None,
                    html_path=html_uri,
                )
                upsert_version_meta(
                    page_id,
                    dt,
                    set_fields={
                        "onenote_user_id": user_account,
                        "notebook": nb_name,
                        "section": sec_name,
                        "page_title": title,
                        "topic": infer_topic([], title),
                        "html_sha_hash": html_hash,
                        "html_md5_hash": html_md5,
                        "html_path": html_uri,
                        "html_downloaded_at": now_utc(),
                        "attached_images": attached_images,
                        "status": "bronze_stored",
                        "embedded_status": False,
                    },
                    set_on_insert_fields={
                        "enriched_md_path": None,
                        "md_md5_hash": None,
                        "enriched_md_exported_at": None,
                        "review_result": None,
                        "reviewed_by_role": None,
                        "reviewed_at": None,
                        "archived_md_path": None,
                        "archived_at": None,
                        "error_msg": None,
                        "md_frontmatter": None,
                        "md_body": None,
                        "dismatched_img_count": None,
                        "md_has_dismatched_img": None,
                    },
                )

    return new_versions


# ── Entry point ───────────────────────────────────────────────────────────────


def e_onenote_download() -> int:
    """Bronze Extract 入口：取得 token、決定 notebook 清單、下載並回傳新版本數。

    取得 token → 從 ONENOTE_NOTEBOOK_IDS 讀取或互動選擇 notebook →
    以今日 dt 呼叫 download_notebooks() → 回傳本次寫入 GCS 的新版本數。

    Returns:
        int: 本次寫入 GCS 的新版本數；未選任何 notebook 時回傳 0。
    """
    token, app, cache = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    limiter = RateLimiter()
    dt = date.today().isoformat()

    ids_from_env = os.getenv("ONENOTE_NOTEBOOK_IDS", "").strip()
    if ids_from_env:
        notebook_ids = json.loads(ids_from_env)
        logger.info(f"Using ONENOTE_NOTEBOOK_IDS from .env: {notebook_ids}")
    else:
        logger.info("Fetching notebook list...")
        notebooks = list_notebooks(headers, limiter, app, cache)
        notebook_ids = prompt_selection(notebooks)

    if not notebook_ids:
        logger.warning("No notebooks selected. Exiting.")
        return 0

    logger.info(f"Bronze layer: download from bucket={gcs.get_bucket_name()} with dt={dt}")
    new_versions = download_notebooks(notebook_ids, headers, limiter, app, cache, dt)
    logger.success(f"Bronze layer: done — {new_versions} 個新版本寫入 GCS (其餘未變動筆記今日已跳過)")
    return new_versions
