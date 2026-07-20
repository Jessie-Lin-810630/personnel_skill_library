"""task08 入口：對 task07 歸檔的 OneNote 筆記做增量多模態 embedding，寫入共用 note_vectors_multimodal。

gate 讀 onenote_note_metadata（status=archived AND embedded_status=false）→ 從 archived 層 chunk+embed →
先刪後插 note_vectors_multimodal（血緣欄 md_path=md_archive_path）、以 md_md5_hash 守衛 CAS 翻 embedded_status。
OneNote 無軟刪除，故不含 purge。

Usage:
    poetry run python -m task08_onenote_embed_etl.main

Required .env keys:
    MONGO_ALTAS_URI                   MongoDB Atlas connection string.
    MONGO_DB_NAME                     Target database name (skill_dashboard).
    GCS_USER_CREDENTIALS              (On-premise only) GCS service account JSON path.
    AGENT_PLATFORM_USER_CREDENTIALS   (On-premise only) Vertex AI gemini-embedding-2 service account key.
    GCP_PROJECT_ID                    Vertex AI project.

Optional .env keys:
    ONENOTE_GCS_BUCKET                GCS data lake bucket (defaults to onenote-vaults).
"""

import os

from loguru import logger

from .e_scan_metadata import get_embedding_gate_list
from .l_load_to_mongodb import get_db, load_vectors_incremental_onenote
from .t_chunk_embed import t_chunk_and_embed_onenote

BUCKET_NAME = "onenote-vaults"


def run_task08():
    """task08 入口，對 task07 的 archived OneNote 筆記做增量 embedding，寫入共用 note_vectors_multimodal。

    1. 檢查 MongoDB 連線用的環境變數，缺任一就拋 EnvironmentError。
    2. 從 onenote_note_metadata 挑出待向量化的版本，若沒有就直接結束。
    3. 對待做版本從 archived 層 chunk 與 embed，先刪後插進 note_vectors_multimodal，並以 CAS 翻 embedded_status。
    """
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")
    if not all([mongo_uri, db_name]):
        logger.error("請確認 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")

    logger.info("=== Task 08: OneNote 向量化開始 ===")
    db = get_db(mongo_uri, db_name)

    # 最外層統一接住內層拋出的例外，只在此處印一次完整 traceback 後再往上拋
    # （per-note 失敗已在 t_chunk_and_embed_onenote 內就地略過，這裡接的是 client 初始化／DB 讀寫等全域錯誤）
    try:
        # Extract: 讀取這次要 embedding 的 archived 版本
        gate_list = get_embedding_gate_list(db)
        if not gate_list:
            logger.warning("=== 本次無任何需做向量化的 onenote 版本 ===")
            logger.success("=== Task 08 完成 | 向量化: 0 ===")
            return

        # Transform: 打開歸檔 md，做切塊與向量化
        vector_docs, embedded_md5_by_md_path = t_chunk_and_embed_onenote(gate_list, BUCKET_NAME)

        # Load: 更新到向量資料庫 (先刪前次向量化結果後插入) + CAS
        load_vectors_incremental_onenote(db, vector_docs, embedded_md5_by_md_path)
    except Exception:
        logger.opt(exception=True).critical("Task 08 job failed")
        raise

    logger.success(f"=== Task 08 完成 | 向量化: {len(embedded_md5_by_md_path)} ===")


if __name__ == "__main__":
    run_task08()
