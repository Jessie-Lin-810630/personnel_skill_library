from .utils.audit_log import upsert_page_metadata
from pathlib import Path
from loguru import logger

_STATUS_MAP = {
    "successed":            "pending_review",
    "upstream_task_failed": "summarized failed",
    "save_failed":          "saved failed",
}


def l_save_markdown(pages: list[dict]) -> None:
    """Load step: write .md files to disk, update per-section CSV, upsert Collection 3."""
    total_pages = 0
    total_imgs = 0

    for page in pages:
        html_path: Path = page["html_path"]
        md_path: Path = page["md_path"]
        saved_md_path = None
        page_status = page["page_status"]
        page_error = page["page_error"]

        try:
            md_path.write_text(page["content"], encoding="utf-8")
            saved_md_path = str(md_path)
        except Exception as e:
            logger.error(f"⚠️  Failed to save .md [{md_path.name}]: {e}")
            if page_status == "successed":
                page_status = "save_failed"
                page_error = str(e)

        if page.get("page_id"):
            upsert_page_metadata(
                page_id=page["page_id"],
                set_fields={"md_path":       saved_md_path,
                            "md_exported_at": page["export_dt"],
                            "note_type":     page["note_type"],
                            "status":        _STATUS_MAP.get(page_status, page_status),
                            "error_msg":     page_error,
                            },
            )

        total_imgs += page["img_count"]
        total_pages += 1

    if pages:
        sample_nb_src = pages[-1]["html_path"].parent
        logger.success(
            f"✅ Done — {total_pages} pages, {total_imgs} image refs. "
            f".md files saved alongside HTML in: {sample_nb_src.parent}"
        )
    else:
        logger.warning("No pages to save.")
