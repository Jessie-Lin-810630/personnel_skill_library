import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

AUDIT_LOG_DIR = Path(__file__).parent.parent / "logs"
E_AUDIT_LOG_PATH = AUDIT_LOG_DIR / "e_audit_logs.jsonl"
T_AUDIT_LOG_PATH = AUDIT_LOG_DIR / "t_audit_logs.jsonl"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(entry: dict, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_api_call(session_id: str,
                 method: str,
                 api_endpoint: str,
                 attempt: int,
                 status: str,
                 status_code: int,
                 latency_ms: int,
                 error_msg: str | None,
                 application: str,
                 ) -> None:
    entry = {"event_id":     uuid.uuid4().hex[:8],
             "timestamp":    _now_utc(),  # 如果 API 有 event datetime 就套用，否則用呼叫端的時間。
             "session_id":   session_id,
             "event_type":   "api_call",
             "method":       method,
             "api_endpoint": api_endpoint,
             "attempt":      attempt,
             "status":       status,
             "status_code":  status_code,
             "latency_ms":   latency_ms,
             "error_msg":    error_msg,
             "application":  application,
             }

    # Write in .jsonl file
    _write(entry, E_AUDIT_LOG_PATH)


def log_llm_call(session_id: str,
                 model: str,
                 html_path: str,
                 attempt: int,
                 status: str,
                 latency_ms: int,
                 input_tokens: int | None,
                 output_tokens: int | None,
                 thinking_tokens: int | None,
                 error_msg: str | None,
                 application: str,
                 ) -> None:
    # Write in .jsonl file

    _write({"event_id":            uuid.uuid4().hex[:8],
            "timestamp":           _now_utc(),
            "session_id":          session_id,
            "event_type":          "llm_call",
            "model":               model,
            "note_html_path":      html_path,
            "attempt":             attempt,
            "status":              status,
            "latency_ms":          latency_ms,
            "input_tokens":        input_tokens,
            "output_tokens":       output_tokens,
            "thinking_tokens":     thinking_tokens,
            "error_msg":           error_msg,
            "application":         application,
            }, T_AUDIT_LOG_PATH)


def log_page_conversion(session_id: str,
                        notebook: str,
                        section: str,
                        page_title: str,
                        html_path: str,
                        md_path: str | None,
                        note_type: str,
                        img_count: int,
                        status: str,
                        error_msg: str | None,
                        application: str,
                        ) -> None:
    """
    status 可能值：
      "successed"            — LLM 成功，.md 存檔成功
      "upstream_task_failed" — LLM 呼叫失敗
      "save_failed"          — LLM 成功但 .md 存檔失敗
      "skipped"              — notebook 不存在等前置錯誤
    """
    _write({"event_id":              uuid.uuid4().hex[:8],
            "timestamp":             _now_utc(),
            "session_id":            session_id,
            "event_type":            "page_conversion",
            "notebook":              notebook,
            "section":               section,
            "page_title":            page_title,
            "html_path":             html_path,
            "md_path":               md_path,
            "note_type":             note_type,
            "img_count":             img_count,
            "status":                status,
            "error_msg":             error_msg,
            "application":           application,
            }, T_AUDIT_LOG_PATH)
