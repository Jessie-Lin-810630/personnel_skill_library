"""Audit logging：維護 task07 三張 MongoDB collection 的寫入工具。

1. onenote_graph_api_logs 為每次 OneNote Graph API 請求各記一筆。
2. multimodal_llm_enrichment_logs 為每次 LLM enrichment 呼叫各記一筆，含 cache_hit 標記。
3. onenote_note_metadata 為每個 (page_id, dt) 版本各記一筆、全程 upsert，
   複合唯一鍵 (Upsert key) 改為 (page_id, dt) 以支援同頁多版本。

三張 collection 寫入的 html sha256 欄位一律命名 html_sha_hash，讓跨 collection join 時欄名一致。
"""

import os
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from loguru import logger
from pymongo import MongoClient

_client = None

GRAPH_API_LOGS = "onenote_graph_api_logs"
LLM_ENRICHMENT_LOGS = "multimodal_llm_enrichment_logs"
NOTE_METADATA = "onenote_note_metadata"


class Environment(StrEnum):
    """三張稽核 collection 的 environment 欄位可用值，用來區分紀錄來自哪個部署環境。"""

    LOCAL = "local"
    DEVELOPMENT = "dev"
    PRODUCTION = "prod"


def _get_db():
    """取得 MongoDB 資料庫物件，首次呼叫才建立連線，之後重複使用同一個。

    Returns:
        對應 MONGO_DB_NAME 的 pymongo Database 物件。
    """
    global _client
    if _client is None:
        _client = MongoClient(os.getenv("MONGO_ALTAS_URI"))
    return _client[os.getenv("MONGO_DB_NAME")]


def now_utc() -> datetime:
    """取得目前時間，帶 UTC 時區。

    Returns:
        帶 UTC 時區的 datetime，可直接寫進 MongoDB。
    """
    return datetime.now(timezone.utc)


def _environment() -> Environment:
    """讀取環境變數判斷目前執行環境，寫進稽核紀錄用。

    Note:
        未設定時預設為 local；設成三個合法值以外的字串會直接中止，
        以免稽核紀錄標上無法辨識的環境而失去追查價值。

    Returns:
        對應的 Environment 列舉值，可為 local、dev 或 prod。

    Raises:
        RuntimeError: 環境變數 ENVIRONMENT 的值不在三個合法值之內時拋出。
    """
    env_name = os.getenv("ENVIRONMENT", "local")
    try:
        return Environment(env_name)
    except ValueError as e:
        logger.error(f"Unknown environment: {env_name}")
        raise RuntimeError(f"Unknown environment: {env_name}") from e


# ── onenote_graph_api_logs ────────────────────────────────────────────────────


def log_api_call(
    page_id: str | None,
    request_id: str,
    method: str,
    api_endpoint: str,
    attempt_id: int,
    status: Literal["success", "failure"],
    status_code: int,
    latency_ms: int,
    html_hash: str | None,
    downloaded: bool,
    error_msg: str | None,
    html_path: str | None = None,
) -> None:
    """寫一筆 OneNote Graph API 的請求紀錄，每次嘗試各記一筆。

    Note:
        寫入失敗只記一筆 warning，不往外拋，因為稽核紀錄不該讓主流程中斷。
        這代表呼叫端無從得知這筆紀錄是否真的寫成功。

    Args:
        page_id: 該請求所屬的頁面代號；列出筆記本這類沒有對應頁面的請求為 None。
        request_id: 同一個邏輯請求的共用代號，讓多次嘗試能被歸在一起查詢。
        method: HTTP 方法，本 task 一律是 GET。
        api_endpoint: 請求的 API 位址。
        attempt_id: 這是第幾次嘗試，含重試。
        status: 該次嘗試的結果，可為 success 或 failure。
        status_code: HTTP 狀態碼；連線逾時這類傳輸層錯誤記 0。
        latency_ms: 該次請求耗時，單位毫秒。
        html_hash: 成功下載頁面內容時的 html sha256，其餘情況為 None。
        downloaded: 是否確實寫入新版本；內容雜湊未變動而跳過時為 False。
        error_msg: 失敗原因；成功時為 None。
        html_path: 成功寫入時的完整物件位址，預設為 None。

    Returns:
        None: 紀錄寫進 MongoDB 的 onenote_graph_api_logs，不回傳值。
    """
    try:
        _get_db()[GRAPH_API_LOGS].insert_one(
            {
                "page_id": page_id,
                "timestamp": now_utc(),
                "event_type": "onenote_api_download",
                "method": method,
                "api_endpoint": api_endpoint,
                "request_id": request_id,
                "attempt_id": attempt_id,
                "status": status,
                "status_code": status_code,
                "latency_ms": latency_ms,
                "html_sha_hash": html_hash,
                "html_path": html_path,
                "downloaded": downloaded,
                "environment": _environment(),
                "error_msg": error_msg,
            }
        )
    except Exception as e:
        logger.warning(f"[audit] Failed to write {GRAPH_API_LOGS}: {e}")


