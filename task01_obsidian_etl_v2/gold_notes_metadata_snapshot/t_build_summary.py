"""對 obsidian_note_metadata 或 onenote_note_metadata 的現況，盤出當日快照所需的統計原料。

只計 status=archived 與被退件（review_closed + rejected）兩桶 → 逐筆累加 tag/topic/type 分佈與
已向量化數 → 兩表 frontmatter 欄名不同（obsidian 用 archived_md_frontmatter、onenote 用 md_frontmatter）
在此分岔 → 回傳含 snapshot_source 與 summary 的 dict，交 upsert_summary 合併寫入。

Required .env keys:
    MONGO_ALTAS_URI   MongoDB Atlas connection string.
    MONGO_DB_NAME     Target database name (skill_dashboard).
"""

from collections import defaultdict
from typing import Literal

from loguru import logger
from pymongo.database import Database


def build_summary(
    db: Database, snapshot_which_coll: Literal["obsidian_note_metadata", "onenote_note_metadata"]
) -> dict:
    """對 obsidian_note_metadata 或 onenote_note_metadata 的現況盤出當日快照的 docs。

    1. 只統計 status 為 archived 的筆記與被退件者，把 deleted 與 error 排除在進度之外。
    2. 逐筆累加各 note_type 與各 topic 的計數、總筆數，以及已向量化的筆數。

    Args:
        db: pymongo Database 物件。
        snapshot_which_coll: 針對哪個 collection 做快照。

    Returns:
        本次寫入的快照字典，含全域的 embedded_notes，以及 archived 桶（archived_notes、
        by_tag_in_archived_notes、by_topic_in_archived_notes、by_type_in_archived_notes）
        與 rejected 桶（rejected_notes、by_tag_in_rejected_notes、
        by_topic_in_rejected_notes、by_type_in_rejected_notes）。
    """
    collection = db[snapshot_which_coll]
    embedded_notes = 0

    # archived / rejected 兩桶，各自累計 count 與 tag／topic／type 分佈
    def _new_bucket() -> dict:
        return {"count": 0, "by_tag": defaultdict(int), "by_topic": defaultdict(int), "by_type": defaultdict(int)}

    archived = _new_bucket()
    rejected = _new_bucket()

    query = {"$or": [{"status": "archived"}, {"status": "review_closed", "review_result": "rejected"}]}
    if snapshot_which_coll == "obsidian_note_metadata":
        frontmatter_column_name = "archived_md_frontmatter"
    elif snapshot_which_coll == "onenote_note_metadata":
        frontmatter_column_name = "md_frontmatter"
    else:
        logger.warning("快照來源指定錯誤，跳過快照，請檢查 collection 名稱是否傳入正確。")
        return

    projection = {
        "status": 1,
        "review_result": 1,
        "topic": 1,
        "embedded_status": 1,
        f"{frontmatter_column_name}.type": 1,
        f"{frontmatter_column_name}.tags": 1,
    }

    for doc in collection.find(query, projection):
        status = doc.get("status")
        is_archived = status == "archived"
        is_rejected = status == "review_closed" and doc.get("review_result") == "rejected"
        if not (is_archived or is_rejected):  # 排除 deleted / error / 尚未定案的 review
            continue

        meta = doc.get(frontmatter_column_name, {})
        note_type = meta.get("type", "unknown")
        topic = doc.get("topic", "other")

        if doc.get("embedded_status"):
            embedded_notes += 1

        bucket = archived if is_archived else rejected
        bucket["count"] += 1
        bucket["by_type"][note_type] += 1
        bucket["by_topic"][topic] += 1
        for tag in meta.get("tags", []):
            bucket["by_tag"][tag] += 1

    summary = {
        "snapshot_source": snapshot_which_coll,
        "summary": {
            "embedded_notes": embedded_notes,
            "archived_notes": archived["count"],
            "by_tag_in_archived_notes": archived["by_tag"],
            "by_topic_in_archived_notes": archived["by_topic"],
            "by_type_in_archived_notes": archived["by_type"],
            "rejected_notes": rejected["count"],
            "by_tag_in_rejected_notes": rejected["by_tag"],
            "by_topic_in_rejected_notes": rejected["by_topic"],
            "by_type_in_rejected_notes": rejected["by_type"],
        },
    }
    return summary
