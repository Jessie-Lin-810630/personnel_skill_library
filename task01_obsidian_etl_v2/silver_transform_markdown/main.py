"""task01_v2 Silver 層入口：CDC gate 挑變更檔 → 清洗 → 歸檔 GCS → upsert metadata → 軟刪除。

1. 掃描 GCS 的 gs://<bucket>/raw-notes/，取得目標 .md 檔與圖片檔的 md5 hash，
2. 再從 MongoDB 撈既有 md5 hash，
3. 透過 hash 執行 CDC gate 只辨識出在 GCS 上發生新增或變更的 .md 與圖片檔。
4. 下載每份新增/變更的 .md、清洗、然後歸檔到 GCS gs://<bucket>/archived-notes/，
再 upsert .md 的 metadata 到 MongoDB；單筆清/歸檔失敗，都記 error 後略過，不中斷函式。
5. 對 gs://<bucket>/raw-notes/ 已消失的筆記做軟刪除。

本層不含 Gold 快照（見 gold_notes_metadata_snapshot）；db 與 bucket_name 由頂層 main 傳入。

Required .env keys:
    MONGO_ALTAS_URI                 MongoDB Atlas connection string.
    MONGO_DB_NAME                   Target database name.
    GCS_USER_CREDENTIALS            (On-premise only) GCS service account JSON path.
"""

from google.cloud import storage
from loguru import logger
from pymongo.database import Database

from .e_get_changed_files import get_existing_md5_map, list_raw_blobs, select_changed_blobs
from .l_archive_markdown import archive_note
from .l_upsert_metadata_to_mongodb import mark_note_error, soft_delete_missing, upsert_note
from .t_build_metadata_docs import build_note_document


def silver_transform_markdown(db: Database, bucket_name: str = "personal-vaults") -> None:
    """task01_v2 的 Silver 層，串接 CDC gate、清洗、歸檔、upsert 與軟刪除。

    1. 掃描 GCS 的 gs://<bucket>/raw-notes/，取得目標 .md 檔與圖片檔的 md5 hash，
    2. 再從 MongoDB 撈既有 md5 hash，
    3. 透過 hash 執行 CDC gate 只辨識出在 GCS 上發生新增或變更的 .md 與圖片檔。
    4. 下載每份新增/變更的 .md、清洗、然後歸檔到 GCS gs://<bucket>/archived-notes/，
    再 upsert .md 的 metadata 到 MongoDB；單筆清/歸檔失敗，都記 error 後略過，不中斷函式。
    5. 對 gs://<bucket>/raw-notes/ 已消失的筆記做軟刪除。

    Args:
        db: pymongo Database 物件，由頂層 main 傳入。
        bucket_name: raw-notes/ 與 archived-notes/ 所在的 GCS bucket 名稱。
        預設是 personal-vaults。
    """
    # Extract：掃 raw-notes 取 markdown blobs、image blob md5，再撈 DB 既有 md5 做 CDC gate
    md_blobs, image_md5_index = list_raw_blobs(bucket_name)
    existing_md5_map = get_existing_md5_map(db)
    changed_blobs = select_changed_blobs(md_blobs, existing_md5_map, image_md5_index, bucket_name)

    # Transform + Load：逐份下載清洗、歸檔回 GCS，並 upsert metadata
    bucket = storage.Client().bucket(bucket_name)
    n_processed = 0
    n_error = 0
    for blob in changed_blobs:
        try:
            # 從 GCS 下載 CDC gate 捕獲的 md 檔
            text = blob.download_as_text(encoding="utf-8")
            note_doc = build_note_document(blob, text, bucket_name, image_md5_index)

            archive_note(note_doc, bucket, bucket_name)
            upsert_note(db, note_doc)
            n_processed += 1
        except Exception as e:
            # 失敗以 status=error + error_msg 落地，不中斷整體流程
            logger.warning(f"清洗/歸檔失敗，記 error 並略過：{blob.name} | 原因：{e}")
            mark_note_error(db, f"gs://{bucket_name}/{blob.name}", str(e))
            n_error += 1

    # 軟刪除：raw live listing 已無、DB 尚存者標 deleted
    present_raw_paths = {f"gs://{bucket_name}/{blob.name}" for blob in md_blobs}
    n_deleted = soft_delete_missing(db, present_raw_paths)

    n_skipped = len(md_blobs) - len(changed_blobs)
    logger.success(
        f"=== Task01 v2 Silver 完成 | 歸檔: {n_processed} | 失敗: {n_error} | "
        f"軟刪除: {n_deleted} | 未變更略過: {n_skipped} ==="
    )
