from collections import defaultdict
from datetime import datetime, timezone

from loguru import logger

"""
程式架構：
    接收 e_scan_obsidian 的 raw list，產出：
    1. 清洗後的 notes list (準備逐筆 upsert)
    2. summary dict (統計快照)
"""


def build_note_documents(raw_notes: list[dict]) -> list[dict]:
    """準備寫入 obsidian_notes 的 documents。

    時間戳改由 load 層的狀態機決定：created_at 只在 insert 設、updated_at 只在內容變更時設，
    故這裡不再無腦塞 created_at (否則每次跑都會覆蓋 created_at、也會破壞 CDC 的 embedding_done 判斷)。
    目前為直接 passthrough，保留此函式作為未來清洗邏輯的掛載點。
    """
    logger.success(f"Built documents for {len(raw_notes)} notes.")
    return raw_notes


def build_summary_document(raw_notes: list[dict]) -> dict:
    """統計所有筆記，產出給 Streamlit 用的快照 document。

    寫入 obsidian_summary collection，以 snapshot_date 為識別鍵。
    """
    logger.info("Building summary documents for all notes...")
    by_type = defaultdict(int)
    by_topic = defaultdict(int)

    for note in raw_notes:
        by_type[note["note_type"]] += 1
        by_topic[note["topic"]] += 1

    summary_notes_docs = {
        "snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "total_notes": len(raw_notes),
        "by_type": dict(by_type),  # MongoDB不支援defaultdict，需轉回dict
        "by_topic": dict(by_topic),
    }
    logger.success(f"Built summary documents for {len(summary_notes_docs)} notes.")
    return summary_notes_docs
