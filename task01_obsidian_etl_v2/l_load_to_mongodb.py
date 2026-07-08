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

import frontmatter
from google.cloud.storage import Bucket
from loguru import logger
from pymongo import MongoClient
from pymongo.database import Database

from .e_scan_obsidian import ARCHIVED_PREFIX, NOTE_METADATA, RAW_PREFIX

# 快照存在以下 collection
NOTES_SUMMARY = "notes_summary"


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


def _archived_name(raw_blob_name: str) -> str:
    """把 blob 名稱開頭的 raw-notes/ 前綴換成 archived-notes/，後段路徑保持不變。

    Args:
        raw_blob_name: raw-notes/ 下的 blob 名稱。

    Returns:
        對應的 archived-notes/ blob 名稱。
    """
    return raw_blob_name.replace(RAW_PREFIX, ARCHIVED_PREFIX, 1)


def _copy_blob(bucket: Bucket, src_name: str, dest_name: str) -> str:
    """在同一個 bucket 內把來源 blob 複製到目的名稱，回傳 archived 端的 md5。

    採覆蓋語意，目的已存在就覆寫。複製後若回應沒帶 md5，就重新載入一次 metadata 再取。

    Args:
        bucket: 來源與目的所在的 GCS Bucket 物件。
        src_name: 來源 blob 名稱。
        dest_name: 目的 blob 名稱。

    Returns:
        目的 blob 的 md5 字串。
    """
    src_blob = bucket.blob(src_name)
    new_blob = bucket.copy_blob(src_blob, bucket, dest_name)
    if new_blob.md5_hash is None:
        new_blob.reload()
    return new_blob.md5_hash


def _delete_misposition_metadata(post: frontmatter.Post) -> None:
    """當 frontmatter 誤植到正文時的清掃，掃正文頂端的 key: value 區塊把欄位刪掉。

    1. 逐行往下掃直到碰到第一個真正的 Markdown 標題行就停；行首的 # 後面要接空白或再一個 #，
    這樣行內標籤 #python 才不會被誤判成標題而提早截斷。
    2. 將停下之前的所有行以空白字串 replace 掉。

    Args:
        post: frontmatter.loads() 解析後的物件。

    Returns:
        清掉 post.content 中錯位 frontmatter 後原位取代的 post 物件
    """
    lines_to_be_deleted = []
    for line in post.content.splitlines():
        # 真正的標題行 = '#' 後接空白或再一個 '#'；'#python' 這種行內標籤不算，不會誤停
        if line.startswith("#") and (len(line) == 1 or line[1] in " #"):
            break
        lines_to_be_deleted.append(line)

    text_to_be_deleted = "\n".join(lines_to_be_deleted)
    post.content = post.content.replace(text_to_be_deleted, "")

    return None


def _upload_clean_md(bucket: Bucket, src_name: str, dest_name: str, clean_frontmatter: dict) -> str:
    """下載 raw .md、把清洗後的 frontmatter 覆寫回內文，再上傳到 archived-notes/，回傳 archived 端 md5。

    不同於 _copy_blob 直接原樣複製，這裡把 Transform 階段算好的 clean_frontmatter 覆寫進 metadata，
    確保歸檔的 .md 不再帶著誤植或雜亂的原始 frontmatter。採覆蓋語意，目的已存在就覆寫；
    上傳後若回應沒帶 md5，就重新載入一次 metadata 再取。

    Args:
        bucket: 來源與目的所在的 GCS Bucket 物件。
        src_name: raw-notes/ 下的來源 .md blob 名稱。
        dest_name: archived-notes/ 下的目的 .md blob 名稱。
        clean_frontmatter: 要覆寫進 frontmatter 的清洗後欄位，即 note_doc 的 archived_md_frontmatter。

    Returns:
        目的 blob 的 md5 字串。
    """
    text = bucket.blob(src_name).download_as_text(encoding="utf-8")
    post = frontmatter.loads(text)
    post.metadata.update(clean_frontmatter)
    _delete_misposition_metadata(post)
    new_text = frontmatter.dumps(post)

    dest_blob = bucket.blob(dest_name)
    dest_blob.upload_from_string(new_text, content_type="text/markdown")
    if dest_blob.md5_hash is None:
        dest_blob.reload()
    return dest_blob.md5_hash


def blob_name_from_uri(uri: str, bucket_name: str) -> str:
    """從 gs://bucket/xxx 這樣的完整 URI 取回 blob 名稱 xxx，即拼 URI 的反向操作。

    有帶 gs://<bucket>/ 前綴時才去掉前綴，否則原樣回傳。

    Args:
        uri: GCS 的完整 gs:// URI，或已是 blob 名稱。
        bucket_name: 要剝除的 bucket 名稱。

    Returns:
        blob 名稱字串，供 copy_blob 等操作使用。
    """
    prefix = f"gs://{bucket_name}/"
    return uri[len(prefix) :] if uri.startswith(prefix) else uri


