import os
from dotenv import load_dotenv
from loguru import logger
from .e_scan_obsidian import scan_vault
from .t_clean_obsidian import build_note_documents, build_summary_document
from .l_load_to_mongodb import get_db, upsert_notes, upsert_note_summary

"""
執行E、T、L。
"""

load_dotenv()


def run_task01():
    vault_path = os.getenv("OBSIDIAN_VAULT_PATH")
    mongo_uri = os.getenv("MONGO_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([vault_path, mongo_uri, db_name]):
        logger.error("請確認 .env 已設定 OBSIDIAN_VAULT_PATH / MONGO_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 .env 已設定 OBSIDIAN_VAULT_PATH / MONGO_URI / MONGO_DB_NAME")

    logger.info("=== Task 01: Obsidian ETL 開始 ===")

    # E：Extract
    raw_notes = scan_vault(vault_path)

    # T：Transform
    notes = build_note_documents(raw_notes)
    summary = build_summary_document(raw_notes)

    # L：Load
    db = get_db(mongo_uri, db_name)
    upsert_notes(db, notes)
    upsert_note_summary(db, summary)

    logger.success("=== Task 01: Obsidian ETL 完成 ===")


if __name__ == "__main__":
    run_task01()
