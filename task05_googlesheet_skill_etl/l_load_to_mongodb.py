"""task05 Load：把技能分數與雷達圖摘要以唯一鍵 upsert 寫入 MongoDB，支援冪等重跑。

1. 函式 get_db 以連線字串建立 MongoClient 並回傳指定 database。
2. 函式 upsert_skill_scores 以「雷達軸」與「經手任務」為唯一鍵把任務分數寫入指定 collection。
3. 函式 upsert_skill_radar_summary 把雷達圖摘要寫入 skill_radar_summary。
"""

import pandas as pd
from loguru import logger
from pymongo import MongoClient, UpdateOne
from pymongo.database import Database


def get_db(mongo_uri: str, db_name: str) -> Database:
    """以連線字串建立 MongoClient，回傳指定名稱的 database。

    Args:
        mongo_uri: MongoDB 連線字串。
        db_name: 目標 database 名稱。

    Returns:
        指定的 pymongo Database 物件。
    """
    client = MongoClient(mongo_uri)
    return client[db_name]


def upsert_skill_scores(db: Database, collection_name: str, df: pd.DataFrame) -> None:
    """以「雷達軸」與「經手任務」為唯一鍵，把任務分數批次 upsert 到指定 collection。

    Args:
        db: 目標 pymongo Database。
        collection_name: 要寫入的 collection 名稱。
        df: 含任務分數的 DataFrame，會轉成 document 逐筆寫入。
    """
    docs = df.to_dict("records")  # 轉成 list of dict
    collection = db[collection_name]  # A collection object
    operations = []
    for doc in docs:
        an_operation = UpdateOne({"雷達軸": doc["雷達軸"], "經手任務": doc["經手任務"]}, {"$set": doc}, upsert=True)
        operations.append(an_operation)

    result = collection.bulk_write(operations)
    logger.success(f"{collection_name} 完成 | 新增: {result.upserted_count} | 更新: {result.modified_count}")


def upsert_skill_radar_summary(db: Database, df: pd.DataFrame) -> None:
    """以 snapshot_date、雷達軸與雷達圖名稱為唯一鍵，把雷達摘要批次 upsert 到 skill_radar_summary。

    Args:
        db: 目標 pymongo Database。
        df: 含雷達摘要的 DataFrame，會轉成 document 逐筆寫入。
    """
    summary = df.to_dict("records")  # 轉成 list of dict
    collection = db["skill_radar_summary"]  # A collection object
    operations = []
    for doc in summary:
        an_operation = UpdateOne(
            {"snapshot_date": doc["snapshot_date"], "雷達軸": doc["雷達軸"], "雷達圖名稱": doc["雷達圖名稱"]},
            {"$set": doc},
            upsert=True,
        )
        operations.append(an_operation)

    result = collection.bulk_write(operations)
    logger.success(f"skill_radar_summary 快照已更新 | 新增: {result.upserted_count} | 更新: {result.modified_count}")
