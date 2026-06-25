from collections import defaultdict
from datetime import datetime, timezone

from loguru import logger

"""
程式架構：
Transform：接收 e_query_leetcode_graphql 所抓取的 用戶已解題清單 與 統計結果，
兩個來自e_query_leetcode_graphql.py的最終變數都是已經 decode 成 python dict 形式。
接下來清洗成符合 MongoDB document 的格式。

函式設計：
(1) build_problem_feat_documents(): 從用戶已解題清單擷取需要的題型特徵與題號，
    以其符合自定義的 MongoDB schema(document)。
(2) build_leetcode_summary_partial(): 接收上一支函式清洗出來的題型特徵文檔、
以及 e_query_leetcode_graphql 任務爬取到的統計結果，產出leetcode刷題進度彙整文檔。
"""


def build_problem_feat_documents(raw_solved: list[dict]) -> list[dict]:
    """將每題 AC 的 raw question 組裝成 文檔集'solved_problems_on_leetcode' 的 document。"""
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
    """產出 文檔集 'ccClub&leetcode_summary' 中關於 LeetCode 相關的欄位。

    另一個刷題系統 ccClub 的部分由 task03 的另一支腳本補入，這裡只產 leetcode 側。
    用 $set partial update 寫入，不覆蓋 ccClub 側的欄位。

    回傳：
    {
        "snapshot_date": "...",
        "totalProblemsOnLeetcode": 15,
        "problemsSolvedOnLeetcode": [...],
        "problemTopicsOnLeetcode": {"array": 13.4, ...}
    }
    """
    logger.info("Building partial summary documents for leetcode...")

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
