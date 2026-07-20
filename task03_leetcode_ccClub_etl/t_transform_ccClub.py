"""task03 Transform（ccClub）：把 Extract 抓來的 ccClub raw problem list 清洗成 MongoDB document。

1. 函式 build_ccclub_problem_documents 從已解題清單擷取題號與題型特徵，
   組成符合 solved_problems_on_ccClub schema 的 document。
2. 函式 build_ccclub_summary_partial 接收上一步的題型特徵文檔，統計出 ccClub 刷題進度的彙整文檔。
"""

from collections import defaultdict
from datetime import datetime, timezone

from loguru import logger


def build_ccclub_problem_documents(raw_solved_problems: list[dict]) -> list[dict]:
    """把 raw problem list 對應成 solved_problems_on_ccClub 的 document。

    每筆 document 的 schema 為 problem_id、problem_type、score、topic 與 difficulty。

    Args:
        raw_solved_problems: Extract 抓來的 ccClub raw problem list。

    Returns:
        符合 solved_problems_on_ccClub schema 的 document 清單。
    """
    logger.info("Building documents listing the features of problems on ccClub.")
    docs = []
    for p in raw_solved_problems:
        doc = {
            "problem_id": p["problem_id"],
            "problem_type": p["problem_type"],
            "score": p.get("score", 0),
            "topic": p.get("topic", ["Unknown"]),
            "difficulty": p.get("difficulty", "Unknown"),
        }
        docs.append(doc)

    logger.info(f"Built documents {len(docs)} listing features of ccClub problems.")
    return docs


def build_ccclub_summary_partial(problem_docs: list[dict]) -> dict:
    """統計 ccClub 題目文檔，產出 ccClub&leetcode_summary 中 ccClub 側的欄位。

    LeetCode 側的欄位由 task03 另一支腳本補入，這裡只產 ccClub 側，計算三項統計：
    totalSolvedProblemsOnCCclub 為總題數、problemDifficultyOnCCclub 為各難度題數佔比、
    topicsPercentOnCCclub 為各 topic 佔比。

    Args:
        problem_docs: build_ccclub_problem_documents 產出的題目文檔清單。

    Returns:
        含 snapshot_date 與上述三項統計欄位的 ccClub 側摘要 dict。
    """
    logger.info("Building partial summary documents for ccClub problems...")
    total_problems = len(problem_docs)

    # 難度統計：計算出現次數後再轉百分比
    difficulty_count = defaultdict(int)
    for doc in problem_docs:
        difficulty_count[doc["difficulty"]] += 1

    problem_difficulty = []
    for diff, cnt in sorted(difficulty_count.items()):
        problem_difficulty.append(
            {
                "difficulty": diff,
                "percentage": round(cnt / total_problems * 100, 2) if total_problems > 0 else 0.0,
            }
        )

    # topic 統計：計算出現次數後再轉百分比
    topic_count = defaultdict(int)
    for doc in problem_docs:
        for topic in doc["topic"]:  # doc["topic"]: ["string", "math", ...]
            topic_count[topic] += 1

    total_topic_cnts = sum(topic_count.values())
    topic_percentage = {}
    sorted_topic_count = sorted(topic_count.items(), key=lambda tup: tup[1], reverse=True)
    for topic, cnt in sorted_topic_count:
        topic_percentage[topic] = round(cnt / total_topic_cnts * 100, 2) if total_topic_cnts > 0 else 0.0

    partial_summary_docs_ccClub = {
        "snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "totalSolvedProblemsOnCCclub": total_problems,
        "problemDifficultyOnCCclub": problem_difficulty,
        "topicsPercentOnCCclub": topic_percentage,
    }
    logger.success(f"Built documents for partial summarizing {len(partial_summary_docs_ccClub)} problems on ccClub.")
    return partial_summary_docs_ccClub
