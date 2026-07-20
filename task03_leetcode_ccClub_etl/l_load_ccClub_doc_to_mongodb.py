"""task03 Load（ccClub）：把 ccClub 的題目文檔與刷題摘要以唯一鍵 upsert 寫入 MongoDB。

1. 函式 get_db 以連線字串建立 MongoClient 並回傳指定 database。
2. 函式 upsert_ccclub_problems 以 problem_id 為唯一鍵把題目文檔寫入 solved_problems_on_ccClub。
3. 函式 upsert_ccclub_summary_partial 把 ccClub 側摘要以 $set partial update 寫進 ccClub&leetcode_summary，
   此 collection 與 LeetCode 側共用、兩側互不覆蓋。
"""

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


def upsert_ccclub_problems(db: Database, problem_docs: list[dict]) -> None:
    """以 problem_id 為唯一鍵把題目文檔批次 upsert 到 solved_problems_on_ccClub。

    Args:
        db: 目標 pymongo Database。
        problem_docs: 要寫入的 ccClub 題目文檔清單。
    """
    collection = db["solved_problems_on_ccClub"]
    operations = []
    for doc in problem_docs:
        operations.append(
            UpdateOne(
                {"problem_id": doc["problem_id"]},
                {"$set": doc},
                upsert=True,
            )
        )
    try:
        if not operations:
            print("No operations to perform, skipping bulk_write.")
            return None
        result = collection.bulk_write(operations)
        logger.success(
            f"solved_problems_on_ccClub upsert 完成 | 新增: {result.upserted_count} | 更新: {result.modified_count}"
        )
    except Exception as e:
        print(f"Bulk write failed! Error: {e}")
        raise


def upsert_ccclub_summary_partial(db: Database, summary_partial: dict) -> None:
    """以 snapshot_date 為鍵，用 $set partial update 只更新 ccClub&leetcode_summary 的 ccClub 側欄位。

    不覆蓋 LeetCode 側已寫入的欄位。

    Args:
        db: 目標 pymongo Database。
        summary_partial: ccClub 側的摘要 dict。
    """
    collection = db["ccClub&leetcode_summary"]
    collection.update_one(
        {"snapshot_date": summary_partial["snapshot_date"]},
        {"$set": summary_partial},
        upsert=True,
    )
    logger.success(f"ccClub&leetcode_summary (ccClub側) 已更新：{summary_partial['snapshot_date']}")
    return None
