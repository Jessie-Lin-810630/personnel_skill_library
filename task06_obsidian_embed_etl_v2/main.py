"""task06 v2 入口：對 task01_v2 medallion 資料做增量 embedding 與軟刪除 purge。

gate 讀 obsidian_note_metadata（status=archived AND embedded_status=false）→ 從 archived 層 chunk+embed →
先刪後插 note_vectors_multimodal、CAS 翻 embedded_status → purge 軟刪除筆記的向量。

Usage:
    poetry run python -m task06_obsidian_embed_etl_v2.main

Required .env keys:
    MONGO_ALTAS_URI                   MongoDB Atlas connection string.
    MONGO_DB_NAME                     Target database name (skill_dashboard).
    GCS_USER_CREDENTIALS              (On-premise only) GCS service account JSON path.
    AGENT_PLATFORM_USER_CREDENTIALS   (On-premise only) Agent Platform gemini-embedding-2 service account key.
    GCP_PROJECT_ID                    Agent Platform project.
"""

import os

from loguru import logger

from .e_scan_metadata import get_embedding_gate_list
from .l_load_to_mongodb import get_db, load_vectors_incremental_v2, purge_deleted_vectors
from .t_chunk_embed import t_chunk_and_embed_v2

BUCKET_NAME = "personal-vaults"


def run_task06_v2():
    """task06_v2 入口，對 task01_v2 的 medallion 資料做增量 embedding 與軟刪除 purge。

    1. 檢查 MongoDB 連線用的環境變數，缺任一就中止。
    2. 從 obsidian_note_metadata 挑出已歸檔但尚未向量化的筆記，沒有的話就只跑 purge 後結束。
    3. 讀取 archived-notes/ 下的內容做切塊與向量化，先刪後插進 note_vectors_multimodal，
       再以 CAS 把 embedded_status 翻成 true。
    4. 清掉已被軟刪除筆記的向量。

    Note:
        單份筆記處理失敗已在 t_chunk_and_embed_v2 內就地略過，這裡最外層攔的是 client 初始化
        與資料庫讀寫這類全域錯誤，只在此印一次完整 traceback 後往外拋，避免同一個例外在各層重複記錄。
        因此這支函式正常結束不代表每份筆記都成功，未成功者的 embedded_status 維持 false，下一輪會再被挑出來。

    Returns:
        None: 向量寫進 MongoDB 的 note_vectors_multimodal，各項筆數只記進 log，不回傳值。

    Raises:
        EnvironmentError: 環境變數 MONGO_ALTAS_URI 或 MONGO_DB_NAME 未設定時拋出。
        Exception: client 初始化或資料庫讀寫失敗時，記錄 traceback 後原樣往外拋。
    """
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")
    if not all([mongo_uri, db_name]):
        logger.error("請確認 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")

    logger.info("=== Task 06 v2: 向量化 + purge 開始 ===")
    db = get_db(mongo_uri, db_name)

    # 最外層統一接住內層拋出的例外，只在此處印一次完整 traceback 後再往上拋
    # （per-note 失敗已在 t_chunk_and_embed_v2 內就地略過，這裡接的是 client 初始化／DB 讀寫等全域錯誤）
    try:
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
        vector_docs, embedded_by_raw_md_path = t_chunk_and_embed_v2(gate_list, BUCKET_NAME)

        # Gold - Load: 更新到向量資料庫 (先刪前次向量化結果後插入) CAS
        load_vectors_incremental_v2(db, vector_docs, embedded_by_raw_md_path)

        # Purge：將已被軟刪除的事實來源之 embed，從向量資料庫中移除。
        n_purged = purge_deleted_vectors(db)
    except Exception:
        logger.opt(exception=True).critical("Task 06 v2 job failed")
        raise

    logger.success(f"=== Task 06 v2 完成 | 向量化: {len(embedded_by_raw_md_path)} | purge: {n_purged} ===")


if __name__ == "__main__":
    # # --------------------------------------------------------------------
    # # 本地運行時請 comment out 以下後執行。
    # from pathlib import Path
    # from dotenv import load_dotenv

    # load_dotenv()
    # # 將路徑轉為絕對路徑，確保不論在哪個目錄執行都不會出錯
    # json_path = os.getenv("GCS_USER_CREDENTIALS")
    # if not json_path:
    #     logger.error("請確認 .env 已設定 GCS_USER_CREDENTIALS")
    #     raise EnvironmentError("請確認 .env 已設定 GCS_USER_CREDENTIALS")
    # absolute_path = Path(json_path).resolve()
    # os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(absolute_path)
    # # --------------------------------------------------------------------

    run_task06_v2()
