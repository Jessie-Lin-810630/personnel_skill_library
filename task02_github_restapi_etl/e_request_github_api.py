"""task02 Extract：透過 GitHub REST API 的多個 endpoint 抓取 repo 清單、commits 與 README。

1. 函式 get_headers 依 token 與 username 組出後續請求共用的 headers。
2. 函式 _check_and_wait_rate_limit 在每次收到回應後檢查剩餘配額，配額觸及緩衝值就先暫停到重置時間，避免觸發 403 或 429。
3. 函式 _paginate 處理分頁並在遇到 rate limit 時重試，回傳完整的 list of dict。
4. 函式 fetch_repos 透過 _paginate 抓取 endpoint /user/repos 的所有 repo 清單。
5. 函式 fetch_all_branches 透過 _paginate 抓取單一 repo 的所有 branch 名稱。
6. 函式 fetch_a_repo_commits 逐 branch 透過 _paginate 抓取單一 repo 的 commits 歷史。
7. 函式 fetch_a_repo_readme 抓取單一 repo 的 README 文字內容。
"""

import base64
import time
from datetime import datetime, timezone

import requests
from loguru import logger

BASE_URL = "https://api.github.com"  # 根據後綴字拼接出不同 endpoint URL


def get_headers(token: str, username: str) -> dict:
    """依 token 與 username 組出後續請求 GitHub API 共用的 headers。

    Args:
        token: GitHub personal access token。
        username: GitHub 帳號名稱，寫入 User-Agent。

    Returns:
        可直接帶入 requests 的 headers dict。
    """
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": f"{username}",
    }


def _check_and_wait_rate_limit(response: requests.Response, rate_limit_buffer: int = 100) -> None:
    """每收到 response 後用此函式檢查剩餘配額，若觸及緩衝值就主動 sleep 到 reset 時間點。

    先處理 retry-after（secondary rate limit），再依 x-ratelimit-remaining 與
    x-ratelimit-reset 判斷是否要暫停。三個 rate limit header 的意義：
      retry-after 為觸發 secondary rate limit 時要等的秒數，優先處理。
      x-ratelimit-remaining 為這個小時內還剩幾次 request，即剩餘配額。
      x-ratelimit-reset 為配額重置的 UTC epoch seconds。

    Args:
        response: 剛拿到的 requests.Response，從其 header 讀配額資訊。
        rate_limit_buffer: x-ratelimit-remaining 低於此緩衝值就暫停，預設 100 次。
    """
    # 優先處理 retry-after（secondary rate limit 用）
    retry_after = response.headers.get("retry-after")
    if retry_after:
        wait_sec = int(retry_after)
        logger.warning(f"Received retry-after, so wait for {wait_sec} seconds...")
        time.sleep(wait_sec)
        return None

    remaining = response.headers.get("x-ratelimit-remaining")
    reset_ts = response.headers.get("x-ratelimit-reset")

    if remaining is None or reset_ts is None:
        return None  # 某些 endpoint 不回傳這些 header，直接跳過

    remaining = int(remaining)
    reset_ts = int(reset_ts)

    logger.debug(f"Rate limit remains：{remaining} requests, will reset at epoch {reset_ts} seconds.")

    if remaining <= rate_limit_buffer:
        now_epoch = int(datetime.now(timezone.utc).timestamp())

        # +5 秒為安全邊際，避免萬一本機時鐘 (now_epoch) 與伺服器時鐘 (reset_ts) 略有不同步；
        # 或是伺服器重置 x-ratelimit-remaining 的動作延遲。
        # 此時 (reset_ts - now_epoch) 是低估的、有欠精準，故最好 +5 秒保險。
        wait_sec = max(reset_ts - now_epoch + 5, 0)
        reset_time_str = datetime.fromtimestamp(reset_ts, tz=timezone.utc).strftime("%H:%M:%S UTC")
        logger.warning(
            f"Rate limit remains {remaining} requests, lower than the buffer [{rate_limit_buffer}]."
            f"Will pause for {wait_sec} seconds until reach {reset_time_str}..."
        )
        time.sleep(wait_sec)
        return None
    return None


def _paginate(url: str, headers: dict, params: dict = None, *, timeout: int = 10) -> list[dict]:
    """通用分頁抓取器，逐頁抓完指定 endpoint 的所有結果。

    每頁以 per_page=100 抓取以減少 request 次數，每次回應都檢查 rate limit，
    遇 403 或 429 就等 300 秒重試，每頁最多重試 3 次，但如有連線層錯誤直接往外拋不重試。

    Args:
        url: 要分頁抓取的 API endpoint。
        headers: 請求共用的 headers。
        params: 額外的 query 參數，預設 None。
        timeout: 單次請求逾時秒數，預設 10。

    Returns:
        所有頁面合併後的 list of dict。
    """
    results = []
    params = params or {}
    params["per_page"] = 100
    params["page"] = 1
    attempts = 3
    while True:
        resp = None
        try:
            for i in range(attempts):
                logger.info(f"Requesting {url} with page {params['page']} and attempt {i + 1}/{attempts}....")
                resp = requests.get(url, headers=headers, params=params, timeout=timeout)

                # 每次 response 都檢查 rate limit，主動在耗盡前暫停
                _check_and_wait_rate_limit(resp)

                # 遇到 rate limit（403/429）就等 300 秒重試一次
                if resp.status_code in (403, 429):
                    logger.warning(
                        f"Rate limit reached，wait for 300 seconds before retrying... (page={params['page']})"
                    )
                    time.sleep(300)
                    continue

                elif resp.status_code == 200:
                    logger.info(f"Successfully requested url {url}，page: {params['page']}")
                    break

            # for 迴圈結束後，補上這個保險，以避免"在連續三次403/429跳出迴圈後，仍然執行了else後面的程序"。
            if resp.status_code != 200 or resp is None:
                raise Exception(f"All {attempts} attempts failed for {url}, last status: {resp.status_code}")

            # HTTP 4xx/5xx（例如：409，排除403&429這種rate limit），讓呼叫_paginate()的外層函式決定怎麼處理
            # 因為每個409的情況隨使用的endpoint不同而可能有不同處理方式
            resp.raise_for_status()

        except requests.ConnectionError as e:  # 網路層錯誤（DNS 失敗、連線中斷等）直接往外拋，不需要重試
            logger.error(f"Network error when requesting {url}, msg error: {e}")
            raise
        else:
            batch = resp.json()
            if not batch:
                break
            results.extend(batch)
            params["page"] += 1

    return results


