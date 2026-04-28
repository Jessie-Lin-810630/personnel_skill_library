from datetime import datetime, timezone
from collections import defaultdict
from loguru import logger
"""
程式架構：
    接收e_request_github_api的raw repo list，產出：
    1. build_repo_document()：每個repo各自一個 document，描述repo的特徵。
    2. 將所有repo的documents集合成一個列表。
    3. build_summary_document()：將所有repos的documents統計成一個摘要表，後續將留給streamlit使用。
"""


def build_repo_document(raw_repo: dict,
                        github_username: str,
                        raw_commits: list[dict],
                        raw_readme: dict[str],) -> dict:
    """
    組裝單一 repo 的 一份完整 document。
    """
    logger.info(f"Building document for repo: {raw_repo.get("full_name")}...")
    role = "owner" if raw_repo.get("owner", {}).get("login") == github_username else "collaborator"

    # 只取需要的 commit 欄位
    commits = []
    for c in raw_commits:
        commit_info = {"sha": c["sha"][:7],  # 只存短 sha 省空間
                       "message": c["commit"]["message"],
                       "committed_at": c["commit"]["author"]["date"], }
        commits.append(commit_info)

    repo_doc = {"repo_id": raw_repo["id"],
                "repo_name": raw_repo["name"],
                "repo_full_name": raw_repo["full_name"],
                "description": raw_repo.get("description", ""),
                # 如果language是None或是空字串，則存成"others"，"others"放在 or 後面而不是 .get() 的default，是希望不要存空字串
                "language": raw_repo.get("language") or "others",
                "is_private": raw_repo["private"],
                "role": role,
                "created_at": raw_repo["created_at"],
                "pushed_at": raw_repo.get("pushed_at", None),
                "stars": raw_repo.get("stargazers_count", 0),
                "topics": raw_repo.get("topics", []),
                "commit_counts": len(commits),
                "commits": commits,
                "readme_summary": raw_readme.get("readme_summary", ""),
                "readme_url": raw_readme.get("readme_html_url", ""),
                "fetched_at": datetime.now(timezone.utc),
                }
    logger.success(f"Built document for repo: {repo_doc["repo_full_name"]}")
    return repo_doc


def build_summary_document(all_repo_docs: list[dict]) -> dict:
    """
    產出給 Streamlit 用的統計快照
    """
    logger.info("Building summary documents for all repos...")
    by_role = defaultdict(int)
    by_language = defaultdict(int)
    total_commits = 0
    for repo in all_repo_docs:
        by_role[repo["role"]] += 1
        by_language[repo["language"]] += 1
        total_commits += repo["commit_counts"]

    # 最近有 push 的 repo（按 pushed_at 降序）
    sorted_repos = sorted(all_repo_docs, key=lambda r: r["pushed_at"] or "", reverse=True)
    recent_repos = []
    for r in sorted_repos:
        if r["pushed_at"] is not None:
            recent_repos.append({"repo_name": r["repo_name"],
                                 "pushed_at": r["pushed_at"],
                                 "language": r["language"],
                                 "description": r["description"],
                                 })

    summary_docs = {"snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "total_repos": len(all_repo_docs),
                    "by_role": dict(by_role),
                    "by_language": dict(by_language),
                    "total_commits": total_commits,
                    "recent_three_repos": recent_repos[0:3],  # 留三個
                    }
    logger.success(f"Built summary documents for {len(all_repo_docs)} repos")
    return summary_docs


if __name__ == "__main__":
    # 測試區：
    import e_request_github_api

    e_request_github_api.load_dotenv()
    git_token = e_request_github_api.os.getenv("GITHUB_TOKEN")
    git_username = e_request_github_api.os.getenv("GITHUB_USERNAME")
    headers = e_request_github_api._get_headers(git_token, git_username)

    # 以 headers 抓取所有 repos，回傳 list of dicts
    all_repos = e_request_github_api.fetch_repos(headers)

    # 先用一個 repo 測試，確認能夠進一步請求到 commits 與 README
    # 測試前需要擷取repo_name 與 owner 供下面兩支函式
    all_repo_docs = []
    for raw_repo in all_repos:
        repo_name = raw_repo.get("name")
        owner = raw_repo.get("owner", {}).get("login")

        # 測試 commits 與 README endpoint 正常回傳資料
        repo_commits = e_request_github_api.fetch_a_repo_commits(owner, repo_name, headers)
        repo_readme = e_request_github_api.fetch_a_repo_readme(owner, repo_name, headers)

        # 測試 build_repo_document()
        a_repo_doc = build_repo_document(raw_repo, git_username, repo_commits, repo_readme)

        # 測試 build_summary_document()
        all_repo_docs.append(a_repo_doc)
        break
    summary_docs = build_summary_document(all_repo_docs)
    print(summary_docs)
