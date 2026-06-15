"""
e_onenote_download.py — Extract step for task07

Downloads selected OneNote notebooks via Microsoft Graph API and saves each page as an
HTML file with local images. Also outputs a per-section metadata CSV.

Usage:
    poetry run python -m task07_onenote_to_markdown.e_onenote_download

Required .env keys:
    ONENOTE_CLIENT_ID      Azure App Registration Client ID (public client, Notes.Read scope)
    ONENOTE_OUTPUT_DIR     Local path where HTML files are saved

Optional .env keys:
    ONENOTE_NOTEBOOK_IDS   JSON array of notebook IDs, e.g. '["id-abc","id-def"]'
                           If omitted, the script lists all notebooks and prompts for selection.
"""

import json
import os
import re
import sys
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

import msal
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from loguru import logger

from .utils.audit_log import log_api_call, upsert_page_metadata

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

CLIENT_ID = os.getenv("ONENOTE_CLIENT_ID", "")
OUTPUT_DIR = Path(os.getenv("ONENOTE_OUTPUT_DIR", ""))
AUTHORITY = "https://login.microsoftonline.com/consumers"
SCOPES = ["Notes.Read"]
CACHE_PATH = Path.home() / ".config" / "onenote-skill" / "token_cache.json"

EXT_MAP = {"image/jpeg": ".jpg",
           "image/png":  ".png",
           "image/gif":  ".gif",
           "image/webp": ".webp",
           "image/tiff": ".tiff",
           }

if not CLIENT_ID:
    logger.error("ONENOTE_CLIENT_ID is not set in .env")
    sys.exit(1)
if not OUTPUT_DIR or str(OUTPUT_DIR) == ".":
    logger.error("ONENOTE_OUTPUT_DIR is not set in .env")
    sys.exit(1)


# ── Auth ──────────────────────────────────────────────────────────────────────

def _build_msal_app() -> tuple[msal.PublicClientApplication, msal.SerializableTokenCache]:
    cache = msal.SerializableTokenCache()
    if CACHE_PATH.exists():
        cache.deserialize(CACHE_PATH.read_text())
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)
    return app, cache


def get_token() -> tuple[str, msal.PublicClientApplication, msal.SerializableTokenCache]:
    """Acquire access token; triggers device-flow login when no cached token exists."""
    app, cache = _build_msal_app()
    accounts = app.get_accounts()
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None

    if not result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            logger.error(f"Device flow initiation failed: {flow}")
            sys.exit(1)
        print("\n" + flow["message"])
        print("等待瀏覽器授權完成...")
        result = app.acquire_token_by_device_flow(flow)

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(cache.serialize())

    if "access_token" not in result:
        logger.error(f"Auth failed: {result.get('error_description', result)}")
        sys.exit(1)

    return result["access_token"], app, cache


# ── Rate limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    """Sliding-window limiter enforcing OneNote API caps (120/min, 400/hour)."""

    def __init__(self, per_minute: int = 115, per_hour: int = 380):
        self.per_minute = per_minute
        self.per_hour = per_hour
        self._min_q = deque()
        self._hour_q = deque()

    def acquire(self):
        while True:
            now = time.time()
            while self._min_q and now - self._min_q[0] > 60:
                self._min_q.popleft()
            while self._hour_q and now - self._hour_q[0] > 3600:
                self._hour_q.popleft()
            wait = 0
            if len(self._min_q) >= self.per_minute:
                wait = max(wait, self._min_q[0] + 60 - now)
            if len(self._hour_q) >= self.per_hour:
                wait = max(wait, self._hour_q[0] + 3600 - now)
            if wait <= 0:
                break
            logger.info(f"[rate limiter] waiting {wait:.1f}s "
                        f"(min={len(self._min_q)}/115, hour={len(self._hour_q)}/380)")
            time.sleep(wait + 0.05)
        now = time.time()
        self._min_q.append(now)
        self._hour_q.append(now)


# ── API helpers ───────────────────────────────────────────────────────────────

