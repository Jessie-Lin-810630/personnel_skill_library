"""Silver 層 Load：把 on-demand enrich 產出的 md 寫入 GCS，並 upsert 版本 metadata。

執行流程：把 md 寫入 GCS processed_note（dt= 對齊 bronze 執行日）→
upsert C3（md_path、md_md5、md_exported_at、status=pending_review）。
由 t_html_to_markdown.enrich_page 在 cache miss 時呼叫。
"""

from loguru import logger

from task07_common import gcs
from task07_common.audit_log import _now_utc, upsert_version_meta


def save_enriched_md(
    page_id: str, dt: str, page_title: str, processed_prefix: str, md_content: str
) -> tuple[str, str | None]:
    """寫 md 到 GCS 並 upsert collection onenote_note_metadata。

    processed_prefix 已含 user_id 與 dt= 分區；回傳 (md_path, md_md5)。
    """
    md_blob = f"{processed_prefix}/{page_title}.md"
    md_md5 = gcs.upload_text(md_blob, md_content)
    md_uri = gcs.gs_uri(md_blob)
    logger.info(f"💾 Silver md 已存 → {md_uri}")

    upsert_version_meta(
        page_id,
        dt,
        set_fields={
            "md_path": md_uri,
            "md_md5": md_md5,
            "md_exported_at": _now_utc(),
            "status": "pending_review",
            "error_msg": None,
        },
    )
    return md_uri, md_md5
