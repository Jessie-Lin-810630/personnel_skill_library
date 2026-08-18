"""Silver 層 Load：把 on-demand enrich 產出的 md 寫入 GCS，並 upsert 版本到 metadata。

執行流程：
    1. 把 md 寫入 GCS processed_note（dt= 對齊 bronze 執行日）。
    2. upsert onenote_note_metadata（enriched_md_path、md_md5_hash、enriched_md_exported_at、
       status=pending_review）。

由 t_enrich_html_to_markdown 在 cache miss 時呼叫。
"""

from loguru import logger

from task07_common import gcs
from task07_common.audit_log import now_utc, upsert_version_meta


def save_enriched_md(
    page_id: str, dt: str, page_title: str, processed_prefix: str, md_content: str
) -> tuple[str, str | None]:
    """把生成好的 md 寫進 GCS，並更新該版本的 metadata 讓它進入待審狀態。

    md 檔名取自頁面標題，存放在傳入的前綴底下。寫入後把路徑、md5、匯出時間與狀態一併更新回 metadata。

    Note:
        傳入的前綴已含使用者代號與版本分區，這支函式不再自行組路徑，
        因此分區規則若有變動要改在呼叫端而不是這裡。

    Args:
        page_id: OneNote 頁面代號。
        dt: 版本分區字串。
        page_title: 頁面標題，作為 md 檔名。
        processed_prefix: Silver 層的路徑前綴，已含使用者代號與版本分區。
        md_content: 要寫入的 md 全文，含 frontmatter。

    Returns:
        md 的完整物件位址與其 md5 組成的 tuple；GCS 未回傳雜湊值時 md5 為 None。
        md 寫進 GCS，狀態欄位寫進 MongoDB 的 onenote_note_metadata。
    """
    md_blob = f"{processed_prefix}/{page_title}.md"
    md_md5_hash = gcs.upload_text(md_blob, md_content)
    md_uri = gcs.gs_uri(md_blob)
    logger.info(f"💾 Silver md 已存：{md_uri}")

    upsert_version_meta(
        page_id,
        dt,
        set_fields={
            "enriched_md_path": md_uri,
            "md_md5_hash": md_md5_hash,
            "enriched_md_exported_at": now_utc(),
            "status": "pending_review",
            "error_msg": None,
        },
    )
    return md_uri, md_md5_hash
