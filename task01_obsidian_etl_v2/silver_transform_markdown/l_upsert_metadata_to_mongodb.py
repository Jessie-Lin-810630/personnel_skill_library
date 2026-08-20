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

    1. 一律把 status 設為 archived，並更新 updated_at。
    2. embedded_status 與 created_at 只在第一次寫入時設定。

    Note:
        embedded_status 之所以只在第一次寫入時設定，是因為 task06 完成向量化後會把它翻成 true，
        這裡若每次都覆寫，已向量化的筆記會被誤判成尚未處理而反覆重做。

    Args:
        db: pymongo Database 物件。
        note_doc: archive_note 回傳、已補上歸檔欄位的 note document。

    Returns:
        None: 結果寫進 MongoDB 的 obsidian_note_metadata，不回傳值。
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
    """清洗或歸檔失敗時，以 raw_md_path 定位該筆記並記下 status=error 與失敗原因，供稽核。

    只覆寫 status、error_msg 與 updated_at 三個欄位，
    archived_md_path、archived_md_md5_hash 等上次成功歸檔留下的值一律不動。同一筆可冪等重跑。

    Note:
        保留上次的歸檔欄位，是為了讓這個版本歸檔失敗時，task06 仍能沿用上一版可讀的內容做向量化，
        不會因為一次失敗就讓這份筆記從檢索結果中消失。

    Args:
        db: pymongo Database 物件。
        raw_md_path: 這份筆記的唯一鍵。
        error_msg: 要記錄的錯誤訊息。

    Returns:
        None: 結果寫進 MongoDB 的 obsidian_note_metadata，不回傳值。
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
    """把 MongoDB 尚存、但這次掃描 raw-notes/ 已不見的筆記標成 status=deleted。

    挑出 raw_md_path 不在本次掃描結果內、且尚未標為 deleted 的筆記，一次更新完畢。
    只動尚未 deleted 的文件，因此可冪等重跑。

    Note:
        present_raw_paths 為空時一律視為上游掃描異常，直接記一筆 warning 後回 0，不執行任何更新。
        因為拿空集合去比對會匹配到整個 collection，等於把所有筆記標成 deleted。
        寧可這輪漏刪、下輪再補，也不能冒這個風險。

    Args:
        db: pymongo Database 物件。
        present_raw_paths: 這次掃描實際存在於 raw-notes/ 的所有 raw_md_path 集合。

    Returns:
        本次新標成 deleted 的筆記數；掃描結果為空而跳過更新時回 0。
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
