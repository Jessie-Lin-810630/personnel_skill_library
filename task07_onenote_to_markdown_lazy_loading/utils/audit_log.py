"""Audit logging：維護 task07 三個 MongoDB collections（企劃書 C1 / C2 / C3）的寫入工具。

三個 collections：
  onenote_graph_api_logs          — 每次 OneNote Graph API 請求一筆 (C1)
  multimodal_llm_enrichment_logs  — 每次 LLM enrichment 呼叫一筆（含 cache_hit） (C2)
  onenote_note_metadata           — 每個 (page_id, dt) 版本一筆，全程 upsert (C3)

與 v01 差異：C3 主鍵改為 (page_id, dt)，支援同頁多版本；新增 html_hash、
embedded_status、superseded 已移除（企劃書改版後不再使用）。
"""

import os
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from loguru import logger
from pymongo import MongoClient

_client = None

C1 = "onenote_graph_api_logs"
C2 = "multimodal_llm_enrichment_logs"
C3 = "onenote_note_metadata"


class Environment(StrEnum):
    LOCAL = "local"
    DEVELOPMENT = "dev"
    PRODUCTION = "prod"


def _get_db():
    """取得 (並快取) MongoDB database handle；首次呼叫才建立 MongoClient。"""
    global _client
    if _client is None:
        _client = MongoClient(os.getenv("MONGO_ALTAS_URI"))
    return _client[os.getenv("MONGO_DB_NAME")]


def _now_utc() -> datetime:
    """回傳現在的 UTC timezone-aware datetime。"""
    return datetime.now(timezone.utc)


def _environment() -> Environment:
    """讀 ENVIRONMENT env 並轉為 Environment enum；未知值記錄錯誤並 raise。"""
    env_name = os.getenv("ENVIRONMENT", "local")
    try:
        return Environment(env_name)
    except ValueError:
        logger.error(f"Unknown environment: {env_name}")
        raise RuntimeError


# ── C1: onenote_graph_api_logs ────────────────────────────────────────────────


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
    """寫一筆 OneNote Graph API 請求紀錄到 Collection C1（每次 attempt 一筆）。

    Args:
        page_id (str | None): 該請求所屬 page id；listing 等無 page 情境為 None。
        request_id (str): 同一邏輯請求的共用 ID，供 join 多個 attempt。
        method (str): HTTP method（此 task 均為 GET）。
        api_endpoint (str): 請求的 API endpoint。
        attempt_id (int): 第幾次嘗試（含重試）。
        status (Literal["success", "failure"]): 該次結果。
        status_code (int): HTTP 狀態碼；傳輸層錯誤記 0。
        latency_ms (int): 該次請求耗時（毫秒）。
        html_hash (str | None): 成功下載頁面內容時的 html sha256，否則 None。
        downloaded (bool): 是否確實寫入新版本（hash 未變動時為 False）。
        error_msg (str | None): 失敗原因；成功為 None。
        html_path (str | None, optional): 成功寫入時的 GCS URI。Defaults to None.
    """
    try:
        _get_db()[C1].insert_one(
            {
                "page_id": page_id,
                "timestamp": _now_utc(),
                "event_type": "onenote_api_download",
                "method": method,
                "api_endpoint": api_endpoint,
                "request_id": request_id,
                "attempt_id": attempt_id,
                "status": status,
                "status_code": status_code,
                "latency_ms": latency_ms,
                "html_hash": html_hash,
                "html_path": html_path,
                "downloaded": downloaded,
                "environment": _environment(),
                "error_msg": error_msg,
            }
        )
    except Exception as e:
        logger.warning(f"[audit] Failed to write {C1}: {e}")


# ── C2: multimodal_llm_enrichment_logs ────────────────────────────────────────


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
    """寫一筆 LLM enrichment 呼叫紀錄到 Collection C2（含 cache_hit，命中時 tokens 皆 0）。

    Args:
        page_id (str | None): 該次 enrichment 所屬 page id。
        html_hash (str): 對應版本的 html sha256，作為快取與配額鍵。
        model (str): 使用的 LLM 模型名稱。
        cache_hit (bool): 是否命中相同 html_hash 的既有 md（命中則未實際打 LLM）。
        trigger (Literal["on_demand", "regenerate"]): 觸發來源。
        status (Literal["success", "failure"]): 該次結果。
        latency_ms (int): 呼叫耗時（毫秒）；cache hit 為 0。
        input_tokens (int | None): 輸入 token 數；失敗或 cache hit 時可為 None / 0。
        output_tokens (int | None): 輸出 token 數。
        total_tokens (int | None): 總 token 數。
        error_msg (str | None): 失敗原因；成功為 None。
    """
    try:
        _get_db()[C2].insert_one(
            {
                "page_id": page_id,
                "html_hash": html_hash,
                "timestamp": _now_utc(),
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
        logger.warning(f"[audit] Failed to write {C2}: {e}")


def count_regenerate(html_hash: str) -> int:
    """查同一 html_hash 已成功 regenerate 的次數（作 per-note 成本上限依據）。

    在 Collection C2（multimodal_llm_enrichment_logs）數 trigger=regenerate 且成功的列數。
    """
    try:
        return _get_db()[C2].count_documents(
            {
                "html_hash": html_hash,
                "trigger": "regenerate",
                "status": "success",
            }
        )
    except Exception as e:
        logger.warning(f"[audit] Failed to count regenerate ({html_hash}): {e}")
        return 0


# ── C3: oneNote_note_metadata（主鍵 = page_id + dt）────────────────────────────


def get_latest_version_meta(page_id: str) -> dict:
    """取某頁最新一筆版本（依 html_downloaded_at 排序），供 hash 變動判定。空則 {}。"""
    try:
        cursor = _get_db()[C3].find({"page_id": page_id}).sort("html_downloaded_at", -1).limit(1)
        docs = list(cursor)
        return docs[0] if docs else {}
    except Exception as e:
        logger.warning(f"[audit] Failed to query latest version ({page_id}): {e}")
        return {}


def get_version_meta(page_id: str, dt: str) -> dict:
    """取某頁某一 dt 版本的 metadata。"""
    try:
        return _get_db()[C3].find_one({"page_id": page_id, "dt": dt}) or {}
    except Exception as e:
        logger.warning(f"[audit] Failed to query version ({page_id}, {dt}): {e}")
        return {}


def find_cached_md_by_hash(html_hash: str) -> dict:
    """在 Collection onenote_note_metadata 做 md 快取查找。

    找一列相同 html_hash 且 md_path != null 的版本；命中即可重用其 md。
    """
    try:
        return (
            _get_db()[C3].find_one(
                {
                    "html_hash": html_hash,
                    "md_path": {"$ne": None},
                }
            )
            or {}
        )
    except Exception as e:
        logger.warning(f"[audit] Failed to query cache ({html_hash}): {e}")
        return {}


def upsert_version_meta(
    page_id: str,
    dt: str,
    set_fields: dict,
    set_on_insert_fields: dict | None = None,
) -> None:
    """Upsert Collection onenote_note_metadata，主鍵為 (page_id, dt)，支援同頁多版本。"""
    update: dict = {"$set": set_fields}
    if set_on_insert_fields:
        update["$setOnInsert"] = set_on_insert_fields
    try:
        _get_db()[C3].update_one(
            {"page_id": page_id, "dt": dt},
            update,
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"[audit] Failed to upsert {C3} (page_id={page_id}, dt={dt}): {e}")
