"""task01_v2 Gold 層入口：對 note metadata 兩表現況盤出當日快照並寫入 notes_summary。

1. 對 obsidian_note_metadata 與 onenote_note_metadata 各跑一次 build_summary
2. 合併後 upsert_summary 以 snapshot_date 為唯一鍵 (Upsert key) 寫入 notes_summary（過渡期同時雙寫舊表）。

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
    """task01_v2 的 Gold 層，對兩份筆記 metadata 的現況產出當日合併快照。

    obsidian_note_metadata 與 onenote_note_metadata 各跑一次統計，合併後以當日日期為唯一鍵寫入，
    因此同一天重跑會覆蓋成最新值。

    Args:
        db: pymongo Database 物件，由頂層 main 傳入。

    Returns:
        None: 快照寫進 MongoDB 的 notes_summary，過渡期間同時寫進舊表 obsidian_summary，不回傳值。
    """
    upsert_summary(db, [build_summary(db, "obsidian_note_metadata"), build_summary(db, "onenote_note_metadata")])
    logger.success("=== Task01 v2 Gold 完成 | notes_summary 當日快照已更新 ===")
