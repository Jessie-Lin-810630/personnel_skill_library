
from pymongo import MongoClient, UpdateOne
from pymongo.collection import Collection
from loguru import logger
from dotenv import load_dotenv
import os

"""
程式架構：
    負責所有 MongoDB 互動。
"""


def get_db(mongo_uri: str, db_name: str):
    client = MongoClient(mongo_uri)
    return client[db_name]


def upsert_repos(db, all_repo_docs: list[dict]) -> None:
    """
    以 repo_id 為唯一鍵做 upsert：已存在就更新; 不存在則新增
    """
    collection = db["github_repos"]
    operations = []
    for doc in all_repo_docs:
        an_operation = UpdateOne({"repo_id": doc["repo_id"]},
                                 {"$set": doc},
                                 upsert=True
                                 )
        operations.append(an_operation)

    result = collection.bulk_write(operations)
    logger.success(f"github_repos upsert 完成 | "
                   f"新增: {result.upserted_count} | 更新: {result.modified_count}"
                   )


def upsert_repo_summary(db, summary: dict) -> None:
    """
    以 snapshot_date 為鍵，每天只保留最新一筆快照
    """

    collection = db["github_summary"]
    collection.update_one({"snapshot_date": summary["snapshot_date"]},
                          {"$set": summary},
                          upsert=True
                          )
    logger.success(f"github_summary 快照已更新，快照日期：{summary['snapshot_date']}")
