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


def upsert_notes(db, notes: list[dict]) -> None:
    """
    以 file_path 為唯一鍵做 upsert：已存在就更新; 不存在則新增
    """
    collection = db["obsidian_notes"]  # A collection object
    operations = []
    for note in notes:
        an_operation = UpdateOne({"file_path": note["file_path"]},
                                 {"$set": note},
                                 upsert=True
                                 )
        operations.append(an_operation)

    result = collection.bulk_write(operations)
    logger.success(f"obsidian_notes upsert 完成 | "
                   f"新增: {result.upserted_count} | 更新: {result.modified_count}"
                   )


def upsert_note_summary(db, summary: dict) -> None:
    """
    以 snapshot_date 為鍵，每天只保留最新一筆快照
    """
    collection = db["obsidian_summary"]  # A collection object
    collection.update_one({"snapshot_date": summary["snapshot_date"]},
                          {"$set": summary},
                          upsert=True
                          )
    logger.success(f"obsidian_summary 快照已更新，快照日期：{summary['snapshot_date']}")
