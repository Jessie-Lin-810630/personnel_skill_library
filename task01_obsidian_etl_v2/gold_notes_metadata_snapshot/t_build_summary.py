"""對 obsidian_note_metadata 或 onenote_note_metadata 的現況，盤出當日快照所需的統計原料。

1. 只計 status=archived 與被退件（review_closed + rejected）這兩類筆記，其餘不納入統計原料。
2. 逐筆累加 tag、topic、type 的分佈與已向量化數。
3. 兩張表的 frontmatter 欄名不同（obsidian 用 archived_md_frontmatter、onenote 用 md_frontmatter），
   取值在此分岔。
4. 回傳含 snapshot_source 與 summary 的 dict，交 upsert_summary 合併寫入。

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

    1. 只統計 status 為 archived 的筆記，以及已定案退件的筆記。
    2. 逐筆累加標籤、topic 與 note_type 三種分佈，加上各自的總筆數與已向量化的筆數。

    Note:
        status 為 deleted 或 error 的筆記一律排除，因此快照反映的是可用內容的規模，不是曾經處理過的總量。
        兩份 metadata 存放 frontmatter 的欄位名稱不同，obsidian_note_metadata 用 archived_md_frontmatter、
        onenote_note_metadata 用 md_frontmatter，投影欄位因此依來源分岔，新增第三種來源時要一併補上。

    Args:
        db: pymongo Database 物件。
        snapshot_which_coll: 要對哪一份筆記 metadata 做快照。

    Returns:
        含 snapshot_source 與 summary 兩個鍵的字典。snapshot_source 記錄來源 collection 供合併時辨識；
        summary 底下有 embedded_notes，以及歸檔與退件兩組數字，每組各含筆數與三種分佈。
        傳入的 collection 名稱不在支援範圍時，記一筆 warning 後回 None，
        此時呼叫端若直接把它交給 upsert_summary 會取不到鍵而失敗。
    """
    collection = db[snapshot_which_coll]
    embedded_notes = 0

    # archived / rejected 兩桶，各自累計 count 與 tag／topic／type 分佈
    def _new_bucket() -> dict:
        """建立一組空的統計容器，歸檔與退件各用一組。

        Returns:
            含 count 與 by_tag、by_topic、by_type 三份分佈的字典，三份分佈的計數都從 0 起算。
        """
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
