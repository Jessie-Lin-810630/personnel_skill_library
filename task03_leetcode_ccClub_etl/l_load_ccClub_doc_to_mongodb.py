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

    把每份文檔各組成一個 upsert 操作，最後以一次批次寫入送出。

    Note:
        - 傳入空清單時直接跳過，因為批次寫入不接受空的操作清單。
        - 以題號為唯一鍵，重跑只會覆蓋既有題目而不會重複新增，因此這支函式可以重複執行。
        - 這裡只增不減，ccClub 上已移除的題目不會從 collection 消失。

    Args:
        db: 目標 pymongo Database。
        problem_docs: 要寫入的 ccClub 題目文檔清單。

    Returns:
        None: 題目寫進 MongoDB 的 solved_problems_on_ccClub，新增與更新筆數只記進 log，不回傳值。

    Raises:
        Exception: 批次寫入失敗時，記一行訊息後原樣往外拋。
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
            logger.warning("No operations to perform, skipping bulk_write.")
            return None
        result = collection.bulk_write(operations)
        logger.success(
            f"solved_problems_on_ccClub upsert 完成 | 新增: {result.upserted_count} | 更新: {result.modified_count}"
        )
    except Exception as e:
        logger.error(f"Bulk write failed! Error: {e}")
        raise


def upsert_ccclub_summary_partial(db: Database, summary_partial: dict) -> None:
    """以 snapshot_date 為唯一鍵，只更新 ccClub&leetcode_summary 裡屬於 ccClub 的那幾個欄位。

    以當天日期定位文件，只寫入傳入的那幾個欄位。

    Note:
        - 只寫入指定欄位而不整份取代，所以同一天由 upsert_leetcode_summary_partial 寫入的欄位不會被清掉，
          兩個來源寫進同一份文件、先後順序不影響結果。
        - snapshot_date 只到日，同一天多次執行會覆蓋當天那筆，歷史天數不受影響。
        - 與 LeetCode 那支不同，這裡沒有空摘要就跳過的保護，因為上游一定會產出摘要。

    Args:
        db: 目標 pymongo Database。
        summary_partial: build_ccclub_summary_partial 產出的摘要字典。

    Returns:
        None: 摘要寫進 MongoDB 的 ccClub&leetcode_summary，快照日期只記進 log，不回傳值。

    Raises:
        KeyError: summary_partial 缺少 snapshot_date 時拋出。
    """
    collection = db["ccClub&leetcode_summary"]
    collection.update_one(
        {"snapshot_date": summary_partial["snapshot_date"]},
        {"$set": summary_partial},
        upsert=True,
    )
    logger.success(f"ccClub&leetcode_summary (ccClub側) 已更新：{summary_partial['snapshot_date']}")
    return None
