"""task02 Transform：把 Extract 抓來的 raw repo list 清洗成 MongoDB document 與彙整摘要。

1. 函式 build_repo_document 為每個 repo 各組出一份描述其特徵的 document。
2. main 把所有 repo 的 document 收集成一個列表。
3. 函式 build_summary_document 把所有 repo 的 document 統計成一份摘要表，供後續 Streamlit 使用。
"""

from collections import defaultdict
from datetime import datetime, timezone

from loguru import logger


def _parse_iso_datetime(value: str | None) -> datetime | None:
    """把 GitHub API 回傳的 ISO 8601 字串（如 2026-04-23T02:13:17Z）轉成 datetime 物件。

    值為 None 或空字串時回傳 None（例如 pushed_at 可能為 None）。

    Args:
        value: GitHub API 回傳的 ISO 8601 時間字串，或 None。

    Returns:
        對應的 datetime 物件；輸入為空時回傳 None。
    """
    if not value:
        return None
    return datetime.fromisoformat(value)


def build_repo_document(
    raw_repo: dict,
    github_username: str,
    github_mail: str,
    raw_commits: list[dict],
    raw_readme: dict[str],
) -> dict:
    """把單一 repo 的原始資料組裝成一份完整的 MongoDB document。

    以 owner.login 是否等於本人判定 role，只保留本人 email 的 commit 並去重，
    language 為空時填 others。

    Args:
        raw_repo: 單一 repo 的 raw dict。取自 fetch_repos 回傳列表的其中一元素。
        github_username: 本人的 GitHub 帳號，用來判定 owner 或 collaborator。
        github_mail: 本人的 commit email，用來篩出自己的 commit。
        raw_commits: 該 repo 的 raw commit 清單，取自 fetch_a_repo_commits 回傳值。
        raw_readme: 該 repo 的 README dict，含 readme_summary 與 readme_html_url。
        取自 fetch_a_repo_readme 回傳值。

    Returns:
        單一 repo 的 document dict。
    """
    logger.info(f"Building document for repo: {raw_repo.get('full_name')}...")
    role = "owner" if raw_repo.get("owner", {}).get("login") == github_username else "collaborator"

    # 只取需要的 commit 欄位
    commits = []
    for c in raw_commits:
        if c["commit"]["committer"]["email"] == github_mail:
            commit_info = {
                "sha": c["sha"][:7],  # 只存短 sha 省空間
                "message": c["commit"]["message"],
                "committed_at": _parse_iso_datetime(c["commit"]["author"]["date"]),
            }
            if commit_info not in commits:  # 分支出去或merge過來的同個 commit 事件之sha 會一樣，故不需要重複計算 commit
                commits.append(commit_info)

    repo_doc = {
        "repo_id": raw_repo["id"],
        "repo_name": raw_repo["name"],
        "repo_full_name": raw_repo["full_name"],
        "description": raw_repo.get("description", ""),
        # 如果language是None或是空字串，則存成"others"，
        # "others"放在 or 後面而不是 .get() 的default，是希望不要存空字串
        "language": raw_repo.get("language") or "others",
        "is_private": raw_repo["private"],
        "role": role,
        "created_at": _parse_iso_datetime(raw_repo["created_at"]),
        "pushed_at": _parse_iso_datetime(raw_repo.get("pushed_at")),
        "stars": raw_repo.get("stargazers_count", 0),
        "topics": raw_repo.get("topics", []),
        "commit_counts": len(commits),
        "commits": commits,
        "readme_summary": raw_readme.get("readme_summary", ""),
        "readme_url": raw_readme.get("readme_html_url", ""),
        "fetched_at": datetime.now(timezone.utc),
    }
    logger.success(f"Built document for repo: {repo_doc['repo_full_name']}")
    return repo_doc


def build_summary_document(all_repo_docs: list[dict]) -> dict:
    """把所有 repo document 統計成一份給 Streamlit 用的快照摘要。

    統計各 role 與各語言的 repo 數、總 commit 數，並依 pushed_at 降序取最近三個 repo。

    Args:
        all_repo_docs: build_repo_document 產出的所有 repo document 清單。

    Returns:
        含 snapshot_date、total_repos、by_role、by_language、total_commits 與
        recent_three_repos 的摘要 dict。
    """
    logger.info("Building summary documents for all repos...")
    by_role = defaultdict(int)
    by_language = defaultdict(int)
    total_commits = 0
    for repo in all_repo_docs:
        by_role[repo["role"]] += 1
        by_language[repo["language"]] += 1
        total_commits += repo["commit_counts"]

    # 最近有 push 的 repo（按 pushed_at 降序），沒有 push 的會排在最後。
    # pushed_at 型別會是 datetime 或 None，None 在排序時替換成 datetime.min 最小可取得時間，
    # 否則 None 與 datetime 在 sorted() 排序時會出現 TypeError。
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    sorted_repos = sorted(all_repo_docs, key=lambda r: r["pushed_at"] or oldest, reverse=True)
    recent_repos = []
    for r in sorted_repos:
        if r["pushed_at"] is not None:
            recent_repos.append(
                {
                    "repo_name": r["repo_name"],
                    "pushed_at": r["pushed_at"],
                    "language": r["language"],
                    "description": r["description"],
                }
            )

    # snapshot_date 存 datetime 物件、但只表示到日（時分秒毫秒歸零），供以日為粒度的 upsert 與排序。
    snapshot_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    summary_docs = {
        "snapshot_date": snapshot_date,
        "total_repos": len(all_repo_docs),
        "by_role": dict(by_role),
        "by_language": dict(by_language),
        "total_commits": total_commits,
        "recent_three_repos": recent_repos[0:3],  # 留三個
    }
    logger.success(f"Built summary documents for {len(all_repo_docs)} repos")
    return summary_docs
