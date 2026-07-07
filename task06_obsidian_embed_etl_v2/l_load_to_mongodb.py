"""把向量本體載入目的地 obsidian_vectors_v2，並消費軟刪除訊號 purge 對應向量。

load_vectors_incremental_v2 對每份筆記先刪後插 obsidian_vectors_v2、以 archived_md_md5_hash 守衛的 CAS
翻 obsidian_note_metadata.embedded_status=true → purge_deleted_vectors 清 status=deleted 且已向量化者的
向量後翻 embedded_status=false。

Required .env keys:
    MONGO_ALTAS_URI   MongoDB Atlas connection string.
    MONGO_DB_NAME     Target database name (skill_dashboard).
"""

from datetime import datetime, timezone

from loguru import logger
from pymongo import MongoClient
from pymongo.database import Database

NOTE_METADATA = "obsidian_note_metadata"
VECTORS_V2 = "obsidian_vectors_v2"


def get_db(mongo_uri: str, db_name: str):
    """以連線字串建立 MongoClient，回傳指定名稱的 database。

    Args:
        mongo_uri: MongoDB Atlas 連線字串。
        db_name: 目標 database 名稱。

    Returns:
        指定的 pymongo Database 物件。
    """
    client = MongoClient(mongo_uri)
    return client[db_name]


def load_vectors_incremental_v2(
    db: Database,
    vector_docs: list[dict],
    embedded_md5_by_raw_md_path: dict[str, str],
) -> None:
    """把本次成功處理的每份筆記寫進 obsidian_vectors_v2，並以帶 md5 守衛的 CAS 翻 embedded_status。

    1. 依 raw_md_path 把 vector_docs 分組。
    2. 對每份筆記先 delete_many 清掉舊向量、再 insert_many 寫新的；這樣重切後 chunk 數變少也不會殘留孤兒，
       全新的筆記因為沒有舊向量，delete 這步等於沒事。
    3. 只有這份筆記在 DB 仍是 embedded_status=false、且 archived_md_md5_hash 等於本次 embedding 的版本時，
       才把 embedded_status 翻成 true 並蓋上 embedded_at。若 embedding 期間 task01_v2 又重歸檔改了 md5，
       CAS 就不會命中，這份留待下輪重做，避免把舊版向量誤標成最新版本。

    Args:
        db: pymongo Database 物件。
        vector_docs: t_chunk_and_embed_v2 產出、待寫入 obsidian_vectors_v2 的 chunk 向量清單。
        embedded_md5_by_raw_md_path: 本次成功處理的 raw_md_path 對到其 archived_md_md5_hash，作 CAS 守衛值。
    """
    vectors = db[VECTORS_V2]
    notes = db[NOTE_METADATA]

    # 依 file_path 分組
    chunks_by_raw_md_path: dict[str, list[dict]] = {}
    for doc in vector_docs:
        chunks_by_raw_md_path.setdefault(doc["raw_md_path"], []).append(doc)

    n_files = n_chunks = n_flipped = n_cas_miss = 0
    for raw_md_path, archived_md5 in embedded_md5_by_raw_md_path.items():
        chunks_of_file = chunks_by_raw_md_path.get(raw_md_path, [])
        vectors.delete_many({"raw_md_path": raw_md_path})  # 先刪舊
        if chunks_of_file:
            vectors.insert_many(chunks_of_file)
            n_chunks += len(chunks_of_file)
        n_files += 1

        cas = notes.update_one(
            {"raw_md_path": raw_md_path, "embedded_status": False, "archived_md_md5_hash": archived_md5},
            {"$set": {"embedded_status": True, "embedded_at": datetime.now(timezone.utc)}},
        )
        if cas.matched_count:
            n_flipped += 1
        else:
            n_cas_miss += 1
            logger.warning(f"CAS 未命中（embedding 期間 archived_md_md5_hash 已變或已翻），留待下輪重做：{raw_md_path}")

    logger.success(
        f"obsidian_vectors_v2 增量寫入完成 | 檔案: {n_files} | 新插入 chunks: {n_chunks} | "
        f"翻 embedded: {n_flipped} | CAS 未命中: {n_cas_miss}"
    )


def purge_deleted_vectors(db: Database) -> int:
    """從向量資料庫中移除「事實來源 (GCS 上) 已經被軟刪除」的資料。

    針對 collection obsidian_note_metadata 中顯示 status=deleted
    且 embedded_status=true 的筆記所對應的、存放於 collection obsidian_vectors_v2 中向量，
    然後再翻過 embedded_status=false。

    此函式不會去改、刪 collection obsidian_note_metadata 文件與 GCS 上物件。
    翻 false 後不再被挑出來做向量化、也不會誤導檢索結果去撈已在 GCS 上被軟刪除的來源。
    函式回傳本次 purge 的筆記數。

    Args:
        db (Database): pymonogo database 物件。

    Returns:
        int: 本次向量化任務最後被 purge 的筆記數。
    """
    notes = db[NOTE_METADATA]
    vectors = db[VECTORS_V2]

    n_purged = 0
    for doc in notes.find({"status": "deleted", "embedded_status": True}, {"raw_md_path": 1}):
        raw_md_path = doc["raw_md_path"]
        vectors.delete_many({"raw_md_path": raw_md_path})
        notes.update_one(
            {
                "raw_md_path": raw_md_path,  # 是從 raw-notes/ 被刪掉的筆記
                "status": "deleted",
                "embedded_status": True,
            },
            {"$set": {"embedded_status": False}},
        )
        n_purged += 1

    logger.success(f"obsidian_vectors_v2 purge 完成 | 清除軟刪除筆記向量: {n_purged}")
    return n_purged
