"""task03 Transform（ccClub）：把 Extract 抓來的 ccClub raw problem list 清洗成 MongoDB document。

1. 函式 build_ccclub_problem_documents 從已解題清單擷取題號與題型特徵，
   組成符合 solved_problems_on_ccClub schema 的 document。
2. 函式 build_ccclub_summary_partial 接收上一步的題型特徵文檔，統計出 ccClub 刷題進度的彙整文檔。
"""

from collections import defaultdict
from datetime import datetime, timezone

from loguru import logger


def build_ccclub_problem_documents(raw_solved_problems: list[dict]) -> list[dict]:
    """把已解題清單對應成 solved_problems_on_ccClub 的 document。

    逐題取出題號、題型、分數、標籤與難度五個欄位。

    Note:
        - 分數、標籤與難度缺值時分別填 0 與 Unknown，讓下游統計不必再處理缺值。
        - 題號與題型缺值則直接拋錯，因為這兩者缺了就無法辨識是哪一題。

    Args:
        raw_solved_problems: fetch_all_solved_problems 回傳的已解題清單。

    Returns:
        可寫入 solved_problems_on_ccClub 的 document 清單，每筆含 problem_id、problem_type、
        score、topic 與 difficulty；傳入空清單時為空清單。

    Raises:
        KeyError: 某題缺少 problem_id 或 problem_type 時拋出。
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
    """統計題目文檔，產出 ccClub&leetcode_summary 裡屬於 ccClub 的那幾個欄位。

    1. 累計各難度的題數，依難度名稱排序後換算成百分比。
    2. 累計各標籤出現的次數，依次數由多到少換算成百分比。
    3. 連同當日日期與總題數組成一份摘要。

    Note:
        - 難度百分比的分母是題數，各難度加總為 100；標籤百分比的分母則是所有標籤出現次數的總和，
          一題掛多個標籤時會各計一次，因此不能解讀成「解過的題目有幾成屬於某標籤」。
        - 題數為 0 時所有百分比都是 0，不會除以零。
        - LeetCode 的欄位由 build_leetcode_summary_partial 另外產出，兩者寫進同一份文件、互不覆蓋。
        - 與 LeetCode 那支不同，這裡沒有上游不一致的檢查，
          因此帳號真的一題未解與抓取異常都會產生總題數為 0 的摘要。

    Args:
        problem_docs: build_ccclub_problem_documents 產出的題目文檔清單。

    Returns:
        含 snapshot_date、totalSolvedProblemsOnCCclub、problemDifficultyOnCCclub 與
        topicsPercentOnCCclub 四個鍵的摘要字典。
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

    # snapshot_date 存 datetime 物件、但只表示到日（時分秒毫秒歸零），供以日為粒度的 upsert 與排序。
    snapshot_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    partial_summary_docs_ccClub = {
        "snapshot_date": snapshot_date,
        "totalSolvedProblemsOnCCclub": total_problems,
        "problemDifficultyOnCCclub": problem_difficulty,
        "topicsPercentOnCCclub": topic_percentage,
    }
    logger.success(f"Built documents for partial summarizing {len(partial_summary_docs_ccClub)} problems on ccClub.")
    return partial_summary_docs_ccClub
