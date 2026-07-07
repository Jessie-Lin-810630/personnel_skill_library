"""負責把資料本體載入目的地：archived-notes 歸檔（GCS）與 obsidian_note_metadata/notes_summary（MongoDB）。

archive_note 把清洗後 .md 與圖片 copy 到 archived-notes → upsert_note 以 raw_md_path 為鍵冪等寫入 →
soft_delete_missing 對消失的 raw 標 deleted → build_and_upsert_summary 對現況做每日快照。

CDC 的既有 md5 讀取（get_existing_md5_map）屬 ingestion 輔助、不寫入，歸 e_scan_obsidian。

Required .env keys:
    MONGO_ALTAS_URI   MongoDB Atlas connection string.
    MONGO_DB_NAME     Target database name (skill_dashboard).
"""

from collections import defaultdict
from datetime import datetime, timezone

from google.cloud.storage import Bucket
from loguru import logger
from pymongo import MongoClient
from pymongo.database import Database

from .e_scan_obsidian import ARCHIVED_PREFIX, NOTE_METADATA, RAW_PREFIX

# 快照存在以下 collection
NOTES_SUMMARY = "notes_summary"


def get_db(mongo_uri: str, db_name: str):
    """建立 MongoClient 並回傳指定 database。"""
    client = MongoClient(mongo_uri)
    return client[db_name]


def _archived_name(raw_blob_name: str) -> str:
    """把 raw-notes/ 前綴換成 archived-notes/，其餘後段路徑不變。"""
    return raw_blob_name.replace(RAW_PREFIX, ARCHIVED_PREFIX, 1)


def _copy_blob(bucket: Bucket, src_name: str, dest_name: str) -> str:
    """在同一 bucket 內 copy_blob（覆蓋語意），回傳 archived 端 md5_hash。"""
    src_blob = bucket.blob(src_name)
    new_blob = bucket.copy_blob(src_blob, bucket, dest_name)
    if new_blob.md5_hash is None:
        new_blob.reload()
    return new_blob.md5_hash


def blob_name_from_uri(uri: str, bucket_name: str) -> str:
    """從 gs://bucket/xxx 取回 blob.name（xxx），供 copy_blob 使用（f-string 拼 URI 的反向）。"""
    prefix = f"gs://{bucket_name}/"
    return uri[len(prefix) :] if uri.startswith(prefix) else uri


def archive_note(note_doc: dict, bucket: Bucket, bucket_name: str = "personal-vaults") -> dict:
    """把清洗後 .md 與其引用圖片 copy 到 archived-notes/，回填 archived_* 欄位（冪等覆蓋）。

    note_doc 需含 raw_md_path 與 attached_images（raw 部分）；回傳補上 archived 欄位的同一 dict。
    任一 _copy_blob 例外時，把訊息寫入 note_doc["error_msg"] 後往外 re-raise（由呼叫端決定略過/落地）。
    """
    now = datetime.now(timezone.utc)
    try:
        # archive .md 檔到 archived-notes/ 下
        raw_md_name = blob_name_from_uri(note_doc["raw_md_path"], bucket_name)
        archived_md_name = _archived_name(raw_md_name)
        archived_md5 = _copy_blob(bucket, raw_md_name, archived_md_name)

        # archive images 到 archived-notes/ 下
        for img in note_doc.get("attached_images", []):
            raw_img_name = img["raw_image_path"]
            archived_img_name = _archived_name(raw_img_name)
            # 組裝最後需要的欄位
            img["archived_image_md5"] = _copy_blob(bucket, raw_img_name, archived_img_name)
            img["archived_image_path"] = f"gs://{bucket_name}/{archived_img_name}"

        note_doc["archived_md_path"] = f"gs://{bucket_name}/{archived_md_name}"
        note_doc["archived_md_md5_hash"] = archived_md5
        note_doc["archived_at"] = now
        note_doc["error_msg"] = ""
        return note_doc
    except Exception as e:
        note_doc["error_msg"] = f"歸檔失敗：{e}"
        raise


def upsert_note(db: Database, note_doc: dict) -> None:
    """以 raw_md_path 為唯一鍵冪等 upsert 到 obsidian_note_metadata。

    status=archived、embedded_status 初始 false（僅 insert 時設，避免覆蓋 task06 已翻的值）。
    """
    collection = db[NOTE_METADATA]
    now = datetime.now(timezone.utc)
    set_fields = {**note_doc, "status": "archived", "updated_at": now}
    collection.update_one(
        {"raw_md_path": note_doc["raw_md_path"]},
        {
            "$set": set_fields,
            "$setOnInsert": {"embedded_status": False, "created_at": now},
        },
        upsert=True,
    )


def mark_note_error(db: Database, raw_md_path: str, error_msg: str) -> None:
    """清洗/歸檔失敗時，以 raw_md_path 為鍵記一筆 status=error 與 error_msg。

    只寫 status/error_msg/updated_at，上一次歸檔成功而寫入的 archived_* 欄位不更動。
    """
    collection = db[NOTE_METADATA]
    now = datetime.now(timezone.utc)
    collection.update_one(
        {"raw_md_path": raw_md_path},
        {
            "$set": {"status": "error", "error_msg": error_msg, "updated_at": now},
            "$setOnInsert": {"embedded_status": False, "created_at": now},
        },
        upsert=True,
    )


def soft_delete_missing(db: Database, present_raw_paths: set[str]) -> int:
    """raw-notes live listing 已無、但 DB 尚存的筆記標 status=deleted。

    只動尚未 deleted 的文件，故重跑冪等；回傳本次翻成 deleted 的筆數。
    """
    collection = db[NOTE_METADATA]
    result = collection.update_many(
        {"raw_md_path": {"$nin": list(present_raw_paths)}, "status": {"$ne": "deleted"}},
        {"$set": {"status": "deleted", "updated_at": datetime.now(timezone.utc)}},
    )
    return result.modified_count


def build_and_upsert_summary(db: Database) -> dict:
    """對 obsidian_note_metadata 現況彙總，以 snapshot_date（截到日）為鍵 upsert notes_summary。"""
    collection = db[NOTE_METADATA]
    by_type: dict[str, int] = defaultdict(int)
    by_topic: dict[str, int] = defaultdict(int)
    total_notes = 0
    embedded_notes = 0

    for doc in collection.find(
        {"status": "archived"}, {"status": 1, "topic": 1, "embedded_status": 1, "archived_md_frontmatter.type": 1}
    ):
        if doc.get("status") != "archived":  # 只計成功歸檔者，排除 deleted / error
            continue
        total_notes += 1
        by_type[doc.get("archived_md_frontmatter", {}).get("type", "unknown")] += 1
        by_topic[doc.get("topic", "other")] += 1
        if doc.get("embedded_status"):
            embedded_notes += 1

    summary = {
        "by_type": dict(by_type),
        "by_topic": dict(by_topic),
        "total_notes": total_notes,
        "embedded_notes": embedded_notes,
    }
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    db[NOTES_SUMMARY].update_one({"snapshot_date": today}, {"$set": summary}, upsert=True)
    logger.success(f"notes_summary 快照已更新，快照日期：{today}")
    return summary
