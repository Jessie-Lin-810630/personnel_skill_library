"""task03 Transform（LeetCode）：把 Extract 抓來的已解題清單與統計結果清洗成 MongoDB document。

輸入的已解題清單與統計結果都已由 Extract 端 decode 成 Python dict。

1. 函式 build_problem_feat_documents 從已解題清單擷取題號與題型特徵，
   組成符合 solved_problems_on_leetcode schema 的 document。
2. 函式 build_leetcode_summary_partial 接收上一步的題型特徵文檔與 Extract 抓到的統計結果，
   產出 LeetCode 刷題進度的彙整文檔。
"""

from collections import defaultdict
from datetime import datetime, timezone

from loguru import logger


def build_problem_feat_documents(raw_solved: list[dict]) -> list[dict]:
    """把每題 AC 的 raw question 組裝成 solved_problems_on_leetcode 的 document。

    Args:
        raw_solved: 已 AC 題目的 raw question 清單。

    Returns:
        符合 solved_problems_on_leetcode schema 的 document 清單。
    """
    logger.info("Building documents listing the features of problems on leetcode...")
    feature_docs = []
    for q in raw_solved:
        doc = {
            "frontendQuestionId": q["frontendQuestionId"],
            "title": q["title"],
            "topic": [tag["name"] for tag in q.get("topicTags", [])],
            "difficulty": q["difficulty"],
        }
        feature_docs.append(doc)

    logger.success(f"Built {len(feature_docs)} documents listing the features of problems.")
    return feature_docs


def build_leetcode_summary_partial(
    feature_docs: list[dict],
    solved_problem_stats: list[dict],
) -> dict:
    """統計 LeetCode 題目文檔與解題統計，產出 ccClub&leetcode_summary 中 LeetCode 側的欄位。

    ccClub 側的欄位由 task03 另一支腳本補入，這裡只產 LeetCode 側，以 $set partial update
    寫入不覆蓋 ccClub 欄位；feature_docs 為空但統計顯示有解題時視為上游不一致並回傳空 dict。

    Args:
        feature_docs: build_problem_feat_documents 產出的題型特徵文檔清單。
        solved_problem_stats: Extract 抓到的各難度 AC submission 統計。

    Returns:
        含 snapshot_date、totalSolvedProblemsOnLeetcode、problemDifficultyOnLeetcode 與
        topicsPercentOnLeetcode 的 LeetCode 側摘要 dict；上游不一致時為空 dict。
    """
    logger.info("Building partial summary documents for leetcode...")

    if len(feature_docs) == 0 and solved_problem_stats[0].get("count", 0) != 0:
        logger.warning(
            "Feature_docs is empty list while there are some solved problems. "
            "Information is not consistent. Please check the upstream task result."
        )
        return {}

    # 統計 topic 出現次數後轉百分比
    topic_count = defaultdict(int)
    for doc in feature_docs:
        for topic in doc["topic"]:  # doc["topic"]: ["string", "database", ...]
            topic_count[topic] += 1

    total_topic_cnts = sum(topic_count.values())
    topic_percentage = {}
    sorted_topic_count = sorted(topic_count.items(), key=lambda tup: tup[1], reverse=True)
    for topic, cnt in sorted_topic_count:
        topic_percentage[topic] = round(cnt / total_topic_cnts * 100, 2) if total_topic_cnts > 0 else 0.0

    partial_summary_docs_leetcode = {
        "snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "totalSolvedProblemsOnLeetcode": len(feature_docs),
        "problemDifficultyOnLeetcode": solved_problem_stats,
        "topicsPercentOnLeetcode": topic_percentage,
    }

    logger.success(
        f"Built documents for partial summarizing {len(partial_summary_docs_leetcode)} problems on leetcode."
    )
    return partial_summary_docs_leetcode
