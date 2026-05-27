"""
Load layer for task06
==============================================
職責：
    1. get_db(): 建立與 MongoDB Altas 連線
    2. upsert_vectors(): 
     - 接收 t_chunk_embed.py - t_chunk_and_embed() 回傳的 list[dict]，
     - 以 file_path + chunk_index 組成唯一鍵做 upsert，分批 upsert 到 MongoDB Atlas 文檔集 obsidian_vectors。
"""

import sys
from loguru import logger
from pymongo import MongoClient, UpdateOne


logger.remove()
logger.add(sys.stderr,
           level="INFO",
           format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>")


def get_db(mongo_uri: str, db_name: str):
    client = MongoClient(mongo_uri)
    return client[db_name]


def upsert_vectors(db, vector_docs: list[dict], batch_size: int = 100) -> None:
    """
    以 file_path + chunk_index 組成唯一鍵做 upsert：
        - 已存在，代表同一份筆記的同一個 chunk已存在，此時更新
        - 不存在，則同一份筆記的同一個 chunk不存在，此時插入

    分批寫入，每批 batch_size 筆，避免單次 bulk_write 寫入過久或觸發 BSON 16MB 上限 (主要是擔心前者)。

    若未來一份筆記被重新切塊後 chunk 數量減少 (例如從 6 個縮為 4 個)，
    舊的 chunk_index 4、5 不會自動被刪除。
    目前資料量小，影響不大；若未來需要清理孤立 chunk，
    可在 upsert 前先 delete_many({"file_path": file_path})，再重新 insert。
    """
    collection = db["obsidian_vectors"]
    total = len(vector_docs)

    if total == 0:
        logger.warning("vector_docs 為空，跳過 upsert。")
        return

    total_upserted = 0
    total_modified = 0

    for batch_start in range(0, total, batch_size):
        batch = vector_docs[batch_start: batch_start + batch_size]

        operations = []
        for doc in batch:
            # 唯一鍵：同一份筆記的同一個 chunk
            filter_key = {"file_path": doc["file_path"],
                          "chunk_index": doc["chunk_index"],
                          }
            operation = UpdateOne(filter_key,
                                  {"$set": doc},
                                  upsert=True,
                                  )
            operations.append(operation)

        result = collection.bulk_write(operations)
        total_upserted += result.upserted_count
        total_modified += result.modified_count

        batch_end = min(batch_start + batch_size, total)
        logger.info(f"批次 {batch_start + 1}–{batch_end} / {total} 寫入完成 | "
                    f"新增: {result.upserted_count} | 更新: {result.modified_count}")

    logger.success(f"obsidian_vectors upsert 全部完成 | "
                   f"總新增: {total_upserted} | 總更新: {total_modified} | 總筆數: {total}")
