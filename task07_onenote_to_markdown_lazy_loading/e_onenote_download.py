"""Bronze 層 Extract：下載 OneNote 頁面 html、比對 hash、有變動才分區寫入 GCS。

執行流程：
    1. 下載 OneNote 頁面 html，算出 html_sha_hash。
    2. 與 onenote_note_metadata 最新一筆 hash 比對，判斷這個版本有無變動。
    3. 有變動才以 dt=<執行日> 分區寫入 GCS（html + _images），並 upsert onenote_note_metadata
       （status=bronze_stored、含 attached_images 圖片血緣與 topic 初判）。

本層完全不呼叫 LLM；Silver enrichment 改由 UI on-demand 觸發。
"""

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
    """建立 MSAL 應用程式物件與其 token 快取，不取得 token。

    先檢查 CACHE_PATH 指向的快取檔是否存在，存在就把先前的紀錄讀進記憶體，
    再以此建立應用程式物件。

    Note:
        這支函式不會把更新後的快取寫回硬碟，呼叫端需自行負責寫回，否則下次執行仍要重新登入。

    Returns:
        MSAL 應用程式物件與 token 快取物件組成的 tuple。
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
    """取得存取 OneNote 所需的 token，快取失效時改走互動式登入。

    先從快取找既有帳號並嘗試在背景取得 token，此時過期的 token 會自動刷新。
    背景取不到就啟動裝置流程，把驗證碼印在畫面上等待使用者在瀏覽器完成授權。
    最後不論走哪條路徑，都把最新的快取狀態寫回硬碟。

    Note:
        互動式登入需要人工介入，這也是 Bronze 層只在地端執行、不納入雲端部署的原因。
        取不到 token 時直接中止整個行程而非拋例外，因為後續每一步都需要它。

    Returns:
        存取 token、MSAL 應用程式物件與 token 快取物件組成的 tuple，
        後兩者供後續請求在收到 401 時刷新 token。
    """
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
    """以滑動窗口演算法節流請求，讓送出頻率不超過 OneNote API 的上限。

    同時維護一分鐘與一小時兩個窗口，任一個達到上限就等待到該窗口空出名額為止。

    Note:
        預設值刻意低於官方的每分鐘 120 次與每小時 400 次，留一點餘裕吸收計時誤差。
        窗口狀態存在記憶體，因此節流只在單一行程內有效。
    """

    def __init__(self, per_minute: int = 115, per_hour: int = 380):
        """建立節流器，設定兩個窗口各自的請求上限。

        Args:
            per_minute: 每分鐘最多送出幾次請求，預設 115 次。
            per_hour: 每小時最多送出幾次請求，預設 380 次。
        """
        self.per_minute = per_minute
        self.per_hour = per_hour
        self._min_q = deque()  # 紀錄一分鐘內的請求時間
        self._hour_q = deque()  # 紀錄一小時內的請求時間

    def acquire(self):
        """取得一個送出請求的名額，額度不足時就地等待到空出為止。

        每輪先清掉已離開窗口的舊紀錄，再看兩個窗口是否還有名額；
        沒有就算出最近一個名額何時釋出並睡到那時，取得名額後把當下時間記進兩個窗口。

        Returns:
            None: 只更新這個物件的內部狀態並視需要等待，不回傳值。
        """
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
    """對單一個 API 位址送出請求，內建節流與分類重試，最多嘗試十次。

    每次送出前先向節流器取得名額。回應非 2xx 時依狀態碼分四類處理：
    收到 401 就刷新 token 後重試一次，收到 429 依伺服器指示的秒數加上退避時間後重試，
    收到 5xx 依退避時間後重試，其餘 4xx 視為非暫時性錯誤不重試而直接往外拋。
    連線逾時這類傳輸層錯誤同樣依退避時間重試。

    Note:
        這支函式只在嘗試失敗時寫稽核紀錄；成功的請求要等呼叫端拿到內容雜湊、
        判斷完是否真的要寫入新版本後才自行寫紀錄，因此成功與否的紀錄分散在兩處。
        收到 401 時會就地改寫傳入的 headers，呼叫端持有的同一個物件會跟著更新。

    Args:
        url: 要請求的單一 API 位址，這支函式不處理分頁。
        headers: HTTP 請求標頭，需含 Bearer token。
        limiter: 節流器，每次送出請求前先向它取得名額。
        app: MSAL 應用程式物件，收到 401 時用來在背景刷新 token。
        cache: MSAL token 快取，刷新後會寫回硬碟。
        binary: 是否以串流方式下載二進位內容，預設 False 代表取文字。
        page_id: 該請求所屬的頁面代號，僅用於稽核紀錄的關聯，預設為 None。
        request_id: 呼叫端傳入的共用請求代號，讓這裡寫的失敗紀錄與呼叫端事後寫的結果紀錄
            掛在同一個代號底下，預設為 None，此時自行產生一個。

    Returns:
        狀態碼為 2xx 的回應物件。

    Raises:
        RuntimeError: token 刷新失敗，或十次嘗試全部失敗時拋出。
        requests.exceptions.HTTPError: 遇到非暫時性的 4xx 錯誤時原樣往外拋。
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
    """把一個 API 位址的所有分頁資料一次取齊。

    逐次請求並累積每頁的內容，直到回應不再帶下一頁的位址為止。

    Note:
        OneNote Graph API 採 OData 協定分頁，下一頁的位址放在回應的 nextLink 欄位。
        傳入的位址可以是筆記本、章節或頁面任一種。

    Args:
        url: 起始的 API 位址。
        headers: HTTP 請求標頭，需含 Bearer token。
        limiter: 節流器，每次送出請求前先向它取得名額。
        app: MSAL 應用程式物件，收到 401 時用來在背景刷新 token。
        cache: MSAL token 快取。

    Returns:
        所有分頁內容合併後的清單；沒有任何資料時為空清單。
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
    """列出這個帳號底下所有筆記本，並逐一補上各自的章節名稱。

    Note:
        每個筆記本都要多送一次請求才能取得章節，因此筆記本數量會等比放大請求數與節流等待時間。

    Args:
        headers: HTTP 請求標頭，需含 Bearer token。
        limiter: 節流器，每次送出請求前先向它取得名額。
        app: MSAL 應用程式物件，收到 401 時用來在背景刷新 token。
        cache: MSAL token 快取。

    Returns:
        每個筆記本一筆的清單，各含 id、name 與 sections 三個鍵，最後一個是章節名稱清單。
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
    """在終端機列出所有筆記本，請使用者輸入編號決定這次要下載哪幾本。

    可以輸入單一編號、以逗號分隔的多個編號，或輸入全部代表全選。

    Note:
        這一步需要人工輸入，是 Bronze 層只能在地端執行的原因之一。
        無法解析成編號的輸入會被略過，超出範圍的編號同樣被濾掉，因此全部輸入錯誤時會得到空清單。

    Args:
        notebooks: list_notebooks 回傳的筆記本清單。

    Returns:
        使用者選定要下載的筆記本代號清單；沒有選中任何一本時為空清單。
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
    """把作業系統檔名不允許的符號全部換成底線，讓字串可安全用作路徑的一段。

    處理的符號涵蓋各家作業系統的限制，包含斜線、冒號、問號、星號與控制字元等。

    Args:
        name: 原始字串，通常是筆記本、章節或頁面的名稱。

    Returns:
        清理後的字串；清理完為空字串時改回 Untitled，避免產生沒有名稱的路徑。
    """
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "Untitled"


def _extract_user_account(sections: list[dict]) -> str | None:
    """從章節資料的自身位址中解析出使用者帳號名稱。

    逐一檢查各章節的自身位址，找到第一個符合格式的就取出其中的帳號段落，
    去掉網域部分後再做檔名清理。

    Note:
        帳號名稱會成為 GCS 路徑的一段，因此必須先清掉檔名不允許的符號。
        取自章節而非帳號 API，是為了省下一次額外請求。

    Args:
        sections: 章節資料清單，通常是 get_all_from_an_api 的回傳值。

    Returns:
        不含網域的使用者帳號名稱；所有章節都解析不出時回 None。
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
    """下載這份 html 引用的所有圖片，上傳到 GCS，並把原本的圖片連結改寫成相對路徑。

    逐一取出圖片標籤，從其連結解析出資源代號與副檔名，組出存放路徑後下載並上傳，
    最後把該標籤的連結改寫成指向圖片資料夾的相對路徑。

    Note:
        這支函式就地修改傳入的 soup 物件，呼叫端隨後直接把它序列化寫入 GCS 即可。
        單張圖片失敗只記一筆 warning 後略過，不中斷整份筆記，
        因此回傳的張數可能少於 html 中出現的圖片數，該圖的連結也會維持原本的外部位址。

    Args:
        soup: 已解析的 html 物件，其圖片標籤會被就地改寫。
        headers: HTTP 請求標頭，需含 Bearer token。
        limiter: 節流器，每次送出請求前先向它取得名額。
        app: MSAL 應用程式物件，收到 401 時用來在背景刷新 token。
        cache: MSAL token 快取。
        page_id: 該筆記的頁面代號，僅用於稽核紀錄的關聯。
        img_prefix: 這份筆記在 Bronze 層的路徑前綴，圖片存放在其底下的圖片資料夾。

    Returns:
        成功上傳的圖片 md5 清單與其完整位址清單組成的 tuple，兩份清單等長且順序一致。
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
    """逐一走訪選定的筆記本、章節與頁面，把內容有變動的筆記下載並寫入 GCS。

    每個筆記本先取出所有章節，每個章節再取出所有頁面，最後逐頁下載 html 原始碼並計算內容雜湊。
    雜湊與該頁最新一筆紀錄相同就跳過不存新版本，不同才解析 html、下載並改寫圖片連結，
    以版本分區寫入 GCS，並更新該版本的 metadata。

    Note:
        內容雜湊在解析 html 之前就先算，因此未變動的筆記完全不需要解析與下載圖片，
        這是每週重跑成本能壓低的主因。
        使用者帳號從第一個取得的章節解析一次後就沿用，因此同一次執行只支援單一帳號。
        單頁下載失敗不中斷整批，改把該版本狀態記成 fetched_failed 後跳過，下一輪會再嘗試。

    Args:
        notebook_ids: 要下載的筆記本代號清單。
        headers: HTTP 請求標頭，需含 Bearer token。
        limiter: 節流器，每次送出請求前先向它取得名額。
        app: MSAL 應用程式物件，收到 401 時用來在背景刷新 token。
        cache: MSAL token 快取。
        dt: 版本分區字串，值為本次執行日期，同時作為 GCS 的分區與 metadata 的版本欄位。

    Returns:
        本次確實偵測到內容變動並寫入 GCS 的新版本數；
        html 與圖片寫進 GCS，版本 metadata 與請求紀錄寫進 MongoDB。
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
    """Bronze 層 Extract 的入口，取得授權、選定筆記本後執行下載。

    先取得 token 並建立請求標頭與節流器，列出所有筆記本請使用者選擇，
    最後以今日日期作為版本分區呼叫下載。

    Note:
        版本分區固定取執行當日日期，因此同一天重跑會寫進同一個分區、覆蓋當日的內容，
        跨日重跑則會產生新版本供人工審閱。

    Returns:
        本次寫入 GCS 的新版本數；使用者沒有選擇任何筆記本時回 0 且不執行下載。
    """
    token, app, cache = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    limiter = RateLimiter()
    dt = date.today().isoformat()

    logger.info("Fetching notebook list...")
    notebooks = list_notebooks(headers, limiter, app, cache)
    notebook_ids = prompt_selection(notebooks)

    if not notebook_ids:
        logger.warning("No notebooks selected. Exiting.")
        return 0

    logger.info(f"Bronze layer: downloading to GCS bucket={gcs.get_bucket_name()} with dt={dt}")
    new_versions = download_notebooks(notebook_ids, headers, limiter, app, cache, dt)
    logger.success(f"Bronze layer: done — {new_versions} 個新版本寫入 GCS (其餘未變動筆記今日已跳過)")
    return new_versions
