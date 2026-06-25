"""Load layer for task06 (增量 embedding 版).

==============================================
職責：
    1. get_db():                 建立與 MongoDB Altas 連線
    2. get_notes_state():        讀 obsidian_notes 的 {file_path: {file_md5_hash, embedding_done}}，供 task06 gate 判斷
    3. load_vectors_incremental(): 對本次成功處理的檔案「先刪後插」obsidian_vectors_multimodal，
                                  並以「帶 md5 守衛的 CAS」翻 obsidian_notes.embedding_done=True
"""

import sys
from datetime import datetime, timezone

from loguru import logger
from pymongo import MongoClient
from pymongo.database import Database

logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
)


def get_db(mongo_uri: str, db_name: str):
    """建立 MongoDB Atlas 連線並回傳指定的 database。

    Args:
        mongo_uri: MongoDB Atlas 連線字串。
        db_name: 目標 database 名稱。

    Returns:
        指定的 pymongo Database 物件。
    """
    client = MongoClient(mongo_uri)
    return client[db_name]


def get_notes_state(db: Database, notes_collection_name: str = "obsidian_notes") -> dict:
    """回傳 {file_path: {"file_md5_hash": str|None, "embedding_done": bool|None}} (DB 層的狀態)。

    供 task06 的 gate：只有 GCS blob 的 file_md5_hash == 這裡的 file_md5_hash 且 embedding_done 為 False 才 embed。

    Args:
        db: pymongo Database 物件。
        notes_collection_name: 筆記狀態 collection 名稱，預設 "obsidian_notes"。

    Returns:
        {file_path: {"file_md5_hash": str|None, "embedding_done": bool|None}}，DB 層的當前狀態。
    """
    notes_collection = db[notes_collection_name]
    state_by_file_path = {}
    for db_note in notes_collection.find({}, {"file_path": 1, "file_md5_hash": 1, "embedding_done": 1}):
        state_by_file_path[db_note["file_path"]] = {
            "file_md5_hash": db_note.get("file_md5_hash"),
            "embedding_done": db_note.get("embedding_done"),
        }
    return state_by_file_path


def load_vectors_incremental(
    db: Database,
    vector_docs: list[dict],
    processed_file_paths: list[str],
    embedded_md5_by_file_path: dict[str, str],
    vectors_collection_name: str = "obsidian_vectors_multimodal",
    notes_collection_name: str = "obsidian_notes",
) -> None:
    """對本次「成功處理」的每個檔案做增量寫入與 CAS 翻 done。

      1. 先刪後插 obsidian_vectors_multimodal：先 delete_many({file_path}) 再 insert_many，
         避免一份筆記重切後 chunk 數變少 (例 6→4) 殘留舊 chunk 孤兒；新檔 delete 為 no-op。
      2. Compare-And-Swap 策略：只有 obsidian_notes 的 file_md5_hash 仍等於本次 embed 的版本、
         且 embedding_done 仍為 False 才將其翻成 True，並蓋上 embedded_at (embedding 完成時間，UTC)。
         若 task01 中途改了 file_md5_hash，不翻成 True，留待下輪重新 embed，
         避免「 embedding_done 誤標成 True、但實際上 obsidian notes 裡面是描述新 file」。

    processed_file_paths 來自 t_chunk_and_embed：包含成功處理切塊 (空切塊也算成功) 的檔案；
    失敗的檔不在其中，故不會被翻 done，下輪會重試。
    embedded_md5_by_file_path：{file_path: 本次 embed 的那版 file_md5_hash}，作 CAS 守衛值。

    Args:
        db: pymongo Database 物件。
        vector_docs: t_chunk_and_embed 產出的 vector docs (待寫入 obsidian_vectors_multimodal)。
        processed_file_paths: 本次成功處理 (含切塊為空) 的 file_path 清單。
        embedded_md5_by_file_path: {file_path: 本次 embed 的那版 file_md5_hash}，作 CAS 守衛值。
        vectors_collection_name: 向量 collection 名稱，預設 "obsidian_vectors_multimodal"。
        notes_collection_name: 筆記狀態 collection 名稱，預設 "obsidian_notes"。
    """
    vectors_collection = db[vectors_collection_name]
    notes_collection = db[notes_collection_name]

    # 依 file_path 分組 (切塊為空的檔不會出現在 chunks_by_file_path，但仍在 processed_file_paths)
    chunks_by_file_path: dict[str, list[dict]] = {}
    for vector_doc in vector_docs:
        chunks_by_file_path.setdefault(vector_doc["file_path"], []).append(vector_doc)

    n_files = n_chunks = n_flipped = n_cas_miss = 0
    for file_path in processed_file_paths:
        chunks_of_file = chunks_by_file_path.get(file_path, [])
        vectors_collection.delete_many({"file_path": file_path})  # 先刪舊
        if chunks_of_file:
            vectors_collection.insert_many(chunks_of_file)
            n_chunks += len(chunks_of_file)
        n_files += 1

        # 帶 file_md5_hash 守衛的 compare-and-swap
        # 同時蓋上 embedded_at (本次 embedding 完成時間，UTC)；只有 CAS 命中才會寫，語意正確。
        # embedded_at 與 task01 的 updated_at (內容變更時間) 語意切開，互不覆蓋。
        cas_result = notes_collection.update_one(
            {
                "file_path": file_path,
                "file_md5_hash": embedded_md5_by_file_path.get(file_path),
                "embedding_done": False,
            },
            {"$set": {"embedding_done": True, "embedded_at": datetime.now(timezone.utc)}},
        )
        if cas_result.matched_count:
            n_flipped += 1
        else:
            n_cas_miss += 1
            logger.warning(
                f"embedding_done 但 CAS 未命中 (可能 embedding 過程中 GCS 檔案變更連帶修改了 file_md5_hash)，"
                f"留待下輪重做 embedding: {file_path}"
            )

    logger.success(
        f"obsidian_vectors_multimodal 增量寫入完成 | 檔案: {n_files} | 新插入 chunks: {n_chunks} | "
        f"翻 done: {n_flipped} | CAS 未命中: {n_cas_miss}"
    )
