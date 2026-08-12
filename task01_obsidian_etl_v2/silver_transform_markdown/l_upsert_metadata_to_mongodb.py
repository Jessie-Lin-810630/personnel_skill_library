"""把清洗歸檔後的 note document 冪等寫進 obsidian_note_metadata，並維護狀態機欄位 status。

1. 函式 upsert_note 以 raw_md_path 為唯一鍵 (Upsert key) 寫入並設 status=archived。
2. 函式 mark_note_error 對失敗者記 status=error。
3. 函式 soft_delete_missing 對已從 GCS 上消失的檔案，標上 status=deleted。

Required .env keys:
    MONGO_ALTAS_URI   MongoDB Atlas connection string.
    MONGO_DB_NAME     Target database name.
"""

from datetime import datetime, timezone

from loguru import logger
from pymongo.database import Database

from .e_get_changed_files import NOTE_METADATA


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
    """清洗或歸檔失敗時，以 raw_md_path 定位該筆記，記一筆 status=error 與 error_msg，供稽核。

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
    """把 DB 尚存，但這次 gs://<bucket>/raw-notes 下 live listing 已不見的筆記標成 status=deleted。

    1. 非常重要：present_raw_paths 為空時，乾脆先視為上游掃描異常，直接 return 0 並記 warning。
       因為拿空清單去比對會匹配到整個 collection，反而誤把全部筆記標成 deleted，非常危險，
       因此寧可先中止函式讓這輪漏刪、下輪再判斷是否要補刪。
    2. 正常情況下，挑出 raw_md_path 不在 present_raw_paths 裡面、且尚未 deleted 的筆記，一次標成 deleted。

    只動尚未 deleted 的文件，所以重跑冪等。

    Args:
        db: pymongo Database 物件。
        present_raw_paths: 這次掃描實際存在於 gs://<bucket>/raw-notes/ 的所有 raw_md_path 集合。

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
