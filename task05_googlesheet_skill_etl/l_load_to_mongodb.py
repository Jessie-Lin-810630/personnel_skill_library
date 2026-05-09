import pandas as pd
from pymongo import MongoClient, UpdateOne
from pymongo.collection import Collection
from loguru import logger

"""
程式架構：
    負責所有 MongoDB 互動。
"""


def get_db(mongo_uri: str, db_name: str):
    client = MongoClient(mongo_uri)
    return client[db_name]


def upsert_skill_scores(db, collection_name: str, df: pd.dataFrame) -> None:
    """
    以 雷達軸 為唯一鍵做 upsert：已存在就更新; 不存在則新增
    """
    docs = df.to_dict("records")  # 轉成 list of dict
    collection = db[collection_name]  # A collection object
    operations = []
    for doc in docs:
        an_operation = UpdateOne({"雷達軸": doc["雷達軸"]},
                                 {"$set": doc},
                                 upsert=True
                                 )
        operations.append(an_operation)

    result = collection.bulk_write(operations)
    logger.success(f"{collection_name} 完成 | "
                   f"新增: {result.upserted_count} | 更新: {result.modified_count}"
                   )


def upsert_skill_radar_summary(db, df: pd.DataFrame) -> None:
    """
    以 snapshot_date 為鍵，每天只保留最新一筆快照
    """
    summary = df.to_dict("records")  # 轉成 list of dict
    collection = db["skill_radar_summary"]  # A collection object
    operations = []
    for doc in summary:
        an_operation = UpdateOne({"snapshot_date": doc["snapshot_date"],
                                  "雷達軸": doc["雷達軸"],
                                  "雷達圖名稱": doc["雷達圖名稱"]
                                  },
                                 {"$set": doc},
                                 upsert=True
                                 )
        operations.append(an_operation)

    result = collection.bulk_write(operations)
    logger.success(f"skill_radar_summary 快照已更新 | "
                   f"新增: {result.upserted_count} | 更新: {result.modified_count}"
                   )
