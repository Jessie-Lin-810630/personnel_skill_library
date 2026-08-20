"""task02 Transform：把 Extract 抓來的 raw repo list 清洗成 MongoDB document 與彙整摘要。

1. 函式 build_repo_document 為每個 repo 各組出一份描述其特徵的 document。
2. main 把所有 repo 的 document 收集成一個列表。
3. 函式 build_summary_document 把所有 repo 的 document 統計成一份摘要表，供後續 Streamlit 使用。
"""

from collections import defaultdict
from datetime import datetime, timezone

from loguru import logger


def _parse_iso_datetime(value: str | None) -> datetime | None:
    """把 GitHub API 回傳的 ISO 8601 時間字串轉成 datetime 物件。

    Note:
        - 缺值不補預設時間而是原樣回 None，因為 pushed_at 這類欄位為空代表「從未發生過」，
          填任何時間都會讓後續統計失真。
        - build_summary_document 的排序另有處理 None 的方式。

    Args:
        value: GitHub API 回傳的 ISO 8601 時間字串，例如 2026-04-23T02:13:17Z，或 None。

    Returns:
        對應的 datetime 物件；傳入 None 或空字串時回傳 None。

    Raises:
        ValueError: 字串非空但不符合 ISO 8601 格式時拋出。
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

    1. 比對 owner.login 與本人帳號，判定這個 repo 的身分是 owner 還是 collaborator。
    2. 只留下 committer email 等於本人的 commit，逐筆去重後取短 sha、訊息與提交時間。
    3. 把 repo 本身的屬性、commit 統計與 README 摘要組成同一份 document。

    Note:
        - commit 以整筆內容比對去重，因為同一次提交在分支與合併後會重複出現在多個 branch，
          不去重會讓 commit_counts 灌水。
        - 只留本人 email 的 commit，是為了讓統計反映本人的實際產出，
          因此協作 repo 裡他人的提交不會出現在這份 document。
        - language 為 None 或空字串時填 others，讓下游統計不必再處理缺值；
          這個預設值寫在判斷式而非取值的預設參數，是因為 GitHub 兩種空值都可能出現。
        - fetched_at 記的是這次執行的時間，不是 GitHub 上的任何時間。

    Args:
        raw_repo: 單一 repo 的原始字典，取自 fetch_repos 回傳清單的其中一個元素。
        github_username: 本人的 GitHub 帳號，用來判定身分。
        github_mail: 本人的 commit email，用來篩出自己的提交。
        raw_commits: 該 repo 的原始 commit 清單，取自 fetch_a_repo_commits 的回傳值。
        raw_readme: 該 repo 的 README 字典，含 readme_summary 與 readme_html_url，
            取自 fetch_a_repo_readme 的回傳值。

    Returns:
        單一 repo 的 document 字典，可直接寫入 github_repos。

    Raises:
        KeyError: raw_repo 缺少 id、name、full_name、private 或 created_at 任一必要欄位，
            或 raw_commits 的某筆缺少 sha、commit.message 與 commit 作者資訊時拋出。
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

    1. 逐份累計各身分與各語言的 repo 數，以及所有 repo 的 commit 總數。
    2. 依 pushed_at 由新到舊排序，濾掉從未 push 過的 repo，取最前面三個。
    3. 連同當日日期組成一份快照。

    Note:
        - 排序時把 pushed_at 為 None 者換成可取得的最小時間，否則 None 與 datetime 相比會拋 TypeError；
          排完再濾掉這些 repo，所以從未 push 過的不會出現在最近清單裡。
        - snapshot_date 只保留到日、時分秒歸零，讓 Load 層能以日為粒度 upsert，
          同一天重跑會覆蓋當天的快照而不是新增一筆。

    Args:
        all_repo_docs: build_repo_document 產出的所有 repo document 清單。

    Returns:
        含 snapshot_date、total_repos、by_role、by_language、total_commits 與
        recent_three_repos 六個鍵的摘要字典；傳入空清單時各項統計為 0 或空值。
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
