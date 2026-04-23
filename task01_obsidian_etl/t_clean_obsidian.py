
from datetime import datetime, timezone
from collections import defaultdict

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
    return raw_notes


def build_summary_document(raw_notes: list[dict]) -> dict:
    """
    統計所有筆記，產出給 Streamlit 用的快照 document。
    寫入 obsidian_summary collection，以 snapshot_date 為識別鍵。
    """
    by_type = defaultdict(int)
    by_topic = defaultdict(int)

    for note in raw_notes:
        by_type[note["note_type"]] += 1
        by_topic[note["topic"]] += 1

    return {"snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "total_notes": len(raw_notes),
            "by_type": dict(by_type),  # MongoDB不支援defaultdict，需轉回dict
            "by_topic": dict(by_topic),
            }


if __name__ == "__main__":
    import e_scan_obsidian

    e_scan_obsidian.load_dotenv()
    obsidian_vault_path = e_scan_obsidian.os.getenv("OBSIDIAN_VAULT_PATH")
    raw_notes = e_scan_obsidian.scan_vault(obsidian_vault_path)
    # print(build_note_documents(raw_notes)[0])
    summary = build_summary_document(raw_notes)
    print(summary)