def fetch_repos(headers: dict) -> list[dict]:
    """抓取使用者身為 owner 與 collaborator 的所有 repo。

    以 endpoint /user/repos 搭配 type=all 一次涵蓋 owner、collaborator 與
    organization_member，真正的 role 留待 transform 階段用 owner.login 判斷。

    Args:
        headers: 請求共用的 headers。

    Returns:
        所有 repo 的 raw dict 清單。
    """
    url = f"{BASE_URL}/user/repos"
    all_repos = _paginate(url, headers)
    logger.success(f"共抓到 {len(all_repos)} 個 repos。")
    return all_repos


def fetch_all_branches(owner: str, repo_name: str, headers: dict) -> list:
    """抓取單一 repo 的所有 branch 名稱。

    Args:
        owner: repo 擁有者的 login 名稱。
        repo_name: repo 名稱。
        headers: 請求共用的 headers。

    Returns:
        該 repo 所有 branch 名稱的清單。
    """
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/branches"
    required_branches = []
    try:
        branches = _paginate(url, headers)
        logger.info(f"Successfully requesting for repo {repo_name}. Total branches fetched: {len(branches)}")
        for b in branches:
            required_branches.append(b.get("name"))
        return required_branches
    except requests.HTTPError as e:
        logger.error(f"Error when requesting the repo {repo_name}. Status code: {branches.status_code}, Error msg: {e}")
        raise Exception(f"Error when requesting {url}.")


def fetch_a_repo_commits(owner: str, repo_name: str, headers: dict, branches: list[str]) -> list[dict]:
    """逐 branch 抓取單一 repo 的所有 commits。

    空 repo（沒有任何 commit）的 branch 會回傳 409，遇到時跳過並回傳空清單。

    Args:
        owner: repo 擁有者的 login 名稱。
        repo_name: repo 名稱。
        headers: 請求共用的 headers。
        branches: 要逐一抓取 commits 的 branch 名稱清單。

    Returns:
        該 repo 所有 commit 的 raw dict 清單，每筆含 sha、commit.message 與 commit.author.date。
    """
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/commits"
    all_commits = []
    for b in branches:
        try:
            params = {"sha": b}
            commits = _paginate(url, headers, params, timeout=30)
            logger.info(f"Already requesting. For the branch {b}, Total commits fetched: {len(commits)}")
            all_commits.extend(commits)
        except requests.HTTPError as e:
            # 空 repo（沒有任何 commit）會回傳 409，需要跳過
            if e.response.status_code == 409:
                logger.warning(f"{repo_name}：空 repo、空 branch，跳過 commits 抓取")
                return []

            logger.error(f"Error when requesting the branch {b}. Status code: {commits.status_code}, Error msg: {e}")
            raise Exception(f"Error when requesting {url}.")

    logger.info(f"Successfully requesting. Total commits fetched in the repo: {len(all_commits)}")
    return all_commits


def fetch_a_repo_readme(owner: str, repo_name: str, headers: dict, returned_max_chars: int = 300) -> dict:
    """抓取單一 repo 的 README，回傳前 returned_max_chars 個字元。

    找不到 README（404）時回傳 readme_html_url 與 readme_summary 皆為空字串的 dict。

    Args:
        owner: repo 擁有者的 login 名稱。
        repo_name: repo 名稱。
        headers: 請求共用的 headers。
        returned_max_chars: README 內文擷取的最大字元數，預設 300。

    Returns:
        含 readme_html_url 與 readme_summary 兩鍵的 dict。
    """
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/readme"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 404:
            return {"readme_html_url": "", "readme_summary": ""}
    except requests.RequestException as e:
        logger.error(f"Error when requesting README. Status code: {resp.status_code}, Error msg: {e}")
        raise Exception(f"Error when requesting README for {repo_name}.")

    html_url = resp.json().get("html_url", "")
    content_b64 = resp.json().get("content", "")
    decoded_content = base64.b64decode(content_b64).decode("utf-8", errors="ignore")

    readme = {
        "readme_html_url": html_url,
        "readme_summary": decoded_content[:returned_max_chars],
    }
    logger.success(f"Completed requesting the README.md of {repo_name}.")
    return readme
