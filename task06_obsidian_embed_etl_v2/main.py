"""task06 v2 入口：對 task01_v2 medallion 資料做增量 embedding 與軟刪除 purge。

gate 讀 obsidian_note_metadata（status=archived AND embedded_status=false）→ 從 archived 層 chunk+embed →
先刪後插 obsidian_vectors_v2、CAS 翻 embedded_status → purge 軟刪除筆記的向量。

Usage:
    poetry run python -m task06_obsidian_embed_etl_v2.main

Required .env keys:
    MONGO_ALTAS_URI                   MongoDB Atlas connection string.
    MONGO_DB_NAME                     Target database name (skill_dashboard).
    GOOGLE_APPLICATION_CREDENTIALS    GCS service account JSON path.
    AGENT_PLATFORM_USER_CREDENTIALS   Vertex AI gemini-embedding-2 service account key.
    GCP_PROJECT_ID                    Vertex AI project.
"""

import os

from loguru import logger

from .e_scan_metadata import get_embedding_gate_list
from .l_load_to_mongodb import get_db, load_vectors_incremental_v2, purge_deleted_vectors
from .t_chunk_embed import t_chunk_and_embed_v2

BUCKET_NAME = "personal-vaults"


def run_task06_v2():
    """task06_v2 入口，對 task01_v2 的 medallion 資料做增量 embedding 與軟刪除 purge。

    1. 檢查 MongoDB 連線用的環境變數，缺任一就拋 EnvironmentError。
    2. 從 obsidian_note_metadata 挑出待向量化的筆記，若沒有就只跑 purge 後結束。
    3. 對待做筆記從 archived 層 chunk 與 embed，先刪後插進 obsidian_vectors_v2，並以 CAS 翻 embedded_status。
    4. 最後消費軟刪除訊號，清掉已被軟刪除筆記的向量。
    """
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")
    if not all([mongo_uri, db_name]):
        logger.error("請確認已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")

    logger.info("=== Task 06 v2: 向量化 + purge 開始 ===")
    db = get_db(mongo_uri, db_name)

    # Embedding：gate → chunk+embed → 先刪後插 + CAS
    # Gold - Extract: 讀取這次要 embedding 的文件之路徑
    gate_list = get_embedding_gate_list(db)

    # Gold - Transform: 打開文件，做切塊與向量化
    if not gate_list:
        logger.warning(f"=== 本次無任何需做向量化的文件，gate_list 列表長度 {len(gate_list)} ===")

        # 只做 Purge：將已被軟刪除的事實來源之 embed，從向量資料庫中移除。
        n_purged = purge_deleted_vectors(db)
        logger.success(f"=== Task 06 v2 完成 | 向量化: 0 | purge: {n_purged} ===")
        return
    vector_docs, embedded_md5_by_raw_md_path = t_chunk_and_embed_v2(gate_list, BUCKET_NAME)

    # Gold - Load: 更新到向量資料庫 (先刪前次向量化結果後插入) CAS
    load_vectors_incremental_v2(db, vector_docs, embedded_md5_by_raw_md_path)

    # Purge：將已被軟刪除的事實來源之 embed，從向量資料庫中移除。
    n_purged = purge_deleted_vectors(db)

    logger.success(f"=== Task 06 v2 完成 | 向量化: {len(embedded_md5_by_raw_md_path)} | purge: {n_purged} ===")


if __name__ == "__main__":
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv()

    # 將路徑轉為絕對路徑，確保不論在哪個目錄執行都不會出錯
    json_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not json_path:
        logger.error("請確認 .env 已設定 GOOGLE_APPLICATION_CREDENTIALS")
        raise EnvironmentError("請確認 .env 已設定 GOOGLE_APPLICATION_CREDENTIALS")
    absolute_path = Path(json_path).resolve()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(absolute_path)

    run_task06_v2()
