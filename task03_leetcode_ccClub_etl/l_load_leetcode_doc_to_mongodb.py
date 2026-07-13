from loguru import logger
from pymongo import MongoClient, UpdateOne

"""
Load：寫入 MongoDB。
ccClub 與 LeetCode 的 summary 共用同一個 collection（ccClub&leetcode_summary），
兩側各自用 $set partial update 寫入，互不覆蓋。
"""


def get_db(mongo_uri: str, db_name: str):
    client = MongoClient(mongo_uri)
    return client[db_name]


def upsert_leetcode_problems(db, problem_docs: list[dict]) -> None:
    """以 frontendQuestionId 為唯一鍵做 upsert：已存在就更新; 不存在則新增"""
    collection = db["solved_problems_on_leetcode"]
    operations = []
    for doc in problem_docs:
        operations.append(UpdateOne({"frontendQuestionId": doc["frontendQuestionId"]}, {"$set": doc}, upsert=True))
    try:
        if not operations:
            logger.warning("No operations to perform, skipping bulk_write.")
            return None
        result = collection.bulk_write(operations)
        logger.success(
            f"solved_problems_on_leetcode upsert 完成 | 新增: {result.upserted_count} | 更新: {result.modified_count}"
        )
    except Exception as e:
        logger.error(f"Bulk write failed! Error: {e}")
        raise


def upsert_leetcode_summary_partial(db, summary_partial: dict) -> None:
    """只更新 summary collection 的 leetcode 側欄位。

    用 $set 做 partial update，不覆蓋 ccClub 側之後補入的欄位。
    """
    if not summary_partial:
        logger.warning("No update operation to perform, skipping upserting.")
        return None
    try:
        collection = db["ccClub&leetcode_summary"]
        collection.update_one(
            {"snapshot_date": summary_partial["snapshot_date"]}, {"$set": summary_partial}, upsert=True
        )
        logger.success(f"ccClub&leetcode_summary (leetcode側) 快照已更新：{summary_partial['snapshot_date']}")
    except Exception as e:
        logger.error(f"Writing failed! Error: {e}")
        raise
