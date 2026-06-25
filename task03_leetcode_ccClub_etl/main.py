import os

from dotenv import load_dotenv
from loguru import logger

from .e_crawler_ccClub import _get_session_and_headers, fetch_all_solved_problems
from .e_query_leetcode_graphql import _get_headers, fetch_solved_problem_stats, fetch_solved_problems_features
from .l_load_ccClub_doc_to_mongodb import upsert_ccclub_problems, upsert_ccclub_summary_partial
from .l_load_leetcode_doc_to_mongodb import get_db, upsert_leetcode_problems, upsert_leetcode_summary_partial
from .t_transform_ccClub import build_ccclub_problem_documents, build_ccclub_summary_partial
from .t_transform_leetcode import build_leetcode_summary_partial, build_problem_feat_documents

"""
一次執行 Task 3-A：LeetCode GraphQL ETL。
"""
load_dotenv()


def run_task03_leetcode() -> None:
    username = os.getenv("LEETCODE_USERNAME")
    session = os.getenv("LEETCODE_SESSION")
    csrf_token = os.getenv("CSRF_TOKEN")
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([username, session, csrf_token, mongo_uri, db_name]):
        logger.error(
            "請確認 .env 或 secret manager 已設定 LEETCODE_USERNAME / LEETCODE_SESSION / "
            "LEETCODE_CSRF_TOKEN / MONGO_ALTAS_URI / MONGO_DB_NAME"
        )
        raise EnvironmentError(
            "請確認 .env 或 secret manager 已設定 LEETCODE_USERNAME / LEETCODE_SESSION / "
            "LEETCODE_CSRF_TOKEN / MONGO_ALTAS_URI / MONGO_DB_NAME"
        )

    logger.info("=== Task 3-A: LeetCode GraphQL ETL 開始 ===")

    headers = _get_headers(csrf_token, session, username)

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

    logger.success("=== Task 3-A: LeetCode GraphQL ETL 完成 ===")
    return None


def run_task03_ccclub() -> None:
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([mongo_uri, db_name]):
        logger.error("請確認 .env 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 .env 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")

    logger.info("=== Task 3-B: ccClub ETL 開始 ===")

    # ======== Extract ========
    # 登入並抓取所有已解題資料
    session, headers = _get_session_and_headers()
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

    logger.success("=== Task 3-B: ccClub ETL 完成 ===")
    return None


if __name__ == "__main__":
    run_task03_leetcode()
    run_task03_ccclub()