# ── multimodal_llm_enrichment_logs ────────────────────────────────────────────


def log_enrichment_call(
    page_id: str | None,
    html_hash: str,
    model: str,
    cache_hit: bool,
    trigger: Literal["on_demand", "regenerate"],
    status: Literal["success", "failure"],
    latency_ms: int,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
    error_msg: str | None,
) -> None:
    """寫一筆 LLM enrichment 的呼叫紀錄，每次觸發各記一筆。

    Note:
        寫入失敗只記一筆 warning，不往外拋，因為稽核紀錄不該讓主流程中斷。
        命中快取時並未真的呼叫模型，此時耗時與各項 token 數一律記 0，
        呼叫失敗時 token 則記 None，兩者以此區分。

    Args:
        page_id: 該次 enrichment 所屬的頁面代號。
        html_hash: 對應版本的 html sha256，也是快取查找的依據。
        model: 使用的模型名稱。
        cache_hit: 是否命中相同 html sha256 的既有 md。
        trigger: 觸發來源，可為 on_demand 或 regenerate。
        status: 該次結果，可為 success 或 failure。
        latency_ms: 呼叫耗時，單位毫秒。
        input_tokens: 輸入的 token 數。
        output_tokens: 輸出的 token 數。
        total_tokens: 合計的 token 數。
        error_msg: 失敗原因；成功時為 None。

    Returns:
        None: 紀錄寫進 MongoDB 的 multimodal_llm_enrichment_logs，不回傳值。
    """
    try:
        _get_db()[LLM_ENRICHMENT_LOGS].insert_one(
            {
                "page_id": page_id,
                "html_sha_hash": html_hash,
                "timestamp": now_utc(),
                "event_type": "llm_enrichment_call",
                "model": model,
                "cache_hit": cache_hit,
                "trigger": trigger,
                "status": status,
                "latency_ms": latency_ms,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "environment": _environment(),
                "error_msg": error_msg,
            }
        )
    except Exception as e:
        logger.warning(f"[audit] Failed to write {LLM_ENRICHMENT_LOGS}: {e}")


def count_regenerate(html_hash: str) -> int:
    """查出同一份內容已經成功重新生成過幾次，作為單篇筆記的成本上限依據。

    在 enrichment 紀錄中計算相同 html sha256、觸發來源為 regenerate 且結果成功的筆數。

    Note:
        查詢失敗時記一筆 warning 並回 0，等同視為尚未用掉配額，
        因此資料庫異常時使用者仍能重新生成，而不會被誤擋。

    Args:
        html_hash: 要查詢的版本 html sha256。

    Returns:
        已成功重新生成的次數；查詢失敗時回 0。
    """
    try:
        return _get_db()[LLM_ENRICHMENT_LOGS].count_documents(
            {
                "html_sha_hash": html_hash,
                "trigger": "regenerate",
                "status": "success",
            }
        )
    except Exception as e:
        logger.warning(f"[audit] Failed to count regenerate ({html_hash}): {e}")
        return 0


# ── onenote_note_metadata（複合唯一鍵 = page_id + dt）─────────────────────────


def get_latest_version_meta(page_id: str) -> dict:
    """取出某一頁最新下載的那個版本，供 Bronze 層判斷內容是否變動。

    依 html_downloaded_at 由新到舊排序後取第一筆。

    Note:
        查無資料或查詢失敗都回空字典，兩者無法區分。
        對 Bronze 層而言這是安全的，因為取不到舊雜湊就會判定為有變動而重新下載。

    Args:
        page_id: OneNote 頁面代號。

    Returns:
        該頁最新一個版本的 metadata；查無資料或查詢失敗時為空字典。
    """
    try:
        cursor = _get_db()[NOTE_METADATA].find({"page_id": page_id}).sort("html_downloaded_at", -1).limit(1)
        docs = list(cursor)
        return docs[0] if docs else {}
    except Exception as e:
        logger.warning(f"[audit] Failed to query latest version ({page_id}): {e}")
        return {}


def get_version_meta(page_id: str, dt: str) -> dict:
    """取出某一頁指定版本的 metadata。

    Note:
        查無資料或查詢失敗都回空字典，呼叫端據此判定版本不存在並回覆 not_found。

    Args:
        page_id: OneNote 頁面代號。
        dt: 版本分區字串。

    Returns:
        該版本的 metadata；查無資料或查詢失敗時為空字典。
    """
    try:
        return _get_db()[NOTE_METADATA].find_one({"page_id": page_id, "dt": dt}) or {}
    except Exception as e:
        logger.warning(f"[audit] Failed to query version ({page_id}, {dt}): {e}")
        return {}