def api_get(url: str, headers: dict, limiter: RateLimiter,
            app: msal.PublicClientApplication,
            cache: msal.SerializableTokenCache,
            binary: bool = False,
            page_id: str | None = None,
            html_path: str | None = None) -> requests.Response:
    """GET with rate limiting, structured audit log, retry on 401/429/5xx."""
    request_id = uuid.uuid4().hex[:12]
    token_refreshed = False

    for attempt in range(1, 11):
        limiter.acquire()
        t0 = time.perf_counter()
        r = requests.get(url, headers=headers, stream=binary)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        if r.status_code == 401 and not token_refreshed:
            log_api_call(page_id=page_id,
                         request_id=request_id,
                         method="GET",
                         api_endpoint=url,
                         attempt_id=attempt,
                         status="failure",
                         status_code=401,
                         latency_ms=latency_ms,
                         error_msg=r.reason,
                         html_path=html_path)
            logger.warning("[401] token expired, refreshing...")
            accs = app.get_accounts()
            res = app.acquire_token_silent(SCOPES, account=accs[0])
            if not res or "access_token" not in res:
                raise RuntimeError("Token refresh failed. Delete token cache and re-run.")
            CACHE_PATH.write_text(cache.serialize())
            headers["Authorization"] = f"Bearer {res['access_token']}"
            token_refreshed = True
            continue

        if r.status_code == 429:
            base = int(r.headers.get("Retry-After", 15))
            wait = base + min(2 ** attempt * 3, 60)
            log_api_call(page_id=page_id,
                         request_id=request_id,
                         method="GET",
                         api_endpoint=url,
                         attempt_id=attempt,
                         status="failure",
                         status_code=429,
                         latency_ms=latency_ms,
                         error_msg=r.reason,
                         html_path=html_path)
            logger.warning(f"[429] waiting {wait}s (attempt {attempt}/10)...")
            time.sleep(wait)
            continue

        if r.status_code >= 500:
            wait = 2 ** attempt * 5
            log_api_call(page_id=page_id,
                         request_id=request_id,
                         method="GET",
                         api_endpoint=url,
                         attempt_id=attempt,
                         status="failure",
                         status_code=r.status_code,
                         latency_ms=latency_ms,
                         error_msg=r.reason,
                         html_path=html_path)
            logger.warning(f"[{r.status_code}] server error, retrying in {wait}s...")
            time.sleep(wait)
            continue

        r.raise_for_status()
        log_api_call(page_id=page_id,
                     request_id=request_id,
                     method="GET",
                     api_endpoint=url,
                     attempt_id=attempt,
                     status="success",
                     status_code=r.status_code,
                     latency_ms=latency_ms,
                     error_msg=None,
                     html_path=html_path)
        return r

    raise RuntimeError(f"Request failed after 10 retries: {url}")


def get_all(url: str, headers: dict, limiter: RateLimiter, app, cache) -> list[dict]:
    items = []
    while url:
        data = api_get(url, headers, limiter, app, cache).json()
        items.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return items


# ── Notebook listing & interactive selection ──────────────────────────────────

def list_notebooks(headers: dict, limiter: RateLimiter, app, cache) -> list[dict]:
    notebooks = get_all("https://graph.microsoft.com/v1.0/me/onenote/notebooks",
                        headers, limiter, app, cache
                        )
    nb_sections_list = []
    for nb in notebooks:
        sections = get_all(f"https://graph.microsoft.com/v1.0/me/onenote/notebooks/{nb['id']}/sections",
                           headers, limiter, app, cache
                           )
        nb_sections_list.append({"id":       nb["id"],
                                 "name":     nb["displayName"],
                                 "sections": [s["displayName"] for s in sections],
                                 })
    return nb_sections_list


def prompt_selection(notebooks: list[dict]) -> list[str]:
    print("\n找到以下筆記本：\n")
    for i, nb in enumerate(notebooks, 1):
        sec_str = ", ".join(nb["sections"]) or "（無 section）"
        print(f"  [{i}] {nb['name']} — {len(nb['sections'])} 個 section（{sec_str}）")

    raw = input("請輸入要下載的編號（如 1 或 1,3，或輸入「全部」）：").strip()
    if raw.lower() in ("全部", "all"):
        return [nb["id"] for nb in notebooks]
    indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
    return [notebooks[i]["id"] for i in indices if 0 <= i < len(notebooks)]


# ── Download ──────────────────────────────────────────────────────────────────

