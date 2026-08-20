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
    """把每題 AC 的原始題目資料組裝成 solved_problems_on_leetcode 的 document。

    逐題取出題號、題名與難度，並把題型標籤攤平成只有名稱的清單。

    Note:
        - 標籤只留名稱，捨棄 LeetCode 一併回傳的 id 與 slug，因為下游只用名稱做統計與顯示。

    Args:
        raw_solved: fetch_solved_problems_features 回傳的已 AC 題目原始清單。

    Returns:
        可寫入 solved_problems_on_leetcode 的 document 清單，每筆含 frontendQuestionId、
        title、topic 與 difficulty；傳入空清單時為空清單。

    Raises:
        KeyError: 某題缺少 frontendQuestionId、title 或 difficulty 任一欄位時拋出。
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
    """統計題目文檔與解題數，產出 ccClub&leetcode_summary 裡屬於 LeetCode 的那幾個欄位。

    1. 先確認題目文檔與解題數統計互相吻合，不吻合就不產出摘要。
    2. 累計各題型標籤出現的次數，依次數由多到少換算成百分比。
    3. 連同當日日期與總題數組成一份摘要。

    Note:
        - 題目文檔為空但統計顯示有解題，代表 Extract 抓到的兩份資料互相矛盾，
          多半是 cookie 過期讓題目清單全被濾掉、但解題數統計仍正常；
          此時回空字典，讓 Load 層跳過寫入，避免用錯誤的 0 覆蓋掉前一天正確的摘要。
        - 百分比的分母是所有標籤出現次數的總和而不是題數，一題掛多個標籤時會各計一次，
          因此各標籤百分比加總為 100，但不能解讀成「解過的題目有幾成屬於某標籤」。
        - ccClub 的欄位由 build_ccclub_summary_partial 另外產出，兩者寫進同一份文件、互不覆蓋。

    Args:
        feature_docs: build_problem_feat_documents 產出的題型特徵文檔清單。
        solved_problem_stats: fetch_solved_problem_stats 抓到的各難度解題數統計。

    Returns:
        含 snapshot_date、totalSolvedProblemsOnLeetcode、problemDifficultyOnLeetcode 與
        topicsPercentOnLeetcode 四個鍵的摘要字典；兩份資料互相矛盾時為空字典。

    Raises:
        IndexError: feature_docs 與 solved_problem_stats 同時為空清單時拋出。
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

    # snapshot_date 存 datetime 物件、但只表示到日（時分秒毫秒歸零），供以日為粒度的 upsert 與排序。
    snapshot_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    partial_summary_docs_leetcode = {
        "snapshot_date": snapshot_date,
        "totalSolvedProblemsOnLeetcode": len(feature_docs),
        "problemDifficultyOnLeetcode": solved_problem_stats,
        "topicsPercentOnLeetcode": topic_percentage,
    }

    logger.success(
        f"Built documents for partial summarizing {len(partial_summary_docs_leetcode)} problems on leetcode."
    )
    return partial_summary_docs_leetcode