def find_cached_md_by_hash(html_hash: str) -> dict:
    """查找是否已有相同內容生成過的 md，命中即可重用而不必再呼叫模型。

    找出任一筆 html sha256 相同、且已經有 md 路徑的版本。

    Note:
        比對的是內容雜湊而不是頁面代號，因此不同頁面只要內容完全相同就會命中同一份 md，
        跨版本重複的內容也因此只需付費生成一次。查詢失敗時回空字典，等同未命中而改走實際生成。

    Args:
        html_hash: 要查找的 html sha256。

    Returns:
        命中的版本 metadata；未命中或查詢失敗時為空字典。
    """
    try:
        return (
            _get_db()[NOTE_METADATA].find_one(
                {
                    "html_sha_hash": html_hash,
                    "enriched_md_path": {"$ne": None},
                }
            )
            or {}
        )
    except Exception as e:
        logger.warning(f"[audit] Failed to query cache ({html_hash}): {e}")
        return {}


def get_latest_archived_version(page_id: str) -> dict:
    """取出某一頁最近一次歸檔的版本，依 archived_at 由新到舊排序後取第一筆。

    Note:
        archive_note 以此把關，避免已有較新內容歸檔後又被舊版本覆寫；
        判斷基準與審查頁只顯示 dt 不早於最後歸檔日的規則一致，兩邊要改就得一起改。

    Args:
        page_id: OneNote 頁面代號。

    Returns:
        最近一次歸檔的版本 metadata；該頁尚未歸檔過或查詢失敗時為空字典。
    """
    try:
        cursor = (
            _get_db()[NOTE_METADATA].find({"page_id": page_id, "status": "archived"}).sort("archived_at", -1).limit(1)
        )
        docs = list(cursor)
        return docs[0] if docs else {}
    except Exception as e:
        logger.warning(f"[audit] Failed to query archived version ({page_id}): {e}")
        return {}


def get_sibling_pending_versions(page_id: str, exclude_dt: str) -> list[dict]:
    """取出同一頁其他還在審閱中的版本，供歸檔時一併結束它們的審閱。

    Note:
        只挑 status 為 pending_review 的版本，因此還沒生成過 md、仍停在 bronze_stored 的舊版不會被誤退役，
        它們日後仍可各自進入審閱。

    Args:
        page_id: OneNote 頁面代號。
        exclude_dt: 要排除的版本分區字串，通常是本次要歸檔的那一版。

    Returns:
        其他仍在審閱中的版本 metadata 清單；沒有或查詢失敗時為空清單。
    """
    try:
        cursor = _get_db()[NOTE_METADATA].find(
            {"page_id": page_id, "status": "pending_review", "dt": {"$ne": exclude_dt}}
        )
        return list(cursor)
    except Exception as e:
        logger.warning(f"[audit] Failed to query sibling pending versions ({page_id}): {e}")
        return []


def upsert_version_meta(
    page_id: str,
    dt: str,
    set_fields: dict,
    set_on_insert_fields: dict | None = None,
) -> None:
    """以 page_id 與 dt 組成的複合唯一鍵 upsert 筆記 metadata，同一頁的多個版本各自成列。

    每次寫入一律更新 updated_at，並在第一次寫入時補上 created_at，兩者都取當下的 UTC 時間，
    因此呼叫端不需逐處手動帶這兩個時間戳。

    Note:
        寫入失敗只記一筆 warning，不往外拋，因此呼叫端無從得知這次更新是否真的生效。
        這是刻意的取捨：三個服務都倚賴這支函式，讓它中斷主流程的代價高於狀態短暫落後。

    Args:
        page_id: OneNote 頁面代號。
        dt: 版本分區字串。
        set_fields: 每次寫入都要覆蓋的欄位。
        set_on_insert_fields: 只在第一次寫入時補上的欄位，預設為 None。

    Returns:
        None: 結果寫進 MongoDB 的 onenote_note_metadata，不回傳值。
    """
    now = now_utc()
    update: dict = {
        "$set": {**set_fields, "updated_at": now},
        "$setOnInsert": {**(set_on_insert_fields or {}), "created_at": now},
    }
    try:
        _get_db()[NOTE_METADATA].update_one(
            {"page_id": page_id, "dt": dt},
            update,
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"[audit] Failed to upsert {NOTE_METADATA} (page_id={page_id}, dt={dt}): {e}")
