"""
audit_log.py — Audit logging for task07

Three MongoDB collections:
  onenote_graph_api_logs  — One doc per OneNote Graph API request attempt (Collection 1)
  gemini_llm_logs         — One doc per Gemini LLM call attempt (Collection 2)
  onenote_page_metadata   — One doc per OneNote page, upserted throughout the pipeline (Collection 3)
"""

from enum import StrEnum
import os
from datetime import datetime, timezone
from typing import Literal
from loguru import logger
from pymongo import MongoClient

_client = None


class Environment(StrEnum):
    LOCAL = "local"
    DEVELOPMENT = "dev"
    PRODUCTION = "prod"


def _get_db():
    global _client
    if _client is None:
        _client = MongoClient(os.getenv("MONGO_ALTAS_URI"))
    return _client[os.getenv("MONGO_DB_NAME")]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def log_api_call(page_id: str | None,
                 request_id: str,
                 method: str,
                 api_endpoint: str,
                 attempt_id: int,
                 status: Literal["success", "failure"],
                 status_code: int,
                 latency_ms: int,
                 error_msg: str | None,
                 html_path: str | None = None,
                 ) -> None:
    # 確認環境
    env_name = os.getenv("ENVIRONMENT", "local")
    try:
        environment = Environment(env_name)
    except ValueError:
        logger.error(f"Unknown environment: {env_name}")
        raise RuntimeError

    # 寫入 MongoDB Altas
    try:
        _get_db()["onenote_graph_api_logs"].insert_one({"page_id":      page_id,
                                                        "timestamp":    _now_utc(),
                                                        "event_type":   "onenote_api_download",
                                                        "user_id":      None,
                                                        "method":       method,
                                                        "api_endpoint": api_endpoint,
                                                        "request_id":   request_id,
                                                        "attempt_id":   attempt_id,
                                                        "status":       status,
                                                        "status_code":  status_code,
                                                        "latency_ms":   latency_ms,
                                                        "error_msg":    error_msg,
                                                        "environment":  environment,
                                                        "html_path":    html_path,
                                                        }
                                                       )
    except Exception as e:
        logger.warning(f"[audit] Failed to write onenote_graph_api_logs: {e}")


def log_llm_call(page_id: str | None,
                 model: str,
                 html_path: str,
                 attempt_id: int,
                 status: Literal["success", "failure"],
                 latency_ms: int,
                 input_tokens: int | None,
                 output_tokens: int | None,
                 thinking_tokens: int | None,
                 total_tokens: int | None,
                 error_msg: str | None,
                 ) -> None:
    # 確認環境
    env_name = os.getenv("ENVIRONMENT", "local")
    try:
        environment = Environment(env_name)
    except ValueError:
        logger.error(f"Unknown environment: {env_name}")
        raise RuntimeError

    try:
        _get_db()["gemini_llm_logs"].insert_one({"page_id":         page_id,
                                                 "timestamp":       _now_utc(),
                                                 "event_type":      "gemini_llm_call",
                                                 "user_id":         None,
                                                 "model":           model,
                                                 "html_path":       html_path,
                                                 "attempt_id":      attempt_id,
                                                 "status":          status,
                                                 "latency_ms":      latency_ms,
                                                 "input_tokens":    input_tokens,
                                                 "output_tokens":   output_tokens,
                                                 "thinking_tokens": thinking_tokens,
                                                 "total_tokens":    total_tokens,
                                                 "error_msg":       error_msg,
                                                 "environment":     environment,
                                                 }
                                                )
    except Exception as e:
        logger.warning(f"[audit] Failed to write gemini_llm_logs: {e}")


def get_page_meta(html_path: str) -> dict:
    """Query onenote_page_metadata by html_path. Returns {} if not found."""
    try:
        return _get_db()["onenote_page_metadata"].find_one({"html_path": html_path}) or {}
    except Exception as e:
        logger.warning(f"[audit] Failed to query onenote_page_metadata: {e}")
        return {}


def upsert_page_metadata(page_id: str,
                         set_fields: dict,
                         set_on_insert_fields: dict | None = None,
                         ) -> None:
    """
    Upsert onenote_page_metadata (Collection 3).
    set_fields      — always applied (both insert and update).
    set_on_insert_fields — only applied on first insert; preserves downstream updates on re-run.
    """
    update: dict = {"$set": set_fields}

    # 對於 update + upsert: true 這套機制導致當下為 insert 新 doc，則 $setOnInsert 、 $set 都會執行；
    # 若導致當下為 update doc，則不執行 $setOnInsert，只執行 $set。
    if set_on_insert_fields:
        update["$setOnInsert"] = set_on_insert_fields
    try:
        _get_db()["onenote_page_metadata"].update_one({"page_id": page_id},
                                                      update,
                                                      upsert=True,
                                                      )
    except Exception as e:
        logger.warning(f"[audit] Failed to upsert onenote_page_metadata (page_id={page_id}): {e}")
