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
    """通用 GraphQL POST，內建最多 attempts 次重試。

    依傳入的 json_payload 送出查詢，遇 429 就等 300 秒重試，回應 body 帶 errors 時拋例外。

    Args:
        headers: 請求 headers。
        json_payload: 含 query 與 variables 的 GraphQL 請求 body。
        attempts: 最多重試次數，預設 3。

    Returns:
        decode 後的 GraphQL 回應 dict。

    Raises:
        Exception: 所有嘗試皆失敗、或回應帶 GraphQL errors 時拋出。
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
    """以 userProblemsSolved 查詢抓取解題進度統計 problemsSolvedBeatsStats。

    Args:
        headers: 請求 headers。
        username: LeetCode 帳號名稱。

    Returns:
        各難度的 AC submission 統計清單。
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
    """以 problemsetQuestionList 查詢抓出所有 status 為 AC 的題目特徵。

    以 filters status=AC 分頁抓取，回傳每題的題號、題名、題型與難易度；
    查無資料時回傳空清單並提示檢查 cookies。

    Args:
        headers: 請求 headers。

    Returns:
        已 AC 題目的特徵 dict 清單。
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
    """登入 LeetCode 取得 csrf token（尚未完成，保留供未來刷新 csrf 用）。"""
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
