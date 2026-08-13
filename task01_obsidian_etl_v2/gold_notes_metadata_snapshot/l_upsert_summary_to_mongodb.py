"""把 obsidian 與 onenote 兩份當日快照原料合併，以 snapshot_date 為唯一鍵 (Upsert key) 寫進 notes_summary。

1. 合併 build_summary 兩份回傳的 tag/topic/type 分佈與計數
2. 組出 final_summary
3. 以截到 (YYYY-mm-dd) 的 snapshot_date upsert 進 notes_summary。
過渡期同時雙寫舊表 obsidian_summary，待遷移穩定後刪舊表。

Required .env keys:
    MONGO_ALTAS_URI   MongoDB Atlas connection string.
    MONGO_DB_NAME     Target database name.
"""

from collections import defaultdict
from datetime import datetime, timezone

from loguru import logger
from pymongo.database import Database

# 快照存在以下 collection
NOTES_SUMMARY = "notes_summary"


def upsert_summary(db: Database, summary: list[dict[str, str | dict[str, int | defaultdict]]]) -> None:
    """將 obsidian_note_metadata 與 onenote_note_metadata 當日快照 doc 合併後存入快照資料表。

    1. 逐份快照把三種分佈與各項計數累加起來。
    2. 由歸檔與退件兩組數字合出不分狀態的 topic 與 note_type 分佈，供舊表使用。
    3. 以截到日的 snapshot_date 為唯一鍵 upsert，同一天重跑會覆蓋成最新值。

    Note:
        目前處於新舊表雙寫的過渡期，新表是 notes_summary，舊表是 obsidian_summary，兩張都會寫。
        待舊資料遷移到新表且不影響前端呈現後，再讓前端改讀新表，確認穩定一段時間才刪除舊表。
        因此這支函式現在寫兩次，遷移完成後應移除舊表那段。

    Args:
        db: pymongo Database 物件。
        summary: build_summary 回傳的快照原料清單，兩份筆記 metadata 各一筆。

    Returns:
        None: 快照寫進 MongoDB 的 notes_summary 與 obsidian_summary 兩張表，不回傳值。
    """
    all_summary = {
        "embedded_notes": 0,
        "archived_notes": 0,
        "rejected_notes": 0,
        "by_tag_in_archived_notes": defaultdict(int),
        "by_topic_in_archived_notes": defaultdict(int),
        "by_type_in_archived_notes": defaultdict(int),
        "by_tag_in_rejected_notes": defaultdict(int),
        "by_topic_in_rejected_notes": defaultdict(int),
        "by_type_in_rejected_notes": defaultdict(int),
    }

    for s in summary:
        if s["snapshot_source"] in ("onenote_note_metadata", "obsidian_note_metadata"):
            for k, v in s["summary"].items():
                if isinstance(v, defaultdict):
                    for k2, v2 in v.items():
                        all_summary[k][k2] += v2
                elif isinstance(v, int):
                    all_summary[k] += v

    by_topic = defaultdict(int)
    for d in (all_summary["by_topic_in_archived_notes"], all_summary["by_topic_in_rejected_notes"]):
        for k, v in d.items():
            by_topic[k] += v

    by_type = defaultdict(int)
    for d in (all_summary["by_type_in_archived_notes"], all_summary["by_type_in_rejected_notes"]):
        for k, v in d.items():
            by_type[k] += v

    final_summary = {
        "total_notes": all_summary["rejected_notes"] + all_summary["archived_notes"],
        "embedded_notes": all_summary["embedded_notes"],
        "archived_notes": all_summary["archived_notes"],
        "by_tag_in_archived_notes": dict(all_summary["by_tag_in_archived_notes"]),
        "by_topic_in_archived_notes": dict(all_summary["by_topic_in_archived_notes"]),
        "by_type_in_archived_notes": dict(all_summary["by_type_in_archived_notes"]),
        "rejected_notes": all_summary["rejected_notes"],
        "by_tag_in_rejected_notes": dict(all_summary["by_tag_in_rejected_notes"]),
        "by_topic_in_rejected_notes": dict(all_summary["by_topic_in_rejected_notes"]),
        "by_type_in_rejected_notes": dict(all_summary["by_type_in_rejected_notes"]),
    }

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    db[NOTES_SUMMARY].update_one({"snapshot_date": today}, {"$set": final_summary}, upsert=True)
    logger.success(f"notes_summary 快照已更新，快照日期：{today}")

    # 舊表雙寫，待舊表的舊資料遷移到 db[NOTES_SUMMARY] 且不影響前端呈現後，
    # 再讓前端去讀 db[NOTES_SUMMARY]，確定穩定能讀取一段時間後，再刪舊表。
    final_summary_old = {
        "by_topic": dict(by_topic),
        "by_type": dict(by_type),
        "total_notes": all_summary["rejected_notes"] + all_summary["archived_notes"],
    }
    db["obsidian_summary"].update_one({"snapshot_date": today}, {"$set": final_summary_old}, upsert=True)
    logger.success(f"舊表 obsidian_summary 快照也已更新，快照日期：{today}")
    return None
