"""task03 Extract（LeetCode）：透過 LeetCode 單一 GraphQL endpoint 抓取已解題清單與統計結果。

1. 函式 get_headers 以登入取得的 csrf_token 與 session 組出 headers，這兩個 cookie 是讓 status 欄位有值的關鍵。
2. 函式 _post_graphql 依傳入的 JSON 查詢語句與 headers 送出請求並捕捉例外。
3. 函式 fetch_solved_problems_features 以 problemsetQuestionList 查詢分頁抓取題型特徵，
   只保留 status 為 AC 的題目，回傳題號、題名、題型與難易度。
4. 函式 fetch_solved_problem_stats 以 userProblemsSolved 查詢抓取解題進度統計，包含解題題數百分比與各難度百分比。

Required .env keys:
    LEETCODE_USERNAME   LeetCode account name.
    LEETCODE_SESSION    LeetCode session cookie.
    CSRF_TOKEN          LeetCode CSRF token cookie.
"""

import time

import requests
from loguru import logger

LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql/"


def get_headers(csrf_token: str, session: str, username: str) -> dict:
    """以登入後取得的 csrf_token 與 leetcode_session 組出 GraphQL 請求用的 headers。

    Note:
        - 這兩個 cookie 是讓查詢結果的 status 欄位有值的關鍵，少了它們 LeetCode 仍會回 200，
          但每題的 status 都是 null，篩不出已 AC 的題目。
        - 兩者都會過期，過期時得重新登入取得。

    Args:
        csrf_token: 瀏覽器登入後取得的 csrf token。
        session: 瀏覽器登入後取得的 LEETCODE_SESSION cookie。
        username: LeetCode 帳號名稱，寫入 User-Agent。

    Returns:
        可直接帶入 requests 的 headers dict。
    """
    return {
        "Content-Type": "application/json",
        "Cookie": f"LEETCODE_SESSION={session}; csrftoken={csrf_token}",
        "x-csrftoken": csrf_token,
        "Referer": "https://leetcode.com",
        "User-Agent": username,
    }


def _post_graphql(headers: dict, json_payload: dict, attempts: int = 3) -> dict:
    """對 LeetCode 的 GraphQL endpoint 送出一次查詢，收到 429 時重試。

    依傳入的 payload 送出查詢，收到 429 就等 300 秒再試，取得 200 後解析回應內容。

    Note:
        - 重試只針對 429，連線層錯誤、其他非 2xx 與 JSON 解析失敗都是第一次就往外拋，不再重試。
        - GraphQL 的查詢語句寫錯時 HTTP 狀態仍是 200，錯誤訊息放在回應內容的 errors 欄位裡，
          因此取得 200 後還要再檢查一次，否則會把錯誤回應當成正常結果往下傳。
        - 重試期間以阻塞方式等待，三次都遇到 429 時這支函式會佔住將近 10 分鐘。

    Args:
        headers: 請求 headers。
        json_payload: 含 query 與 variables 的 GraphQL 請求內容。
        attempts: 最多嘗試次數，預設 3。

    Returns:
        解析後的 GraphQL 回應字典，結構依查詢語句而定。

    Raises:
        Exception: 用盡嘗試次數仍未取得 200，或回應內容帶有 GraphQL errors 時拋出。
        requests.HTTPError: 回應為 429 以外的非 2xx 時拋出。
        requests.ConnectionError: 連線失敗或中斷時拋出。
        requests.Timeout: 請求逾時時拋出。
        ValueError: 回應內容不是合法 JSON 時拋出。
    """
    for i in range(attempts):
        logger.info(f"Requesting graphQL API at attempt No. {i + 1}/{attempts}....")
        try:
            resp = requests.post(LEETCODE_GRAPHQL_URL, headers=headers, json=json_payload, timeout=30)
            if resp.status_code == 429:
                logger.warning(f"Rate limit reached，wait for 300 seconds before retrying at attempt No. {i + 2}")
                time.sleep(300)
                continue
            elif resp.status_code == 200:
                logger.info("Successfully requested leetcode graphQL.")

            #  HTTP 4xx/5xx（例如：409，排除403&429這種rate limit）
            resp.raise_for_status()

            # .json() 移進 try，parse 錯誤才接得到（在 else 區塊會漏接）
            data = resp.json()

        # 以下各桶各記不同業務短訊息、皆不放 exc_info、純 raise，交給最外層印一次 traceback
        except requests.ConnectionError as e:
            logger.error(f"Network error at attempt No. {i + 1}/{attempts}: {e}")
            raise
        except requests.Timeout as e:
            logger.error(f"Network error at attempt No. {i + 1}/{attempts}: {e}")
            raise
        except requests.HTTPError as e:
            logger.error(f"GraphQL HTTP error at attempt No. {i + 1}/{attempts}, status {e.response.status_code}")
            raise
        except ValueError:  # ValueError 已涵蓋 json.JSONDecodeError
            logger.error(f"Malformed JSON from GraphQL at attempt No. {i + 1}/{attempts}")
            raise
        else:
            # 處理非網路層的錯誤：可能是 Query 敘述不當導致 status code 是200但 reponse body 出現 errors key
            if "errors" in data:
                logger.error(f"GraphQL responsed error messages: {data['errors'][0]['message']}")
                raise Exception(f"GraphQL responsed error: {data['errors']}")

            logger.info("Completed decoding the response from GraphQL.")
            return data

    # critical + exc_info 留給最外層 run_task03_leetcode，這裡只記短訊息後拋
    logger.error(f"All {i + 1} attempts failed for GraphQL request. Stop the tasks.")
    raise Exception(f"All {i + 1} attempts failed for GraphQL request.")


