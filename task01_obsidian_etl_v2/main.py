"""task01_v2 medallion 變體入口：串接 Silver（CDC gate→清洗→歸檔）與 Gold（快照）。

掃 raw-notes 取 md5 → CDC gate 只挑變更檔 → 下載清洗 → copy 到 archived-notes →
以 raw_md_path upsert obsidian_note_metadata → 對消失的 raw 軟刪除 → Gold 每日快照。

Bronze（本機 gcloud storage rsync 到 raw-notes/）為前置手動步驟，不在本入口內、不清洗、不呼叫 LLM。

Usage:
    # Bronze：本機 vault 覆蓋同步到 raw-notes/（--recursive 遞迴、--delete-unmatched-destination-objects 讓刪除生效）
    gcloud storage rsync --recursive --delete-unmatched-destination-objects \
        <local_vault>/<user>/<notebook> gs://personal-vaults/raw-notes/<user>/<notebook>

    # Silver + Gold：本入口
    poetry run python -m task01_obsidian_etl_v2.main

Required .env keys:
    MONGO_ALTAS_URI                 MongoDB Atlas connection string.
    MONGO_DB_NAME                   Target database name (skill_dashboard).
    GOOGLE_APPLICATION_CREDENTIALS  GCS service account JSON path.
"""

import os

from google.cloud import storage
from loguru import logger

from .e_scan_obsidian import (
    get_existing_md5_map,
    list_raw_blobs,
    select_changed_blobs,
)
from .l_load_to_mongodb import (
    archive_note,
    build_summary,
    get_db,
    mark_note_error,
    soft_delete_missing,
    upsert_note,
    upsert_summary,
)
from .t_clean_obsidian import build_note_document

BUCKET_NAME = "personal-vaults"


def run_task01_v2():
    """task01_v2 的 Silver 與 Gold 入口，串接 CDC gate、清洗、歸檔、軟刪除與每日快照。

    1. 檢查 MongoDB 連線用的環境變數，缺任一就拋 EnvironmentError。
    2. 掃 raw-notes 取得目標 .md 與圖片 md5，再從 DB 撈既有狀態，經 CDC gate 只留新增或變更的 .md。
    3. 對每份變更的 .md 下載、清洗、複製到 archived-notes，並 upsert metadata；單筆失敗就記 error 後略過。
    4. 對 raw 已消失的筆記做軟刪除，最後對現況產出當日快照。
    """
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")
    if not all([mongo_uri, db_name]):
        logger.error("請確認已設定 .env 或 secret manager MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 .env 或 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")

    logger.info("=== Task 01 v2: Obsidian medallion ETL 開始 ===")

    # Silver - Extract：
    # 掃 raw-notes 取 markdown blobs, image blob name 與 image blob md5 hash
    md_blobs, image_md5_index = list_raw_blobs(BUCKET_NAME)

    # 從 MongoDB 撈現存的 raw_md_path 與 raw_md_md5_hash
    db = get_db(mongo_uri, db_name)
    existing_md5_map = get_existing_md5_map(db)

    # CDC gate，將二者比對，只留下有新增/變更的 .md（含 .md 未變但引用圖片變更）
    changed_blobs = select_changed_blobs(md_blobs, existing_md5_map, image_md5_index, BUCKET_NAME)

    # Silver - Transform:
    bucket = storage.Client().bucket(BUCKET_NAME)
    n_processed = 0
    n_error = 0
    for blob in changed_blobs:
        try:
            text = blob.download_as_text(encoding="utf-8")
            note_doc = build_note_document(blob, text, BUCKET_NAME, image_md5_index)

            # Silver - Load:
            archive_note(note_doc, bucket, BUCKET_NAME)
            upsert_note(db, note_doc)
            n_processed += 1
        except Exception as e:
            # 失敗以 status=error + error_msg 落地，不中斷整體流程
            logger.warning(f"清洗/歸檔失敗，記 error 並略過：{blob.name} | 原因：{e}")
            mark_note_error(db, f"gs://{BUCKET_NAME}/{blob.name}", str(e))
            n_error += 1

    # 軟刪除：raw live listing 已無、DB 尚存者標 deleted
    present_raw_paths = {f"gs://{BUCKET_NAME}/{blob.name}" for blob in md_blobs}
    n_deleted = soft_delete_missing(db, present_raw_paths)

    # Gold - Load: 每日快照
    upsert_summary(db, [build_summary(db, "obsidian_note_metadata"), build_summary(db, "onenote_note_metadata")])

    n_skipped = len(md_blobs) - len(changed_blobs)
    logger.success(
        f"=== Task 01 v2 完成 | 歸檔: {n_processed} | 失敗: {n_error} | "
        f"軟刪除: {n_deleted} | 未變更略過: {n_skipped} ==="
    )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    run_task01_v2()
