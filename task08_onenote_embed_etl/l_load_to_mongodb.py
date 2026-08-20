"""把向量本體載入目的地 note_vectors_multimodal（與 task01/task06 共用），並以 CAS 翻 embedded_status。

load_vectors_incremental_onenote 對每份筆記先以 md_path 過濾刪掉舊 chunk、再插入本次新 chunk，並
以 md_md5_hash 守衛的 CAS 翻 onenote_note_metadata.embedded_status=true。
OneNote 無軟刪除（版本以 review_closed 退役），故不含 purge 端。

Required .env keys:
    MONGO_ALTAS_URI   MongoDB Atlas connection string.
    MONGO_DB_NAME     Target database name (skill_dashboard).
"""

from datetime import datetime, timezone

from loguru import logger
from pymongo import MongoClient
from pymongo.database import Database

NOTE_METADATA = "onenote_note_metadata"
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


def load_vectors_incremental_onenote(
    db: Database,
    vector_docs: list[dict],
    embedded_md5_by_md_path: dict[str, str],
) -> None:
    """把本次成功處理的每份 onenote 筆記寫進 note_vectors_multimodal，並以帶 md5 守衛的 CAS 翻 embedded_status。

    1. 依 md_path 把向量文件分組，該欄位的值就是歸檔後的 .md 路徑。
    2. 對每份筆記先刪掉舊向量再寫入新的。
    3. 以 CAS 更新 embedded_status，條件是該版本目前仍為 false、且 md_md5_hash
       等於本次向量化所依據的版本；命中才翻成 true，並以同一個時戳蓋上 embedded_at 與 updated_at。

    Note:
        - 先刪後插是為了讓重新切塊後 chunk 數變少時不殘留孤兒向量；全新的筆記沒有舊向量，那步等於空跑。
        - CAS 若沒命中，代表向量化期間 task07 又重新歸檔改了 md5，此時不翻狀態、留待下一輪重做，
          以免把舊版內容產生的向量標記成最新版本。這種情況只記 warning，不視為失敗。
        - CAS 以 archived_md_path 定位，該路徑本身就唯一對應一個版本，效果等同以 page_id 與 dt 定位。
        - embedded_at 與 updated_at 一起蓋，是因為 task08 直接以 pymongo 翻旗標、不經過 task07 的
          upsert_version_meta，若只蓋前者會出現 embedded_at 晚於 updated_at 的矛盾時序。

    Args:
        db: pymongo Database 物件。
        vector_docs: t_chunk_and_embed_onenote 產出、待寫入 note_vectors_multimodal 的 chunk 向量清單，
            每筆都帶有 md_path。
        embedded_md5_by_md_path: 本次成功處理的版本對照表，鍵為 archived_md_path，值為其 md_md5_hash，
            前者供先刪後插定位向量，後者作為 CAS 的守衛值。

    Returns:
        None: 向量寫進 MongoDB 的 note_vectors_multimodal，狀態欄位寫回 onenote_note_metadata，
        各項筆數只記進 log，不回傳值。
    """
    vectors = db[VECTORS_V2]
    notes = db[NOTE_METADATA]

    # 依 md_path 分組
    chunks_by_md_path: dict[str, list[dict]] = {}
    for doc in vector_docs:
        chunks_by_md_path.setdefault(doc["md_path"], []).append(doc)

    n_files = n_chunks = n_flipped = n_cas_miss = 0
    for md_path, md5 in embedded_md5_by_md_path.items():
        chunks_of_file = chunks_by_md_path.get(md_path, [])
        vectors.delete_many({"md_path": md_path})  # 先刪舊
        if chunks_of_file:
            vectors.insert_many(chunks_of_file)
            n_chunks += len(chunks_of_file)
        n_files += 1

        # embedded_at 與 updated_at 同一時戳一起蓋：task08 直接以 pymongo 翻旗標、未經 task07
        # 的 upsert_version_meta，故此處自行補 updated_at，避免 embedded_at 晚於 updated_at 的矛盾
        # （否則會被誤讀成「先偷翻 status 再做 embedding」）。
        now = datetime.now(timezone.utc)
        cas = notes.update_one(
            {"archived_md_path": md_path, "embedded_status": False, "md_md5_hash": md5},
            {"$set": {"embedded_status": True, "embedded_at": now, "updated_at": now}},
        )
        if cas.matched_count:
            n_flipped += 1
        else:
            n_cas_miss += 1
            logger.warning(f"CAS 未命中（embedding 期間 md_md5_hash 已變或已翻），留待下輪重做：{md_path}")

    logger.success(
        f"note_vectors_multimodal 增量寫入完成（onenote）| 檔案: {n_files} | 新插入 chunks: {n_chunks} | "
        f"翻 embedded: {n_flipped} | CAS 未命中: {n_cas_miss}"
    )
