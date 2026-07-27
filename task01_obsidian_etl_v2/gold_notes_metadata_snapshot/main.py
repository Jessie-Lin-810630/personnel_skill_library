"""task01_v2 Gold 層入口：對 note metadata 兩表現況盤出當日快照並寫入 notes_summary。

1. 對 obsidian_note_metadata 與 onenote_note_metadata 各跑一次 build_summary
2. 合併後 upsert_summary 以 snapshot_date 為鍵寫入 notes_summary（過渡期同時雙寫舊表）。

db 由頂層 main 傳入。

Required .env keys:
    MONGO_ALTAS_URI   MongoDB Atlas connection string.
    MONGO_DB_NAME     Target database name.
"""

from loguru import logger
from pymongo.database import Database

from .l_upsert_summary_to_mongodb import upsert_summary
from .t_build_summary import build_summary


def gold_notes_metadata_snapshot(db: Database) -> None:
    """task01_v2 的 Gold 層，對 obsidian 與 onenote 兩表現況產出當日合併快照。

    Args:
        db: pymongo Database 物件，由頂層 main 傳入。
    """
    upsert_summary(db, [build_summary(db, "obsidian_note_metadata"), build_summary(db, "onenote_note_metadata")])
    logger.success("=== Task01 v2 Gold 完成 | notes_summary 當日快照已更新 ===")