def fetch_solved_problem_stats(headers: dict, username: str) -> list[dict]:
    """以 userProblemsSolved 查詢抓取各難度的解題數統計。

    送出查詢後，只取回應中的 acSubmissionNum 一段。

    Note:
        - 查詢語句同時要了題庫總題數與擊敗百分比，但這裡只取各難度的 AC 題數，
          其餘欄位取回後不使用；日後若要用到，改動的是取值那一行而不是查詢語句。

    Args:
        headers: 請求 headers。
        username: LeetCode 帳號名稱。

    Returns:
        各難度的 AC 題數統計清單，每筆含 difficulty 與 count；
        清單第一筆是不分難度的合計，其餘依難度分列。

    Raises:
        KeyError: 回應缺少 data 或其下的統計欄位時拋出。
        TypeError: 帳號名稱查無此人導致 matchedUser 為 null 時拋出。
        Exception: 查詢失敗時，由 _post_graphql 拋出的例外一律原樣往外拋。
    """
    query = """
            query userProblemsSolved($username: String!) {
                    allQuestionsCount {
                        difficulty
                        count
                        }
                        matchedUser(username: $username) {
                            problemsSolvedBeatsStats {
                                difficulty
                                percentage
                                }
                        submitStatsGlobal {
                            acSubmissionNum {
                                difficulty
                                count
                                    }
                                }
                            }
                        }
            """
    payload = {"query": query, "variables": {"username": username}}

    data = _post_graphql(headers, payload)
    solved_problem_stats = data["data"]["matchedUser"]["submitStatsGlobal"]["acSubmissionNum"]
    logger.success(f"Successfully fetched problemsSolvedBeatsStats：{solved_problem_stats}")
    return solved_problem_stats


