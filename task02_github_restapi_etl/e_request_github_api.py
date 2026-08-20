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
import binascii
import time
from datetime import datetime, timezone

import requests
from loguru import logger

BASE_URL = "https://api.github.com"  # 根據後綴字拼接出不同 endpoint URL


def get_headers(token: str, username: str) -> dict:
    """依 token 與 username 組出後續請求 GitHub API 共用的 headers。

    Note:
        - API 版本以 X-GitHub-Api-Version 寫死在回傳值裡，GitHub 日後淘汰該版本時要在這裡改。

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
    """每收到回應後檢查剩餘配額，若觸及緩衝值就主動暫停到配額重置的時間點。

    先看 retry-after，有值就依它指定的秒數等待後結束；沒有才改看剩餘次數與重置時戳，
    剩餘次數低於緩衝值時暫停到重置時間為止。

    Note:
        - 三個 header 各有意義：retry-after 是觸發 secondary rate limit 時 GitHub 指定要等的秒數，
          優先處理；x-ratelimit-remaining 是這個小時內還剩幾次請求；x-ratelimit-reset 是配額重置的
          UTC epoch 秒數。
        - 部分 endpoint 不回傳後兩者，此時直接跳過檢查。
        - 等待秒數多加 5 秒是安全邊際，因為本機時鐘與伺服器時鐘可能不同步、伺服器重置配額也可能延遲，
          算出來的差值偏低估。
        - 這支函式以阻塞方式等待，最長可能佔住整個執行緒將近一小時。

    Args:
        response: 剛拿到的 requests.Response，從其 header 讀配額資訊。
        rate_limit_buffer: 剩餘次數低於此緩衝值就暫停，預設 100 次。

    Returns:
        None: 只做等待，不回傳值，也不更動傳入的 response。
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

    每頁固定要 100 筆以減少請求次數，抓到空頁就停。每收到一次回應都檢查配額，
    收到 403 或 429 時等 300 秒再試，同一頁最多試 3 次。

    Note:
        - 403 與 429 在這裡當成配額問題而重試，其餘非 2xx 一律往外拋，交給呼叫端決定怎麼處理，
          因為同一個狀態碼在不同 endpoint 的意義不同，例如 409 在 commits 代表空 repo。
        - 連線層錯誤與 JSON 解析失敗都不重試，直接往外拋。
        - 3 次都沒拿到 200 時會拋出通用 Exception，而不是留著非 2xx 的回應往下走。

    Args:
        url: 要分頁抓取的 API endpoint。
        headers: 請求共用的 headers。
        params: 額外的 query 參數，預設 None；傳入的字典會被就地加上分頁參數。
        timeout: 單次請求逾時秒數，預設 10。

    Returns:
        所有頁面合併後的字典清單；endpoint 沒有任何結果時為空清單。

    Raises:
        Exception: 同一頁重試 3 次仍未取得 200 時拋出。
        requests.HTTPError: 回應為 403 與 429 以外的非 2xx 時拋出。
        requests.ConnectionError: 連線失敗或中斷時拋出。
        requests.Timeout: 請求逾時時拋出。
        ValueError: 回應內容不是合法 JSON 時拋出。
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
            if resp is None or resp.status_code != 200:
                last_status = resp.status_code if resp is not None else "N/A"
                logger.error(f"All {attempts} attempts failed for {url}, last status: {last_status}")
                raise Exception(f"All {attempts} attempts failed for {url}")

            # HTTP 4xx/5xx（例如：409，排除403&429這種rate limit），讓呼叫_paginate()的外層函式決定怎麼處理
            # 因為每個409的情況隨使用的endpoint不同而可能有不同處理方式
            resp.raise_for_status()

            batch = resp.json()

        # 網路層錯誤（DNS 失敗、連線中斷、逾時等）直接往外拋，不需要重試；HTTPError 故意不接，留給中間層補 repo context
        except requests.ConnectionError as e:
            logger.error(f"Network error when requesting {url}, msg error: {e}")
            raise
        except requests.Timeout as e:
            logger.error(f"Network error when requesting {url}, msg error: {e}")
            raise
        except ValueError:  # ValueError 已涵蓋 json.JSONDecodeError
            logger.error(f"Malformed JSON from {url}, page {params['page']}")
            raise
        else:
            if not batch:
                break
            results.extend(batch)
            params["page"] += 1

    return results


def fetch_repos(headers: dict) -> list[dict]:
    """抓取使用者身為 owner 與 collaborator 的所有 repo。

    以 /user/repos 一次取回這個 token 能看到的全部 repo，不在請求階段區分身分。

    Note:
        - 該 endpoint 預設就涵蓋 owner、collaborator 與 organization_member 三種身分，
          回應本身不標示是哪一種，真正的身分留待 build_repo_document 以 owner.login 判斷。

    Args:
        headers: 請求共用的 headers。

    Returns:
        所有 repo 的原始字典清單。

    Raises:
        Exception: 分頁抓取失敗時，由 _paginate 拋出的例外一律原樣往外拋。
    """
    url = f"{BASE_URL}/user/repos"
    all_repos = _paginate(url, headers)
    logger.success(f"共抓到 {len(all_repos)} 個 repos。")
    return all_repos


