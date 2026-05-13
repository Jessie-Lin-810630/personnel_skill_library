
from datetime import datetime, timezone
from collections import defaultdict
from loguru import logger

"""
程式架構：
    接收 e_scan_obsidian 的 raw list，產出：
    1. 清洗後的 notes list (準備逐筆 upsert)
    2. summary dict (統計快照)
"""


def build_note_documents(raw_notes: list[dict]) -> list[dict]:
    """加上 created_at timestamp，準備寫入 obsidian_notes collection"""
    now = datetime.now(timezone.utc)  # 會變成UTC+0的時間
    for note in raw_notes:
        note["created_at"] = now
    logger.success(f"Built documents for {len(raw_notes)} notes.")
    return raw_notes


def build_summary_document(raw_notes: list[dict]) -> dict:
    """
    統計所有筆記，產出給 Streamlit 用的快照 document。
    寫入 obsidian_summary collection，以 snapshot_date 為識別鍵。
    """
    logger.info("Building summary documents for all notes...")
    by_type = defaultdict(int)
    by_topic = defaultdict(int)

    for note in raw_notes:
        by_type[note["note_type"]] += 1
        by_topic[note["topic"]] += 1

    summary_notes_docs = {"snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                          "total_notes": len(raw_notes),
                          "by_type": dict(by_type),  # MongoDB不支援defaultdict，需轉回dict
                          "by_topic": dict(by_topic),
                          }
    logger.success(f"Built summary documents for {len(summary_notes_docs)} notes.")
    return summary_notes_docs