def fetch_solved_problems_features(headers: dict) -> list[dict]:
    """以 problemsetQuestionList 查詢抓出 status 為 AC 的題目特徵。

    以 status 為 AC 作為篩選條件送出查詢，取回每題的題號、題名、題型標籤與難易度。

    Note:
        - 這支函式只送一次請求、上限 100 題，沒有分頁，因此已解題數超過 100 時只會拿到前 100 題，
          統計會少算。
        - 題目總數為 null 時代表查詢語句或 cookie 有問題，此時回空清單而不是往外拋，
          讓呼叫端的 build_leetcode_summary_partial 以「特徵清單為空但統計顯示有解題」判定上游不一致。
        - 總數為 0 且清單也為空時只記 warning 提示檢查 cookie，因為真的一題都沒解也是同樣的結果，
          兩者從回應上無法區分。

    Args:
        headers: 請求 headers。

    Returns:
        已 AC 題目的特徵字典清單，每筆含 frontendQuestionId、title、topicTags 與 difficulty；
        查無題目總數時為空清單。

    Raises:
        KeyError: 回應缺少 data 或 problemsetQuestionList 欄位時拋出。
        Exception: 查詢失敗時，由 _post_graphql 拋出的例外一律原樣往外拋。
    """
    query = """
        query problemsetQuestionList(
            $categorySlug: String,
            $limit: Int,
            $skip: Int,
            $filters: QuestionListFilterInput) {
                problemsetQuestionList: questionList(
                    categorySlug: $categorySlug
                    limit: $limit
                    skip: $skip
                    filters: $filters) {
                        total: totalNum
                        questions: data {
                            acRate
                            difficulty
                            freqBar
                            frontendQuestionId: questionFrontendId
                            isFavor
                            paidOnly: isPaidOnly
                            status
                            title
                            titleSlug
                            topicTags {
                                name
                                id
                                slug
                            }
                            hasSolution
                            hasVideoSolution
                        }
                    }
        }
        """

    # Variables
    variables = {"limit": 100, "skip": 0, "categorySlug": "", "filters": {"status": "AC"}}

    payload = {"query": query, "variables": variables}

    data = _post_graphql(headers, payload)
    problem_list = data["data"]["problemsetQuestionList"]

    ac_problems_num = problem_list.get("total", None)
    if ac_problems_num is None:
        logger.error("Cannot find solved problems, please check the query statements or cookies")
        return []

    logger.info(
        f"There are {ac_problems_num} problems solved on LeetCode. Starting to fetch the features of each problems."
    )

    ac_problem_features = problem_list.get("questions", [])

    if ac_problems_num == 0 and len(ac_problem_features) == 0:
        logger.warning("Please check if COOKIES expired, and refresh it if does.")
    else:
        logger.success("Successfully fetch the features of all solved problems.")
    return ac_problem_features


def _login_and_get_csrf(account, password):
    """以帳號密碼登入 LeetCode，取得登入前後的 csrf token 與 session cookie。

    先拜訪首頁取得初始 csrf token，帶著它送出登入請求，登入成功後 session 會自動更新所有 cookie。

    Note:
        - 這支函式尚未完成也還沒被任何流程呼叫，保留是為了日後自動刷新 cookie，
          免去每次過期都要手動從瀏覽器複製貼進環境變數。
        - 目前登入結果只用 print 輸出、未接 logger，也沒有檢查登入是否真的成功，
          接進正式流程前這兩點都要補。

    Args:
        account: LeetCode 登入帳號。
        password: LeetCode 登入密碼。

    Returns:
        三個值組成的 tuple，依序是登入前的 csrf token、登入後的 csrf token 與 LEETCODE_SESSION cookie。
    """
    session = requests.Session()

    # Step 1：取得初始 csrftoken
    session.get("https://leetcode.com")
    csrf_token = session.cookies.get("CSRF_TOKEN")
    leetcode_session = session.cookies.get("LEETCODE_SESSION")

    # Step 2：用 csrftoken 登入
    login_resp = session.post(
        "https://leetcode.com/accounts/login/",
        json={
            "login": account,
            "password": password,
            "csrfmiddlewaretoken": csrf_token,
        },
        headers={
            "Referer": "https://leetcode.com",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "x-csrftoken": csrf_token,
        },
    )
    print(login_resp.status_code)

    # Step 3：登入成功後，session 會自動更新所有 cookies
    new_csrf = session.cookies.get("CSRF_TOKEN")
    leetcode_session = session.cookies.get("LEETCODE_SESSION")
    return csrf_token, new_csrf, leetcode_session
