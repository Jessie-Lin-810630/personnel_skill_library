"""task01_v2 medallion 總入口：建立連線與參數，依序串接 Silver 與 Gold 兩層。

1. 檢查 MongoDB 連線環境變數
2. get_db 建 db
3. 把 db、bucket_name 傳給 Silver（清洗歸檔）
4. Gold 做每日快照。
5. Bronze（本機 gcloud storage rsync 到 raw-notes/）為前置手動步驟，不在本入口內。

Usage:
    # Bronze：本機 vault 覆蓋同步到 raw-notes/（--recursive 遞迴、--delete-unmatched-destination-objects 讓刪除生效）
    gcloud storage rsync --recursive --delete-unmatched-destination-objects \
        <local_vault>/<user>/<notebook> gs://personal-vaults/raw-notes/<user>/<notebook>

    # Silver + Gold：本入口
    poetry run python -m task01_obsidian_etl_v2.main

Required .env keys:
    MONGO_ALTAS_URI                 MongoDB Atlas connection string.
    MONGO_DB_NAME                   Target database name.
    GCS_USER_CREDENTIALS            (On-premise only) GCS service account JSON path.
"""

import os

from loguru import logger
from pymongo import MongoClient
from pymongo.database import Database

from .gold_notes_metadata_snapshot.main import gold_notes_metadata_snapshot
from .silver_transform_markdown.main import silver_transform_markdown

BUCKET_NAME = "personal-vaults"


def get_db(mongo_uri: str, db_name: str) -> Database:
    """以連線字串建立 MongoClient，回傳指定名稱的 database。

    Args:
        mongo_uri: MongoDB Atlas 連線字串。
        db_name: 目標 database 名稱。

    Returns:
        指定的 pymongo Database 物件。
    """
    client = MongoClient(mongo_uri)
    return client[db_name]


def run_task01_v2():
    """task01_v2 總入口，建立 db 與 bucket 參數後，依序執行 Silver 與 Gold 兩層。

    1. 檢查 MongoDB 連線用的環境變數，缺任一就拋 EnvironmentError。
    2. 建立 db，呼叫 Silver 層做 CDC gate、清洗、歸檔、upsert 與軟刪除。
    3. 呼叫 Gold 層對現況產出當日快照。
    """
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")
    if not all([mongo_uri, db_name]):
        logger.error("請確認已設定 .env 或 secret manager MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 .env 或 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")

    logger.info("=== Task 01 v2: Obsidian medallion ETL 開始 ===")

    db = get_db(mongo_uri, db_name)

    # Silver：CDC gate → 清洗 → 歸檔 → upsert → 軟刪除
    silver_transform_markdown(db, BUCKET_NAME)

    # Gold：對 note metadata 現況產出當日快照
    gold_notes_metadata_snapshot(db)

    logger.success("=== Task 01 v2 完成：Silver 與 Gold 兩層均已執行 ===")


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

    run_task01_v2()
