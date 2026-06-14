from .utils.audit_log import log_page_conversion
from .t_html_to_markdown import _update_csv_row, save_csv
from pathlib import Path
from loguru import logger


def l_save_markdown(pages: list[dict]) -> None:
    """Load step: write .md files to disk and update per-section metadata CSV."""
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

            csv_path = page["csv_path"]
            if csv_path:
                new_csv_rows = _update_csv_row(page["csv_rows"],
                                               html_path,
                                               md_path,
                                               page["export_dt"]
                                               )
                save_csv(csv_path, new_csv_rows)
        except Exception as e:
            logger.error(f"⚠️  Failed to save .md [{md_path.name}]: {e}")
            if page_status == "successed":
                page_status = "save_failed"
                page_error = str(e)

        log_page_conversion(session_id=page["session_id"],
                            notebook=page["notebook"],
                            section=page["section"],
                            page_title=page["page_title"],
                            html_path=str(html_path),
                            md_path=saved_md_path,
                            note_type=page["note_type"],
                            img_count=page["img_count"],
                            status=page_status,
                            error_msg=page_error,
                            application=Path(__file__).resolve().name,
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
