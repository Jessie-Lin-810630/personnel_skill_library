import base64
from datetime import datetime, timezone
import time
from loguru import logger
import requests
import os
from dotenv import load_dotenv


"""
程式架構：
Extract：透過 GitHub REST API 的多個 endpoints 分別抓取 
(1) Endpoint `/user/repos`: 抓取所有repo 清單
(2) Endpoint `repos/{owner}/{repo_name}/commits`: 抓取單一 repo 的 commits 歷史
(3) Endpoint `repos/{owner}/{repo_name}/readme`: 抓取單一 repo 的 README.md 文字內容

函式設計：
- _get_headers(token, username): 產生 headers 供後續打 API 使用)
- _check_and_wait_rate_limit(): 主動在每次取得 response 後檢查剩餘配額，若剩餘配額達到緩衝值就主動暫停到reset時間點，避免真的觸發403或429的錯誤。
- _paginate(): 處理 Github API 分頁邏輯，同時利用重試機制應對 rate-limit 風險。回傳完整list of dicts。
- fetch_repos(headers): 抓取所有 repos，中途呼叫_paginate()
- fetch_a_repo_commits(): 抓取單一 repo 的 commits，中途呼叫_paginate()
- fetch_a_repo_readme(): 抓取單一 repo 的 README.md 內容
"""

BASE_URL = "https://api.github.com"  # 根據後綴字拼接出不同 endpoint URL
load_dotenv()


def _get_headers(token: str, username: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": f"{username}"
    }


def _check_and_wait_rate_limit(response: requests.Response,
                               rate_limit_buffer: int = 100) -> None:
    """
    用於每次拿到 response 後呼叫。此函式從 response header 讀取剩餘配額，
    若剩餘配額達到 rate_limit_buffer 就主動 sleep 到 reset 時間點。

    GitHub 回傳的 rate limit headers：
      x-ratelimit-remaining : 這個小時內還剩幾次 request (str of int)
      x-ratelimit-reset     : 配額重置的 UTC epoch seconds (str of int)
      retry-after           : 若觸發 secondary rate limit，要等幾秒 (優先處理)
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
        wait_sec = max(reset_ts - now_epoch + 5, 0)  # +5 秒緩衝避免時差
        reset_time_str = datetime.fromtimestamp(reset_ts, tz=timezone.utc).strftime("%H:%M:%S UTC")
        logger.warning(f"Rate limit remains {remaining} requests, lower than the buffer [{rate_limit_buffer}]."
                       f"Will pause for {wait_sec} seconds until reach {reset_time_str}..."
                       )
        time.sleep(wait_sec)
        return None
    return None


def _paginate(url: str, headers: dict, params: dict = None) -> list[dict]:
    """
    通用分頁抓取器。
    GitHub 預設每頁 30 筆，per_page 最大 100，這裡統一設 100 減少 request 次數。
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
                logger.info(f"Requesting {url} with page {params["page"]} and attempt {i + 1}/{attempts}....")
                resp = requests.get(url, headers=headers, params=params, timeout=10)

                # 每次 response 都檢查 rate limit，主動在耗盡前暫停
                _check_and_wait_rate_limit(resp)

                # 遇到 rate limit（403/429）就等 300 秒重試一次
                if resp.status_code in (403, 429):
                    logger.warning(
                        f"Rate limit reached，wait for 300 seconds before retrying... (page={params["page"]})")
                    time.sleep(300)
                    continue

                elif resp.status_code == 200:
                    logger.info(f"Successfully requested url {url}，page: {params["page"]}")
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
    """
    抓取自己身為 Owner 與 collaborator 的所有 repos。
    type=all 同時涵蓋 owner + collaborator，再用 affiliation 細分角色。

    GitHub API type=all 實際上包含：owner、collaborator、organization_member
    我們在 transform 階段用 owner.login 來判斷真正的 role。
    """
    url = f"{BASE_URL}/user/repos"
    all_repos = _paginate(url, headers)
    logger.success(f"共抓到 {len(all_repos)} 個 repos。")
    return all_repos


def fetch_a_repo_commits(owner: str,
                         repo_name: str,
                         headers: dict) -> list[dict]:
    """
    抓取單一 repo 的所有 commits。
    回傳欄位：sha、commit.message、commit.author.date
    """
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/commits"
    try:
        commits = _paginate(url, headers)
        logger.success(f"Completed requesting. Total commits fetched: {len(commits)}")
        return commits
    except requests.HTTPError as e:
        # 空 repo（沒有任何 commit）會回傳 409，需要跳過
        if e.response.status_code == 409:
            logger.warning(f"{repo_name}：空 repo，跳過 commits 抓取")
            return []

        logger.error(f"Error when requesting. Status code: {commits.status_code}, Error msg: {e}")
        raise Exception(f"Error when requesting {url}.")


def fetch_a_repo_readme(owner: str,
                        repo_name: str,
                        headers: dict,
                        returned_max_chars: int = 300) -> dict:
    """
    抓取 README，回傳前 returned_max_chars個字符。
    找不到 README 回傳空字串。

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

    readme = {"readme_html_url": html_url,
              "readme_summary": decoded_content[:returned_max_chars],
              }
    logger.success(f"Completed requesting the README.md of {repo_name}.")
    return readme


if __name__ == "__main__":
    # 測試區：

    # 拼湊 headers
    git_token = os.getenv("GITHUB_TOKEN")
    git_username = os.getenv("GITHUB_USERNAME")
    headers = _get_headers(git_token, git_username)

    # 以 headers 抓取所有 repos，回傳 list of dicts
    all_repos = fetch_repos(headers)

    # 先用一個 repo 測試，確認能夠進一步請求到 commits 與 README
    # 測試前需要擷取repo_name 與 owner 供下面兩支函式
    repo_name = all_repos[0].get("name")
    owner = all_repos[0].get("owner", {}).get("login")

    # 測試 commits 與 README endpoint 正常回傳資料
    repo_commits = fetch_a_repo_commits(owner, repo_name, headers)
    repo_reame = fetch_a_repo_readme(owner, repo_name, headers)
