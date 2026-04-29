import os
from dotenv import load_dotenv
from loguru import logger
from .e_request_github_api import _get_headers, fetch_repos, fetch_a_repo_commits, fetch_a_repo_readme
from .t_transform_github import build_repo_document, build_summary_document
from .l_load_to_mongodb import get_db, upsert_repos, upsert_repo_summary

"""
一次執行E、T、L。
"""

load_dotenv()


def run_task02() -> None:
    git_token = os.getenv("GITHUB_TOKEN")
    git_username = os.getenv("GITHUB_USERNAME")
    headers = _get_headers(git_token, git_username)
    mongo_uri = os.getenv("MONGO_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([git_token, git_username, mongo_uri, db_name]):
        logger.error("請確認 .env 已設定 GITHUB_TOKEN / GITHUB_USERNAME / MONGO_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 .env 已設定 GITHUB_TOKEN / GITHUB_USERNAME / MONGO_URI / MONGO_DB_NAME")

    logger.info("=== Task 2: GitHub REST API ETL 開始 ===")

    # ======== Extract ========
    # 以 headers 抓取所有 repos，回傳 list of dicts
    all_repos = fetch_repos(headers)

    # 先擷取repo_name 與 owner 供下面兩支函式使用
    all_repo_docs = []
    for raw_repo in all_repos:
        repo_name = raw_repo.get("name")
        owner = raw_repo.get("owner", {}).get("login")

        # 從 /commits 與 /readme endpoint 獲取資料
        repo_commits = fetch_a_repo_commits(owner, repo_name, headers)
        repo_readme = fetch_a_repo_readme(owner, repo_name, headers)

        # ======== Transform ========
        # 建立單一repo文檔
        a_repo_doc = build_repo_document(raw_repo, git_username, repo_commits, repo_readme)
        all_repo_docs.append(a_repo_doc)

    # 建立摘要文檔
    summary_docs = build_summary_document(all_repo_docs)

    # ======== Load ========
    db = get_db(mongo_uri, db_name)
    # 存入文檔集 github_repos
    upsert_repos(db, all_repo_docs)
    upsert_repo_summary(db, summary_docs)

    logger.success("=== Task 2: GitHub REST API ETL 完成 ===")
    return None


if __name__ == "__main__":
    run_task02()
