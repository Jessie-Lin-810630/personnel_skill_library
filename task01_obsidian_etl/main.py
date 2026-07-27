import os

from loguru import logger

from .e_scan_obsidian import scan_vault_gs
from .l_load_to_mongodb import get_db, sync_notes, upsert_note_summary
from .t_clean_obsidian import build_note_documents, build_summary_document

"""
執行E、T、L。
"""


def run_task01():
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([mongo_uri, db_name]):
        logger.error("請確認 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")

    logger.info("=== Task 01: Obsidian ETL 開始 ===")

    # E：Extract
    gcs_raw_notes = scan_vault_gs("personal-vaults")

    # T：Transform
    gcs_notes = build_note_documents(gcs_raw_notes)
    summary = build_summary_document(gcs_raw_notes)

    # L：Load (CDC 狀態機：insert/update/skip/delete，並維護 embedding_done)
    db = get_db(mongo_uri, db_name)
    sync_notes(db, gcs_notes)
    upsert_note_summary(db, summary)

    logger.success("=== Task 01: Obsidian ETL 完成 ===")


if __name__ == "__main__":
    # # ---------------------------------------------------------------
    # # 本地測試區，測試與 GCS 連線後 ETL 邏輯正確
    # import os
    # from pathlib import Path

    # from dotenv import load_dotenv

    # load_dotenv()
    # # 將路徑轉為絕對路徑，確保不論在哪個目錄執行都不會出錯
    # json_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    # if not json_path:
    #     logger.error("請確認  .env 已設定 GOOGLE_APPLICATION_CREDENTIALS")
    #     raise EnvironmentError("請確認 .env 已設定 GOOGLE_APPLICATION_CREDENTIALS")
    # absolute_path = Path(json_path).resolve()
    # os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(absolute_path)
    # ---------------------------------------------------------------
    run_task01()
