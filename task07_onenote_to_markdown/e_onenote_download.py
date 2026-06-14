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

Audit log:  task07_onenote_to_markdown/util/logs/e_audit_logs.jsonl
"""

import csv
import json
import os
import re
import sys
import time
import uuid
from collections import deque
from pathlib import Path

import msal
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from loguru import logger

from .utils.audit_log import log_api_call

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

CLIENT_ID = os.getenv("ONENOTE_CLIENT_ID", "")
OUTPUT_DIR = Path(os.getenv("ONENOTE_OUTPUT_DIR", ""))
AUTHORITY = "https://login.microsoftonline.com/consumers"
SCOPES = ["Notes.Read"]
CACHE_PATH = Path.home() / ".config" / "onenote-skill" / "token_cache.json"

EXT_MAP = {
    "image/jpeg": ".jpg",
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

def api_get(url: str, session_id: str, headers: dict, limiter: RateLimiter,
            app: msal.PublicClientApplication,
            cache: msal.SerializableTokenCache,
            binary: bool = False) -> requests.Response:
    """GET with rate limiting, structured audit log, retry on 401/429/5xx."""
    token_refreshed = False

    for attempt in range(1, 11):
        limiter.acquire()
        t0 = time.perf_counter()
        r = requests.get(url, headers=headers, stream=binary)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        if r.status_code == 401 and not token_refreshed:
            log_api_call(session_id=session_id,
                         method="GET",
                         api_endpoint=url,
                         attempt=attempt,
                         status="fail",
                         status_code=401,
                         latency_ms=latency_ms,
                         error_msg=r.reason,
                         application=Path(__file__).resolve().name)
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
            log_api_call(session_id=session_id,
                         method="GET",
                         api_endpoint=url,
                         attempt=attempt,
                         status="fail",
                         status_code=429,
                         latency_ms=latency_ms,
                         error_msg=r.reason,
                         application=Path(__file__).resolve().name)
            logger.warning(f"[429] waiting {wait}s (attempt {attempt}/10)...")
            time.sleep(wait)
            continue

        if r.status_code >= 500:
            wait = 2 ** attempt * 5
            log_api_call(session_id=session_id,
                         method="GET",
                         api_endpoint=url,
                         attempt=attempt,
                         status="fail",
                         status_code=r.status_code,
                         latency_ms=latency_ms,
                         error_msg=r.reason,
                         application=Path(__file__).resolve().name)
            logger.warning(f"[{r.status_code}] server error, retrying in {wait}s...")
            time.sleep(wait)
            continue

        r.raise_for_status()
        log_api_call(session_id=session_id,
                     method="GET",
                     api_endpoint=url,
                     attempt=attempt,
                     status="success",
                     status_code=r.status_code,
                     latency_ms=latency_ms,
                     error_msg=None,
                     application=Path(__file__).resolve().name)
        return r

    raise RuntimeError(f"Request failed after 10 retries: {url}")


def get_all(url: str, session_id: str, headers: dict, limiter: RateLimiter,
            app, cache) -> list[dict]:
    items = []
    while url:
        data = api_get(url, session_id, headers, limiter, app, cache).json()
        items.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return items


# ── Notebook listing & interactive selection ──────────────────────────────────

def list_notebooks(session_id: str, headers: dict,
                   limiter: RateLimiter, app, cache) -> list[dict]:
    notebooks = get_all(
        "https://graph.microsoft.com/v1.0/me/onenote/notebooks",
        session_id, headers, limiter, app, cache
    )
    result = []
    for nb in notebooks:
        sections = get_all(
            f"https://graph.microsoft.com/v1.0/me/onenote/notebooks/{nb['id']}/sections",
            session_id, headers, limiter, app, cache
        )
        result.append({
            "id":       nb["id"],
            "name":     nb["displayName"],
            "sections": [s["displayName"] for s in sections],
        })
    return result


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


def download_notebooks(notebook_ids: list[str], session_id: str, headers: dict,
                       limiter: RateLimiter, app, cache) -> int:
    total_pages = 0

    for nb_id in notebook_ids:
        nb_data = api_get(
            f"https://graph.microsoft.com/v1.0/me/onenote/notebooks/{nb_id}",
            session_id, headers, limiter, app, cache
        ).json()
        nb_name = sanitize(nb_data["displayName"])
        sections = get_all(
            f"https://graph.microsoft.com/v1.0/me/onenote/notebooks/{nb_id}/sections",
            session_id, headers, limiter, app, cache
        )
        logger.info(f"📓 {nb_name} ({len(sections)} sections)")

        for section in sections:
            sec_name = sanitize(section["displayName"])
            sec_dir = OUTPUT_DIR / nb_name / sec_name
            img_dir = sec_dir / "_images"
            sec_dir.mkdir(parents=True, exist_ok=True)

            pages = get_all(
                f"https://graph.microsoft.com/v1.0/me/onenote/sections/{section['id']}/pages",
                session_id, headers, limiter, app, cache
            )
            logger.info(f"  📂 {sec_name} ({len(pages)} pages)")

            page_metadata = []
            for page in pages:
                title = sanitize(page.get("title") or "Untitled")
                logger.info(f"    ↓ {title}")

                soup = BeautifulSoup(
                    api_get(
                        f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page['id']}/content",
                        session_id, headers, limiter, app, cache
                    ).text,
                    "html.parser",
                )

                # Download embedded images and rewrite src to local relative path
                for img_tag in soup.find_all("img"):
                    src = img_tag.get("src", "")
                    if not src.startswith("https://"):
                        continue
                    match = re.search(r"/resources/([^/]+)/(?:content|\$value)", src)
                    if not match:
                        continue
                    resource_id = match.group(1)
                    try:
                        img_r = api_get(src, session_id, headers, limiter, app, cache, binary=True)
                        ct = img_r.headers.get("Content-Type", "image/png").split(";")[0].strip()
                        ext = EXT_MAP.get(ct, ".png")
                        img_dir.mkdir(parents=True, exist_ok=True)
                        img_path = img_dir / f"{resource_id}{ext}"
                        if not img_path.exists():
                            img_path.write_bytes(img_r.content)
                        img_tag["src"] = f"_images/{resource_id}{ext}"
                    except Exception as e:
                        logger.warning(f"      [image error] {e}")

                html_path = sec_dir / f"{title}.html"
                style_tag = soup.new_tag("style")
                style_tag.string = "body{font-family:sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem}"
                if soup.head:
                    soup.head.append(style_tag)
                html_path.write_text(str(soup), encoding="utf-8")
                total_pages += 1

                page_metadata.append({
                    "title":             title,
                    "created_datetime":  page.get("createdDateTime", ""),
                    "modified_datetime": page.get("lastModifiedDateTime", ""),
                    "html_path":         str(html_path.resolve()),
                })

            csv_path = sec_dir / f"{sec_name}_pages_metadata.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["title", "created_datetime", "modified_datetime", "html_path"]
                )
                writer.writeheader()
                writer.writerows(page_metadata)
            logger.info(f"    Metadata saved → {csv_path.name}")

    return total_pages


# ── Entry point ───────────────────────────────────────────────────────────────

def e_onenote_download():
    session_id = uuid.uuid4().hex[:12]
    token, app, cache = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    limiter = RateLimiter()

    ids_from_env = os.getenv("ONENOTE_NOTEBOOK_IDS", "").strip()
    if ids_from_env:
        notebook_ids = json.loads(ids_from_env)
        logger.info(f"Using ONENOTE_NOTEBOOK_IDS from .env: {notebook_ids}")
    else:
        logger.info("Fetching notebook list...")
        notebooks = list_notebooks(session_id, headers, limiter, app, cache)
        notebook_ids = prompt_selection(notebooks)

    if not notebook_ids:
        logger.warning("No notebooks selected. Exiting.")
        return

    logger.info(f"Downloading {len(notebook_ids)} notebook(s) → {OUTPUT_DIR}")
    total = download_notebooks(notebook_ids, session_id, headers, limiter, app, cache)
    logger.success(f"✅ Done — {total} pages saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    e_onenote_download()
