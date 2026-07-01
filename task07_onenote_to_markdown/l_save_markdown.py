"""Load 步驟：把單頁 .md 寫入磁碟並 upsert MongoDB Collection 3。

執行流程：將 page 的 Markdown 內容寫入本地 .md 檔 → 依寫檔結果映射 status →
以 page_id 為鍵 upsert Collection 3（md_path、md_exported_at、note_type、status、error_msg）。
"""

from .utils.audit_log import upsert_page_metadata
from pathlib import Path
from loguru import logger

_STATUS_MAP = {
    "successed":            "pending_review",
    "upstream_task_failed": "summarized failed",
    "save_failed":          "saved failed",
}


def save_one_page(page: dict) -> None:
    """Write a single page's .md to disk and upsert Collection 3."""
    html_path: Path = page["html_path"]
    md_path: Path = page["md_path"]
    saved_md_path = None
    page_status = page["page_status"]
    page_error = page["page_error"]

    try:
        md_path.write_text(page["content"], encoding="utf-8")
        saved_md_path = str(md_path)
        logger.info(f"💾 Saved: {md_path.name}")
    except Exception as e:
        logger.error(f"⚠️  Failed to save .md [{md_path.name}]: {e}")
        if page_status == "successed":
            page_status = "save_failed"
            page_error = str(e)

    if page.get("page_id"):
        upsert_page_metadata(
            page_id=page["page_id"],
            set_fields={"md_path":        saved_md_path,
                        "md_exported_at": page["export_dt"],
                        "note_type":      page["note_type"],
                        "status":         _STATUS_MAP.get(page_status, page_status),
                        "error_msg":      page_error,
                        },
        )


def l_save_markdown(pages: list[dict]) -> None:
    """Load step: write .md files to disk and upsert Collection 3."""
    for page in pages:
        save_one_page(page)

    if pages:
        logger.success(
            f"✅ Done — {len(pages)} pages. "
            f".md files saved alongside HTML in: {pages[-1]['html_path'].parent.parent}"
        )
    else:
        logger.warning("No pages to save.")
