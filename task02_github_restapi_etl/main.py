"""task02 入口：串接 GitHub REST API ETL 的 Extract、Transform、Load 三階段。

1. Extract 以 GitHub REST API 抓取所有 repo、各 repo 的 commits 與 README。
2. Transform 把原始資料組裝成每個 repo 的 document，並統計成一份彙整摘要。
3. Load 以 upsert 把 document 與摘要寫入 MongoDB 的 github_repos 與 github_summary。

Usage:
    poetry run python -m task02_github_restapi_etl.main

Required .env keys:
    GITHUB_TOKEN      GitHub personal access token.
    GITHUB_USERNAME   GitHub account login name.
    GITHUB_MAIL       Commit author email used to keep only the user's own commits.
    MONGO_ALTAS_URI   MongoDB Atlas connection string.
    MONGO_DB_NAME     Target database name.
"""

import os

from loguru import logger

from .e_request_github_api import (
    fetch_a_repo_commits,
    fetch_a_repo_readme,
    fetch_all_branches,
    fetch_repos,
    get_headers,
)
from .l_load_to_mongodb import get_db, upsert_repo_summary, upsert_repos
from .t_transform_github import build_repo_document, build_summary_document


def run_task02() -> None:
    """task02 總入口，依序執行 GitHub REST API 的 Extract、Transform、Load。

    1. 檢查 GitHub 與 MongoDB 連線用的環境變數，缺任一就拋 EnvironmentError。
    2. Extract 抓取所有 repo，並逐 repo 抓 branches、commits 與 README。
    3. Transform 把每個 repo 組成 document，再統計成一份摘要。
    4. Load 以 upsert 把 document 寫入 github_repos、把摘要寫入 github_summary。
    """
    git_token = os.getenv("GITHUB_TOKEN")
    git_username = os.getenv("GITHUB_USERNAME")
    git_mail = os.getenv("GITHUB_MAIL")
    headers = get_headers(git_token, git_username)
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([git_token, git_username, mongo_uri, db_name]):
        logger.error(
            "請確認 secret managers 已設定 "
            "GITHUB_TOKEN / GITHUB_USERNAME / GITHUB_MAIL / MONGO_ALTAS_URI / MONGO_DB_NAME"
        )
        raise EnvironmentError(
            "請確認 secret managers 已設定 "
            "GITHUB_TOKEN / GITHUB_USERNAME / GITHUB_MAIL / MONGO_ALTAS_URI / MONGO_DB_NAME"
        )

    logger.info("=== Task 02: GitHub REST API ETL 開始 ===")

    # ======== Extract ========
    # 以 headers 抓取所有 repos，回傳 list of dicts
    all_repos = fetch_repos(headers)

    # 先擷取repo_name 與 owner 供下面兩支函式使用
    all_repo_docs = []
    for raw_repo in all_repos:
        repo_name = raw_repo.get("name")
        owner = raw_repo.get("owner", {}).get("login")

        # 找尋該 repo 下的 branches
        branch_list = fetch_all_branches(owner, repo_name, headers)

        # 從 /commits 與 /readme endpoint 獲取資料
        repo_commits = fetch_a_repo_commits(owner, repo_name, headers, branch_list)
        repo_readme = fetch_a_repo_readme(owner, repo_name, headers)

        # ======== Transform ========
        # 建立單一repo文檔，並 append 到統一 list
        a_repo_doc = build_repo_document(raw_repo, git_username, git_mail, repo_commits, repo_readme)
        all_repo_docs.append(a_repo_doc)

    # 建立摘要文檔
    summary_docs = build_summary_document(all_repo_docs)

    # ======== Load ========
    db = get_db(mongo_uri, db_name)
    # 存入文檔集 github_repos 與 github_summary。
    upsert_repos(db, all_repo_docs)
    upsert_repo_summary(db, summary_docs)

    logger.success("=== Task 02: GitHub REST API ETL 完成 ===")
    return None


if __name__ == "__main__":
    run_task02()
