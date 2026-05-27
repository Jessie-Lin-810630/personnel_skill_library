from dotenv import load_dotenv
import os
from loguru import logger
from pathlib import Path
from task01_obsidian_etl.e_scan_obsidian import scan_vault_gs
from task06_obsidian_embed_etl.t_chunk_embed import t_chunk_and_embed
from task06_obsidian_embed_etl.l_upsert_vectors import get_db, upsert_vectors


def run_task06():
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")
    if not all([mongo_uri, db_name]):
        logger.error("請確認 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")

    logger.info("=== Task 06: Obsidian Vector DB ETL 開始 ===")

    # E：Extract
    raw_notes_metadata = scan_vault_gs("personal-vaults")

    # T：Transform
    all_vector_docs = t_chunk_and_embed(raw_notes_metadata)

    # L：Load
    db = get_db(mongo_uri, db_name)
    upsert_vectors(db, all_vector_docs)

    logger.success("=== Task 06: Obsidian Vector DB ETL 完成 ===")


if __name__ == "__main__":
    load_dotenv()
    # 將路徑轉為絕對路徑，確保不論在哪個目錄執行都不會出錯
    json_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if json_path:
        absolute_path = Path(json_path).resolve()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(absolute_path)
    run_task06()
