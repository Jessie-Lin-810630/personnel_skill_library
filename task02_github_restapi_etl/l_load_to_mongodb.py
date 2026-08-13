"""task02 Load：把 repo document 與彙整摘要寫入 MongoDB，全部以唯一鍵 upsert 支援冪等重跑。

1. 函式 get_db 以連線字串建立 MongoClient 並回傳指定 database。
2. 函式 upsert_repos 以 repo_id 為唯一鍵把 repo document 批次寫入 github_repos。
3. 函式 upsert_repo_summary 以 snapshot_date 為唯一鍵把摘要寫入 github_summary，每天只保留最新一筆快照。
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


def upsert_repos(db: Database, all_repo_docs: list[dict]) -> None:
    """以 repo_id 為唯一鍵把所有 repo document 批次 upsert 到 github_repos。

    把每份 document 各組成一個 upsert 操作，最後以一次批次寫入送出。

    Note:
        - 以 repo_id 為唯一鍵，repo 改名後仍會更新到同一筆而不是多出一份；
          重跑同一天的抓取只會覆蓋既有內容，因此這支函式可以重複執行。
        - 寫入採覆蓋既有欄位的方式，document 這次沒帶到的欄位會留著上一次的值，不會被清掉。

    Args:
        db: 目標 pymongo Database。
        all_repo_docs: 要寫入的 repo document 清單。

    Returns:
        None: document 寫進 MongoDB 的 github_repos，新增與更新筆數只記進 log，不回傳值。

    Raises:
        pymongo.errors.InvalidOperation: 傳入空清單導致批次寫入沒有任何操作時拋出。
    """
    collection = db["github_repos"]
    operations = []
    for doc in all_repo_docs:
        an_operation = UpdateOne({"repo_id": doc["repo_id"]}, {"$set": doc}, upsert=True)
        operations.append(an_operation)

    result = collection.bulk_write(operations)
    logger.success(f"github_repos upsert 完成 | 新增: {result.upserted_count} | 更新: {result.modified_count}")


def upsert_repo_summary(db: Database, summary: dict) -> None:
    """以 snapshot_date 為唯一鍵把摘要 upsert 到 github_summary，每天只保留最新一筆快照。

    Note:
        - snapshot_date 只到日，所以同一天多次執行會覆蓋當天那筆，歷史天數的快照不受影響，
          github_summary 因此是一天一列的時間序列。

    Args:
        db: 目標 pymongo Database。
        summary: build_summary_document 產出的摘要字典。

    Returns:
        None: 摘要寫進 MongoDB 的 github_summary，快照日期只記進 log，不回傳值。
    """
    collection = db["github_summary"]
    collection.update_one({"snapshot_date": summary["snapshot_date"]}, {"$set": summary}, upsert=True)
    logger.success(f"github_summary 快照已更新，快照日期：{summary['snapshot_date']}")
