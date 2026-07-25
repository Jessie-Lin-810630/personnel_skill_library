"""task03 入口：依序執行 LeetCode 與 ccClub 兩條刷題 ETL。

1. 函式 run_task03_leetcode 執行 LeetCode GraphQL ETL，抓取已解題清單與統計，寫入 MongoDB。
2. 函式 run_task03_ccclub 執行 ccClub REST API ETL，登入後抓取已解題資料，寫入 MongoDB。
3. 兩條 pipeline 各自把 summary 以 partial update 寫進共用的 ccClub&leetcode_summary，互不覆蓋。

Usage:
    poetry run python -m task03_leetcode_ccClub_etl.main

Required .env keys:
    LEETCODE_USERNAME   LeetCode account name.
    LEETCODE_SESSION    LeetCode session cookie.
    CSRF_TOKEN          LeetCode CSRF token cookie.
    CCCLUB_USERNAME     ccClub Judge account name.
    CCCLUB_PASSWORD     ccClub Judge password.
    MONGO_ALTAS_URI     MongoDB Atlas connection string.
    MONGO_DB_NAME       Target database name.
"""

import os

from loguru import logger

from .e_crawler_ccClub import fetch_all_solved_problems, get_session_and_headers
from .e_query_leetcode_graphql import fetch_solved_problem_stats, fetch_solved_problems_features, get_headers
from .l_load_ccClub_doc_to_mongodb import upsert_ccclub_problems, upsert_ccclub_summary_partial
from .l_load_leetcode_doc_to_mongodb import get_db, upsert_leetcode_problems, upsert_leetcode_summary_partial
from .t_transform_ccClub import build_ccclub_problem_documents, build_ccclub_summary_partial
from .t_transform_leetcode import build_leetcode_summary_partial, build_problem_feat_documents


def run_task03_leetcode() -> None:
    """執行 LeetCode GraphQL ETL，抓取已解題清單與統計後寫入 MongoDB。

    1. 檢查 LeetCode 與 MongoDB 連線用的環境變數，缺任一就拋 EnvironmentError。
    2. Extract 以 GraphQL 抓取已解題題型特徵與解題統計。
    3. Transform 把兩者組成題目文檔與 LeetCode 側摘要。
    4. Load 以 upsert 寫入 solved_problems_on_leetcode 與 ccClub&leetcode_summary。
    """
    username = os.getenv("LEETCODE_USERNAME")
    session = os.getenv("LEETCODE_SESSION")
    csrf_token = os.getenv("CSRF_TOKEN")
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([username, session, csrf_token, mongo_uri, db_name]):
        logger.error(
            "請確認 secret manager 已設定 LEETCODE_USERNAME / LEETCODE_SESSION / "
            "CSRF_TOKEN / MONGO_ALTAS_URI / MONGO_DB_NAME"
        )
        raise EnvironmentError(
            "請確認 secret manager 已設定 LEETCODE_USERNAME / LEETCODE_SESSION / "
            "CSRF_TOKEN / MONGO_ALTAS_URI / MONGO_DB_NAME"
        )

    logger.info("=== Task 3-A: LeetCode GraphQL ETL 開始 ===")

    headers = get_headers(csrf_token, session, username)

    # 最外層統一接住內層拋出的例外，只在此處印一次完整 traceback 後再往上拋
    # （loguru 不吃 exc_info=True，需用 logger.opt(exception=True) 才會帶出 traceback）
    try:
        # ======== Extract ========
        # 抓已解題清單 + beats stats
        raw_solved_problem_feat = fetch_solved_problems_features(headers)
        raw_solved_problem_stats = fetch_solved_problem_stats(headers, username)

        # ======== Transform ========
        # 組裝 documents
        feature_docs = build_problem_feat_documents(raw_solved_problem_feat)
        summary_docs_leetcode = build_leetcode_summary_partial(feature_docs, raw_solved_problem_stats)

        # ======== Load ========
        # 寫入 MongoDB
        db = get_db(mongo_uri, db_name)
        upsert_leetcode_problems(db, feature_docs)
        upsert_leetcode_summary_partial(db, summary_docs_leetcode)
    except Exception:
        logger.opt(exception=True).critical("Task 3-A (LeetCode) job failed")
        raise

    logger.success("=== Task 3-A: LeetCode GraphQL ETL 完成 ===")
    return None


def run_task03_ccclub() -> None:
    """執行 ccClub REST API ETL，登入後抓取已解題資料並寫入 MongoDB。

    1. 檢查 MongoDB 連線用的環境變數，缺任一就拋 EnvironmentError。
    2. Extract 登入 ccClub 後抓取已解題清單並逐題補齊 topic 與 difficulty。
    3. Transform 把資料組成題目文檔與 ccClub 側摘要。
    4. Load 以 upsert 寫入 solved_problems_on_ccClub 與 ccClub&leetcode_summary。
    """
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([mongo_uri, db_name]):
        logger.error("請確認  secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")

    logger.info("=== Task 3-B: ccClub ETL 開始 ===")

    # 最外層統一接住內層拋出的例外，只在此處印一次完整 traceback 後再往上拋
    # （loguru 不吃 exc_info=True，需用 logger.opt(exception=True) 才會帶出 traceback）
    try:
        # ======== Extract ========
        # 登入並抓取所有已解題資料
        session, headers = get_session_and_headers()
        raw_solved_problems = fetch_all_solved_problems(session, headers)

        # ======== Transform ========
        # 組裝 documents
        problem_docs = build_ccclub_problem_documents(raw_solved_problems)
        summary_docs_ccClub = build_ccclub_summary_partial(problem_docs)

        # ======== Load ========
        # 寫入 MongoDB
        db = get_db(mongo_uri, db_name)
        upsert_ccclub_problems(db, problem_docs)
        upsert_ccclub_summary_partial(db, summary_docs_ccClub)
    except Exception:
        logger.opt(exception=True).critical("Task 3-B (ccClub) job failed")
        raise

    logger.success("=== Task 3-B: ccClub ETL 完成 ===")
    return None


if __name__ == "__main__":
    # # 地端執行時，需要 uncomment 下面兩行後再執行
    # from dotenv import load_dotenv
    # load_dotenv()
    run_task03_leetcode()
    run_task03_ccclub()