def fetch_all_branches(owner: str, repo_name: str, headers: dict) -> list:
    """抓取單一 repo 的所有 branch 名稱。

    分頁取回該 repo 的 branch 清單後，只留下每個 branch 的名稱。

    Note:
        - 請求失敗時只記一行帶狀態碼的訊息就原樣往外拋，不在這裡印 traceback，
          以免同一個例外在各層重複記錄；完整 traceback 由 run_task02 最外層統一印出。

    Args:
        owner: repo 擁有者的 login 名稱。
        repo_name: repo 名稱。
        headers: 請求共用的 headers。

    Returns:
        該 repo 所有 branch 名稱的清單。

    Raises:
        requests.HTTPError: GitHub 回應非 2xx 時拋出。
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
        # 只記業務簡短訊息、不放 exc_info；純 raise 保留 HTTPError 型別交給最外層印 traceback
        logger.error(f"Failed to fetch branches for {owner}/{repo_name}, status {e.response.status_code}")
        raise


def fetch_a_repo_commits(owner: str, repo_name: str, headers: dict, branches: list[str]) -> list[dict]:
    """逐 branch 抓取單一 repo 的所有 commits。

    對每個 branch 各分頁抓一次，把結果合併成同一份清單。

    Note:
        - 沒有任何 commit 的 repo 會回應 409，此時記一筆 warning 後直接回空清單，不視為失敗；
          由於空 repo 的每個 branch 都會是 409，這裡不繼續試其他 branch。
        - 合併結果不去重，同一個 commit 若同時存在於多個 branch 會重複出現，
          去重與篩選作者留在 build_repo_document 處理。
        - 單次請求逾時放寬到 30 秒，因為 commit 歷史長的 repo 單頁回應較慢。

    Args:
        owner: repo 擁有者的 login 名稱。
        repo_name: repo 名稱。
        headers: 請求共用的 headers。
        branches: 要逐一抓取 commits 的 branch 名稱清單。

    Returns:
        該 repo 所有 commit 的原始字典清單，每筆含 sha、commit.message 與 commit.author.date；
        空 repo 時為空清單。

    Raises:
        requests.HTTPError: GitHub 回應 409 以外的非 2xx 時拋出。
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

            # 只記業務簡短訊息、不放 exc_info；純 raise 保留 HTTPError 型別交給最外層印 traceback
            logger.error(f"Failed to fetch commits for {owner}/{repo_name} branch {b}, status {e.response.status_code}")
            raise

    logger.info(f"Successfully requesting. Total commits fetched in the repo: {len(all_commits)}")
    return all_commits


def fetch_a_repo_readme(owner: str, repo_name: str, headers: dict, returned_max_chars: int = 300) -> dict:
    """抓取單一 repo 的 README，只取開頭一小段內文。

    取回 README 後把 base64 內容解碼成文字，截到指定字元數為止。

    Note:
        - repo 沒有 README 會回應 404，這是正常情形，此時兩個欄位都回空字串、不視為失敗；
          其餘非 2xx 一律往外拋，不靜默吞掉。
        - 解碼時忽略無法解碼的位元組，因此含非 UTF-8 內容的 README 會少掉那些字元，
          但不會中斷整批抓取。
        - 這支函式不分頁，README 只有一份。

    Args:
        owner: repo 擁有者的 login 名稱。
        repo_name: repo 名稱。
        headers: 請求共用的 headers。
        returned_max_chars: README 內文擷取的最大字元數，預設 300。

    Returns:
        含 readme_html_url 與 readme_summary 兩個鍵的字典；沒有 README 時兩者都是空字串。

    Raises:
        requests.HTTPError: GitHub 回應 404 以外的非 2xx 時拋出。
        requests.ConnectionError: 連線失敗或中斷時拋出。
        requests.Timeout: 請求逾時時拋出。
        ValueError: 回應內容不是合法 JSON 時拋出。
        binascii.Error: README 的 base64 內容無法解碼時拋出。
    """
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/readme"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 404:  # 找不到 README 是正常情形，回空字串
            return {"readme_html_url": "", "readme_summary": ""}
        resp.raise_for_status()  # 其餘非 2xx（500/403…）不再靜默吞掉，明確拋出
        payload = resp.json()
        content_b64 = payload.get("content", "")
        decoded_content = base64.b64decode(content_b64).decode("utf-8", errors="ignore")
    # 以下三桶各記不同業務訊息、皆不放 exc_info，純 raise 保留原型別交給最外層印 traceback
    # 網路層錯誤，resp 可能未綁定，故不引用 resp
    except requests.ConnectionError:
        logger.error(f"Network error when fetching README for {owner}/{repo_name}")
        raise
    except requests.Timeout:
        logger.error(f"Network error when fetching README for {owner}/{repo_name}")
        raise
    except requests.HTTPError as e:
        logger.error(f"HTTP {e.response.status_code} when fetching README for {owner}/{repo_name}")
        raise
    # ValueError 已涵蓋 json.JSONDecodeError；base64 解碼失敗為 binascii.Error（非 ValueError 子類）
    except ValueError:
        logger.error(f"Malformed README payload for {owner}/{repo_name}")
        raise
    except binascii.Error:
        logger.error(f"Malformed README payload for {owner}/{repo_name}")
        raise

    readme = {
        "readme_html_url": payload.get("html_url", ""),
        "readme_summary": decoded_content[:returned_max_chars],
    }
    logger.success(f"Completed requesting the README.md of {repo_name}.")
    return readme