def archive_note(note_doc: dict, bucket: Bucket, bucket_name: str = "personal-vaults") -> dict:
    """把清洗後的 .md 與其引用圖片複製到 archived-notes/，並把 archived 端資訊回填進 note_doc。

    1. 依 raw_md_path 算出 archived 端的 .md 名稱，覆寫上清洗後的 frontmatter 再上傳並取回 archived md5。
    2. 逐一把 attached_images 的每張圖複製到對應的 archived _attachment/，回填該圖 archived 端的路徑與 md5。
    3. 補上 note_doc 的 archived_md_path、archived_md_md5_hash、archived_at，並把 error_msg 清空。

    整段採覆蓋語意，重跑同一版本結果一致。任一次複製失敗時，先把錯誤訊息寫進 note_doc["error_msg"]，
    再把例外往外拋，由呼叫端決定要略過還是落地記錄。

    Args:
        note_doc: 待歸檔的 note document，需含 raw_md_path 與 attached_images 的 raw 部分。
        bucket: 來源與目的所在的 GCS Bucket 物件。
        bucket_name: bucket 名稱，用來組 archived 端的 gs:// 路徑，預設 "personal-vaults"。

    Returns:
        補上 archived_* 欄位的同一個 note_doc。
    """
    now = datetime.now(timezone.utc)
    try:
        # archive .md 檔到 archived-notes/ 下，並帶上清洗後的 frontmatter
        raw_md_name = blob_name_from_uri(note_doc["raw_md_path"], bucket_name)
        archived_md_name = _archived_name(raw_md_name)
        archived_md5 = _upload_clean_md(bucket, raw_md_name, archived_md_name, note_doc["archived_md_frontmatter"])

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
    """以 raw_md_path 為唯一鍵，把 note document 冪等 upsert 進 obsidian_note_metadata。

    1. 一律把 status 設為 archived、更新 updated_at。
    2. embedded_status 與 created_at 只在第一次 insert 時設定，避免覆蓋 task06 之後翻過的向量化狀態。

    Args:
        db: pymongo Database 物件。
        note_doc: archive_note 回傳、已補上 archived_* 欄位的 note document。
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
    """清洗或歸檔失敗時，以 raw_md_path 為鍵記一筆 status=error 與 error_msg，供稽核。

    只覆寫 status、error_msg 與 updated_at，上一次成功歸檔留下的 archived_* 欄位不動，
    因此就算某版本歸檔失敗，仍保留上一版可用的向量化來源。這支函式可冪等重跑。

    Args:
        db: pymongo Database 物件。
        raw_md_path: 這份筆記的唯一鍵。
        error_msg: 要記錄的錯誤訊息。
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
    """把 DB 尚存、但這次 raw-notes live listing 已不見的筆記標成 status=deleted。

    1. present_raw_paths 為空時視為上游掃描異常，直接跳過並記 warning。
       因為拿空清單去比對會匹配到整個 collection，反而誤把全部筆記標成 deleted，寧可這輪漏刪、下輪補刪。
    2. 正常情況下，挑出 raw_md_path 不在 present_raw_paths、且尚未 deleted 的筆記，一次標成 deleted。

    只動尚未 deleted 的文件，所以重跑冪等。

    Args:
        db: pymongo Database 物件。
        present_raw_paths: 這次掃描實際存在於 raw-notes/ 的所有 raw_md_path 集合。

    Returns:
        本次新翻成 deleted 的筆記數。
    """
    if not present_raw_paths:
        logger.warning("present_raw_paths 為空，疑似上游掃描異常，跳過軟刪除以免誤刪全表")
        return 0

    collection = db[NOTE_METADATA]
    result = collection.update_many(
        {"raw_md_path": {"$nin": list(present_raw_paths)}, "status": {"$ne": "deleted"}},
        {"$set": {"status": "deleted", "updated_at": datetime.now(timezone.utc)}},
    )
    return result.modified_count


def build_and_upsert_summary(db: Database) -> dict:
    """對 obsidian_note_metadata 的現況做每日快照，以當天日期為鍵 upsert 進 notes_summary。

    1. 只統計 status 為 archived 的筆記，把 deleted 與 error 排除在進度之外。
    2. 逐筆累加各 note_type 與各 topic 的計數、總筆數，以及已向量化的筆數。
    3. 以截到日的 snapshot_date 為鍵 upsert，同一天重跑會覆蓋成最新值。

    Args:
        db: pymongo Database 物件。

    Returns:
        本次寫入的快照字典，含 by_type、by_topic、total_notes、embedded_notes。
    """
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