def sanitize(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip() or "Untitled"


def _extract_user_account(sections: list[dict]) -> str | None:
    """Extract account name from the first section's self URL.
    e.g. 'https://.../users/abcd12345@gmail.com/onenote/...' → 'abcd12345'
    """
    for sec in sections:
        match = re.search(r'/users/([^/]+)/onenote/', sec.get("self", ""))
        if match:
            return sanitize(match.group(1).split("@")[0])
    return None


def _parse_onenote_dt(dt_str: str) -> datetime | None:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def download_notebooks(notebook_ids: list[str], headers: dict,
                       limiter: RateLimiter, app, cache) -> tuple[int, Path]:
    total_pages = 0
    user_account: str | None = None

    for nb_id in notebook_ids:
        nb_data = api_get(f"https://graph.microsoft.com/v1.0/me/onenote/notebooks/{nb_id}",
                          headers, limiter, app, cache
                          ).json()
        nb_name = sanitize(nb_data["displayName"])
        sections = get_all(f"https://graph.microsoft.com/v1.0/me/onenote/notebooks/{nb_id}/sections",
                           headers, limiter, app, cache
                           )
        logger.info(f"📓 {nb_name} ({len(sections)} sections)")

        if user_account is None:
            user_account = _extract_user_account(sections)
            if user_account:
                logger.info(f"Detected account: {user_account}")
            else:
                logger.warning("Could not extract user account from section URLs; saving directly under OUTPUT_DIR.")

        for section in sections:
            sec_name = sanitize(section["displayName"])
            base = OUTPUT_DIR / user_account if user_account else OUTPUT_DIR
            sec_dir = base / nb_name / sec_name
            img_dir = sec_dir / "_images"
            sec_dir.mkdir(parents=True, exist_ok=True)

            pages = get_all(f"https://graph.microsoft.com/v1.0/me/onenote/sections/{section['id']}/pages",
                            headers, limiter, app, cache
                            )
            logger.info(f"  📂 {sec_name} ({len(pages)} pages)")

            for page in pages:
                page_id = page["id"]
                title = sanitize(page.get("title") or "Untitled")
                html_path = sec_dir / f"{title}.html"
                html_path_str = str(html_path.resolve())
                logger.info(f"{title}:")

                soup = BeautifulSoup(
                    api_get(f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page_id}/content",
                            headers, limiter, app, cache,
                            page_id=page_id,
                            html_path=html_path_str,
                            ).text,
                    "html.parser",
                )

                # Download embedded images and rewrite src to local relative path
                img_paths = []
                for img_tag in soup.find_all("img"):
                    src = img_tag.get("src", "")
                    if not src.startswith("https://"):
                        continue
                    match = re.search(r"/resources/([^/]+)/(?:content|\$value)", src)
                    if not match:
                        continue
                    resource_id = match.group(1)
                    ct = img_tag.get("data-src-type", "image/png")
                    ext = EXT_MAP.get(ct, ".png")
                    try:
                        img_r = api_get(src, headers, limiter, app, cache,
                                        binary=True, page_id=page_id,
                                        html_path=html_path_str)
                        img_dir.mkdir(parents=True, exist_ok=True)
                        local_img_path = img_dir / f"{resource_id}{ext}"
                        if not local_img_path.exists():
                            local_img_path.write_bytes(img_r.content)
                        img_tag["src"] = f"_images/{resource_id}{ext}"
                        img_paths.append(str(local_img_path.resolve()))
                    except Exception as e:
                        logger.warning(f"      [image error] {e}")
                style_tag = soup.new_tag("style")
                style_tag.string = "body{font-family:sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem}"
                if soup.head:
                    soup.head.append(style_tag)
                html_path.write_text(str(soup), encoding="utf-8")
                total_pages += 1

                created_dt_str = page.get("createdDateTime", "")
                modified_dt_str = page.get("lastModifiedDateTime", "")
                img_count = len(soup.find_all("img"))

                upsert_page_metadata(page_id=page_id,
                                     set_fields={"page_id":           page_id,
                                                 "notebook":          nb_name,
                                                 "section":           sec_name,
                                                 "page_title":        title,
                                                 "html_path":         str(html_path.resolve()),
                                                 "html_created_at":   _parse_onenote_dt(created_dt_str),
                                                 "html_modified_at":  _parse_onenote_dt(modified_dt_str),
                                                 "img_count_in_html": img_count,
                                                 "img_path":          img_paths,
                                                 "status":            "fetched",
                                                 },
                                     set_on_insert_fields={"md_path":          None,
                                                           "md_exported_at":   None,
                                                           "note_type":        None,
                                                           "error_msg":        None,
                                                           "review_result":    None,
                                                           "reviewed_by_role": None,
                                                           "reviewed_at":      None,
                                                           "md_archive_path":  None,
                                                           "img_archive_path": None,
                                                           "archived_at":      None,
                                                           },
                                     )

    user_output_dir = OUTPUT_DIR / user_account if user_account else OUTPUT_DIR
    return total_pages, user_output_dir


# ── Entry point ───────────────────────────────────────────────────────────────

def e_onenote_download():
    token, app, cache = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    limiter = RateLimiter()

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
        return

    logger.info(f"Downloading {len(notebook_ids)} notebook(s) → {OUTPUT_DIR}")
    total, user_output_dir = download_notebooks(notebook_ids, headers, limiter, app, cache)
    logger.success(f"✅ Done — {total} pages saved to {user_output_dir}")
    return str(user_output_dir)


if __name__ == "__main__":
    e_onenote_download()
