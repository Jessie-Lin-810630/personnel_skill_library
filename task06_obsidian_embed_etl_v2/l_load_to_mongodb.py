"""把向量本體載入目的地 note_vectors_multimodal，並消費軟刪除訊號 purge 對應向量。

1. 函式 load_vectors_incremental_v2 對每份筆記先刪後插 note_vectors_multimodal，
   再以 archived_md_md5_hash 守衛的 CAS 把 obsidian_note_metadata.embedded_status 翻成 true。
2. 函式 purge_deleted_vectors 消費軟刪除訊號，清掉 status=deleted 且已向量化筆記的向量本體，
   再把 embedded_status 翻回 false。

Required .env keys:
    MONGO_ALTAS_URI   MongoDB Atlas connection string.
    MONGO_DB_NAME     Target database name (default to skill_dashboard).
"""

from datetime import datetime, timezone

from loguru import logger
from pymongo import MongoClient
from pymongo.database import Database

NOTE_METADATA = "obsidian_note_metadata"
VECTORS_V2 = "note_vectors_multimodal"


def get_db(mongo_uri: str, db_name: str) -> Database:
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
    embedded_by_raw_md_path: dict[str, dict],
) -> None:
    """把本次成功處理的每份筆記寫進 note_vectors_multimodal，並以帶 md5 守衛的 CAS 翻 embedded_status。

    1. 依 md_path 把向量文件分組，該欄位的值就是歸檔後的 .md 路徑。
    2. 對每份筆記先刪掉舊向量再寫入新的。
    3. 以 CAS 更新 embedded_status，條件是該筆記目前仍為 false、且 archived_md_md5_hash
       等於本次向量化所依據的版本；命中才翻成 true，並以同一個時戳蓋上 embedded_at 與 updated_at。

    Note:
        先刪後插是為了讓重新切塊後 chunk 數變少時不殘留孤兒向量；全新的筆記沒有舊向量，那步等於空跑。
        CAS 若沒命中，代表向量化期間 task01 又重新歸檔改了 md5，此時不翻狀態、留待下一輪重做，
        以免把舊版內容產生的向量標記成最新版本。這種情況只記 warning，不視為失敗。
        向量文件以 md_path 分組，但 CAS 仍以 raw_md_path 定位筆記，兩者用途不同不可混用。

    Args:
        db: pymongo Database 物件。
        vector_docs: t_chunk_and_embed_v2 產出、待寫入 note_vectors_multimodal 的 chunk 向量清單，
            每筆都帶有 md_path。
        embedded_by_raw_md_path: 本次成功處理的筆記對照表，鍵為 raw_md_path，
            值含 md_path 供先刪後插定位向量，以及 archived_md5 作為 CAS 的守衛值。

    Returns:
        None: 向量寫進 MongoDB 的 note_vectors_multimodal，狀態欄位寫回 obsidian_note_metadata，
        各項筆數只記進 log，不回傳值。
    """
    vectors = db[VECTORS_V2]
    notes = db[NOTE_METADATA]

    # 依 md_path 分組（向量表的 data lineage 依據）
    chunks_by_md_path: dict[str, list[dict]] = {}
    for doc in vector_docs:
        chunks_by_md_path.setdefault(doc["md_path"], []).append(doc)

    n_files = n_chunks = n_flipped = n_cas_miss = 0
    for raw_md_path, info in embedded_by_raw_md_path.items():
        md_path = info["md_path"]
        archived_md5 = info["archived_md5"]
        chunks_of_file = chunks_by_md_path.get(md_path, [])
        vectors.delete_many({"md_path": md_path})  # 先刪舊（以 md_path 過濾）
        if chunks_of_file:
            vectors.insert_many(chunks_of_file)
            n_chunks += len(chunks_of_file)
        n_files += 1

        # CAS 仍以 metadata 唯一鍵 raw_md_path 定位；同一時戳一併蓋 embedded_at 與 updated_at，避免時序矛盾
        now = datetime.now(timezone.utc)
        cas = notes.update_one(
            {"raw_md_path": raw_md_path, "embedded_status": False, "archived_md_md5_hash": archived_md5},
            {"$set": {"embedded_status": True, "embedded_at": now, "updated_at": now}},
        )
        if cas.matched_count:
            n_flipped += 1
        else:
            n_cas_miss += 1
            logger.warning(f"CAS 未命中（embedding 期間 archived_md_md5_hash 已變或已翻），留待下輪重做：{raw_md_path}")

    logger.success(
        f"note_vectors_multimodal 增量寫入完成 | 檔案: {n_files} | 新插入 chunks: {n_chunks} | "
        f"翻 embedded: {n_flipped} | CAS 未命中: {n_cas_miss}"
    )


def purge_deleted_vectors(db: Database) -> int:
    """清除向量庫中那些來源檔案已在 GCS 上被軟刪除的向量。

    挑出 obsidian_note_metadata 裡 status 為 deleted 且 embedded_status 為 true 的筆記，
    依其 archived_md_path 刪掉向量庫中對應的所有 chunk，再把 embedded_status 翻回 false。

    Note:
        翻回 false 之後，這些筆記既不會再被挑出來重做向量化，檢索結果也不會再撈到已軟刪除的內容。
        這支函式只動向量文件與 embedded_status 欄位，不會刪改筆記 metadata 本身，也不會動 GCS 上的物件，
        因此筆記若日後在 GCS 上復原，task01 重新歸檔後仍可正常重做向量化。

    Args:
        db: pymongo Database 物件。

    Returns:
        本次清除向量的筆記數；向量刪除與狀態更新都寫進 MongoDB。
    """
    notes = db[NOTE_METADATA]
    vectors = db[VECTORS_V2]

    n_purged = 0
    for doc in notes.find({"status": "deleted", "embedded_status": True}, {"raw_md_path": 1, "archived_md_path": 1}):
        raw_md_path = doc["raw_md_path"]
        # 向量表以 md_path（＝archived_md_path 值）作為 data lineage 依據，故以它清除該筆記的向量
        vectors.delete_many({"md_path": doc.get("archived_md_path")})
        notes.update_one(
            {
                "raw_md_path": raw_md_path,  # metadata 唯一鍵；是從 raw-notes/ 被刪掉的筆記
                "status": "deleted",
                "embedded_status": True,
            },
            {"$set": {"embedded_status": False, "updated_at": datetime.now(timezone.utc)}},
        )
        n_purged += 1

    logger.success(f"note_vectors_multimodal purge 完成 | 清除軟刪除筆記向量: {n_purged}")
    return n_purged
