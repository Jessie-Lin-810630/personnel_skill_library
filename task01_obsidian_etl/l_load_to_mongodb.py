from datetime import datetime, timezone

from loguru import logger
from pymongo import InsertOne, MongoClient, UpdateOne
from pymongo.collection import Collection
from pymongo.database import Database

"""
程式架構：
    負責所有 MongoDB 互動。
"""


def get_db(mongo_uri: str, db_name: str):
    client = MongoClient(mongo_uri)
    return client[db_name]


def _images_changed(db_images: list[dict], gcs_images: list[dict]) -> bool:
    """比較 DB 現況與 GCS 現況的 attached_images 是否不同 (圖片增減、或同名圖片內容換掉 → md5 變)。

    以 (image_path, image_md5_hash) 的集合比較，忽略順序。
    """

    def to_set(imgs):
        return {(i.get("image_path"), i.get("image_md5_hash")) for i in (imgs or [])}

    return to_set(db_images) != to_set(gcs_images)


def sync_notes(db: Database, notes_on_gcs: list[dict]) -> None:
    """obsidian_notes 的 CDC 狀態機 (增量 embedding 的真實來源)。

    以 GCS 掃描結果 (notes) 對比 DB 現況，逐筆決定動作：
      - 新增：DB 無此 file_path
            → 走 insert，created_at/updated_at=now，embedding_done=False
      - 修改：.md 或 圖片任一的 md5 變
            → 走 update，更新筆記本身 metadata、md5、attached_images、updated_at，
              並把 embedding_done 翻回 False (讓 task06 知道要重 embed)
      - 刪除狀況一： .md 從 GCS 被刪，但 DB 內尚存
            → delete_many 該 note doc
      - 刪除狀況二： 圖片從 GCS 被刪，但原屬 .md 沒被刪
            → 同修改處置。
      - 未變更：md5 與圖片皆相同
            → 跳過，完全不動該 doc (保住 created_at 與 embedding_done)
    """
    notes_collection: Collection = db["obsidian_notes"]
    now = datetime.now(timezone.utc)

    # 一次撈出 DB 現況：
    existing_notes_on_db = {
        db_note["file_path"]: db_note
        for db_note in notes_collection.find({}, {"file_path": 1, "file_md5_hash": 1, "attached_images": 1})
    }

    gcs_file_paths = set()  # 本次 GCS 上存在的所有 .md 的 file_path (用來反推哪些 DB doc 該刪)
    operations = []
    n_insert = n_update = n_skip = 0

    for gcs_note in notes_on_gcs:
        file_path = gcs_note["file_path"]
        gcs_file_paths.add(file_path)
        db_note = existing_notes_on_db.get(file_path)

        # 情境一：GCS 新增了 DB 沒有的筆記
        if db_note is None:
            # 補時間戳與 embedding_done=False
            insert_doc = {**gcs_note, "created_at": now, "updated_at": now, "embedding_done": False}
            operations.append(InsertOne(insert_doc))
            n_insert += 1
            continue

        # 情境二：.md或圖片任一的 md5 變。情境三：圖片從 GCS 被刪，但原屬 .md 沒任何變動
        # 比對 DB 現況 vs GCS 現況 (缺 file_md5_hash 的舊 doc 視為已變更，借此 backfill 並觸發一次重 embed)
        changed = db_note.get("file_md5_hash") != gcs_note.get("file_md5_hash") or _images_changed(
            db_note.get("attached_images"), gcs_note.get("attached_images")
        )
        if changed:
            update_fields = {**gcs_note, "updated_at": now, "embedding_done": False}
            operations.append(UpdateOne({"file_path": file_path}, {"$set": update_fields}))
            n_update += 1
        else:
            # 情境四: .md與圖片都沒變動，不做處置。
            n_skip += 1

    if operations:
        notes_collection.bulk_write(operations, ordered=False)

    # 情境五：刪除 DB 有、但 GCS 已不存在的 .md
    file_paths_to_delete = [db_file_path for db_file_path in existing_notes_on_db if db_file_path not in gcs_file_paths]
    n_delete = 0
    if file_paths_to_delete:
        n_delete = notes_collection.delete_many({"file_path": {"$in": file_paths_to_delete}}).deleted_count

    logger.success(
        f"obsidian_notes 同步完成 | 新增: {n_insert} | 更新: {n_update} | 未變更: {n_skip} | 刪除: {n_delete}"
    )


def upsert_note_summary(db: Database, summary: dict) -> None:
    """以 snapshot_date 為唯一鍵 (Upsert key)，每天只保留最新一筆快照"""
    collection = db["obsidian_summary"]  # A collection object
    collection.update_one({"snapshot_date": summary["snapshot_date"]}, {"$set": summary}, upsert=True)
    logger.success(f"obsidian_summary 快照已更新，快照日期：{summary['snapshot_date']}")
