from collections import defaultdict
from datetime import datetime, timezone

from loguru import logger

"""
程式架構：
Transform：把 e_crawler_ccClub 所抓取到的 ccClub raw problem list 清洗成 MongoDB document 格式。

函式設計：
(1) build_ccclub_problem_documents(): 從用戶已解題清單擷取需要的題型特徵與題號，
    以其符合自定義的 MongoDB schema(document)。
(2) build_ccclub_summary_partial(): 接收上一支函式清洗出來的題型特徵文檔，產出ccClub刷題進度彙整文檔。
"""


def build_ccclub_problem_documents(raw_solved_problems: list[dict]) -> list[dict]:
    """將 raw problem list 直接對應到文檔集 'solved_problems_on_ccClub' 的 schema。

    schema：problem_id, problem_type, score, topic, difficulty。
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
    """產出文檔集 'ccClub&leetcode_summary' 中 ccClub 相關的欄位。

    另一個刷題系統 leetcode 的部分由 task03 的另一支腳本補入，這裡只產 ccClub 側。

    計算內容：
    - totalSolvedProblemsOnCCclub : 總題數 (document 數量)
    - problemDifficultyOnCCclub   : 各難度題數佔比 (百分比)
    - topicsPercentOnCCclub       : 各 topic 佔比 (百分比)
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
