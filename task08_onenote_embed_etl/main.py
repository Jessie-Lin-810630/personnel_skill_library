"""task08 入口：對 task07 歸檔的 OneNote 筆記做增量多模態 embedding，寫入共用 note_vectors_multimodal。

1. gate 讀 onenote_note_metadata，挑出 status=archived 且 embedded_status=false 的版本。
2. 讀 archived 層的內容做 chunking 與多模態 embedding。
3. 先刪後插 note_vectors_multimodal，md_path 存 md_archive_path，作為 data lineage 依據。
4. 以 md_md5_hash 守衛 CAS，把 embedded_status 翻成 true。

OneNote 無軟刪除，故不含 purge。

Usage:
    poetry run python -m task08_onenote_embed_etl.main

Required .env keys:
    MONGO_ALTAS_URI                   MongoDB Atlas connection string.
    MONGO_DB_NAME                     Target database name (skill_dashboard).
    GCS_USER_CREDENTIALS              (On-premise only) GCS service account JSON path.
    AGENT_PLATFORM_USER_CREDENTIALS   (On-premise only) Agent Platform gemini-embedding-2 service account key.
    GCP_PROJECT_ID                    Agent Platform project.

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

    1. 檢查 MongoDB 連線用的環境變數，缺任一就中止。
    2. 從 onenote_note_metadata 挑出已歸檔但尚未向量化的版本，沒有的話就直接結束。
    3. 讀取 archived-notes/ 下的內容做切塊與向量化，先刪後插進 note_vectors_multimodal，
       再以 CAS 把 embedded_status 翻成 true。

    Note:
        - 單份筆記處理失敗已在 t_chunk_and_embed_onenote 內就地略過，這裡最外層攔的是 client 初始化
          與資料庫讀寫這類全域錯誤，只在此印一次完整 traceback 後往外拋，避免同一個例外在各層重複記錄。
        - 這支函式正常結束不代表每份筆記都成功，未成功者的 embedded_status 維持 false，下一輪會再被挑出來。
        - OneNote 的版本退役時由 task07 標成 status=review_closed，沒有 status=deleted 這種軟刪除，
          所以這裡不像 task06 還要另跑一步清除已刪除筆記的向量。

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
    # # --------------------------------------------------------------------
    # # 本地運行時請 uncomment 以下後執行。
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
    run_task08()
