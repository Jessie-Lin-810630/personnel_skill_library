from loguru import logger
from pymongo import MongoClient, UpdateOne

"""
Load：寫入 MongoDB。
ccClub 與 LeetCode 的 summary 共用同一個 collection (ccClub&leetcode_summary)，
兩側各自用 $set partial update 寫入，互不覆蓋。
"""


def get_db(mongo_uri: str, db_name: str):
    client = MongoClient(mongo_uri)
    return client[db_name]


def upsert_ccclub_problems(db, problem_docs: list[dict]) -> None:
    """以 problem_id 為唯一鍵做 upsert：已存在就更新; 不存在則新增"""
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
    result = collection.bulk_write(operations)
    logger.success(
        f"solved_problems_on_ccClub upsert 完成 | 新增: {result.upserted_count} | 更新: {result.modified_count}"
    )
    return None


def upsert_ccclub_summary_partial(db, summary_partial: dict) -> None:
    """只更新 summary collection 的 ccClub 側欄位。

    用 $set 做 partial update，不覆蓋 leetcode 側已寫入的欄位。
    """
    collection = db["ccClub&leetcode_summary"]
    collection.update_one(
        {"snapshot_date": summary_partial["snapshot_date"]},
        {"$set": summary_partial},
        upsert=True,
    )
    logger.success(f"ccClub&leetcode_summary (ccClub側) 已更新：{summary_partial['snapshot_date']}")
    return None
