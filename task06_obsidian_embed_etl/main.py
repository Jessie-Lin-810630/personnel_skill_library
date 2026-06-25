import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from task01_obsidian_etl.e_scan_obsidian import scan_vault_gs
from task06_obsidian_embed_etl.l_load_to_mongodb import (
    get_db,
    get_notes_state,
    load_vectors_incremental,
)
from task06_obsidian_embed_etl.t_chunk_embed import t_chunk_and_embed


def run_task06():
    """執行 task06 的 E→Gate→T→L：掃描 GCS、篩出待 embed 的候選、多模態向量化後增量寫入 MongoDB。

    Raises:
        EnvironmentError: 缺少 MONGO_ALTAS_URI 或 MONGO_DB_NAME 環境變數時。
    """
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")
    if not all([mongo_uri, db_name]):
        logger.error("請確認 .env 或 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 .env 或 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")

    logger.info("=== Task 06: Obsidian Vector DB ETL 開始 ===")

    # E：Extract (scan 回傳值含每檔的 GCS file_md5_hash)
    notes_on_gcs = scan_vault_gs("personal-vaults")

    # Gate：只 embed「task01 已記錄的版本」且尚未 embedding 的檔
    #   條件：file_path 在 obsidian_notes、其 file_md5_hash == GCS 現在的 file_md5_hash、embedding_done 為 False
    #   - 新檔 GCS 有但 notes 沒有 → 等下次 task01 insert
    #   - GCS 已刪但 notes 殘留     → 等下次 task01 delete
    db = get_db(mongo_uri, db_name)
    notes_state_on_db = get_notes_state(db)

    gcs_candidate_notes = []
    embedded_md5_by_file_path = {}
    for gcs_note in notes_on_gcs:
        file_path = gcs_note["file_path"]
        db_state = notes_state_on_db.get(file_path)
        if (
            db_state
            and db_state["embedding_done"] is False
            and db_state["file_md5_hash"] == gcs_note.get("file_md5_hash")
        ):
            gcs_candidate_notes.append(gcs_note)
            embedded_md5_by_file_path[file_path] = gcs_note["file_md5_hash"]

    logger.info(f"增量 embedding 候選：{len(gcs_candidate_notes)} / {len(notes_on_gcs)} 份筆記")

    # T：Transform (只對候選做多模態向量化)
    all_vector_docs, processed_file_paths = t_chunk_and_embed(gcs_candidate_notes)

    # L：Load (先刪後插 + CAS 翻 embedding_done)
    load_vectors_incremental(
        db,
        all_vector_docs,
        processed_file_paths,
        embedded_md5_by_file_path,
        vectors_collection_name="obsidian_vectors_multimodal",
    )

    logger.success("=== Task 06: Obsidian Vector DB ETL 完成 ===")


if __name__ == "__main__":
    # ---------------------------------------------------------------
    # 本地測試區，測試與 GCS 連線後 ETL 邏輯正確
    load_dotenv()
    # 將路徑轉為絕對路徑，確保不論在哪個目錄執行都不會出錯
    json_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not json_path:
        logger.error("請確認 .env 已設定 GOOGLE_APPLICATION_CREDENTIALS")
        raise EnvironmentError("請確認 .env 已設定 GOOGLE_APPLICATION_CREDENTIALS")
    absolute_path = Path(json_path).resolve()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(absolute_path)
    # ---------------------------------------------------------------
    run_task06()
