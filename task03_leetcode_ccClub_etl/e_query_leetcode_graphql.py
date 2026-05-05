from requests import session
import os
import time
import requests
from loguru import logger
from dotenv import load_dotenv


LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql/"

"""
程式架構：
Extract：透過 LeetCode GraphQL API 抓取用戶已解題清單與統計結果。
Endpoint 只有這一個，從GraphQL API查詢時使用 Query: 
(1) problemsetQuestionList: 抓所有解題清單特徵，並用 status=="AC" 以過濾已成功解題的題目
    - 需要登入 cookies (包含 CRSF TOKEN 與 LEETCODE_SESSION) 才能讓 status 欄位有值
    - 需要分頁（每次最多 limit=100）
    - 回傳題目編號、題目名稱、題型特徵、難易度
(2) serProblemsSolved: 抓取解題進度統計結果 (解題題數百分比、難度百分比)

函式設計：
- _get_headers(csrf_token, session, username)：產生 headers，session 與 crsf_token為關鍵。
- _post_graphql()：根據傳入的查詢語句(JSON 格式) 與 headers，執行請求，並捕捉例外。
- fetch_solved_problem_stats(): 組合graphQL 查詢語句(JSON 格式)後調用_post_graphql()。查詢解題統計結果。
- fetch_solved_problems_features(): 組合graphQL 查詢語句(JSON 格式)後調用_post_graphql()。查詢解題題型特徵。
"""


def _get_headers(csrf_token: str, session: str, username: str) -> dict:
    """
        事先用瀏覽器登入後，取得 csrf_token 與 leetcode_session，以此組合出 headers。
    """
    return {
        "Content-Type": "application/json",
        "Cookie": f"LEETCODE_SESSION={session}; csrftoken={csrf_token}",
        "x-csrftoken": csrf_token,
        "Referer": "https://leetcode.com",
        "User-Agent": username,
    }


def _post_graphql(headers: dict, json_payload: dict, attempts: int = 3) -> dict:
    """
        通用 GraphQL POST，內建重試機制 (最多3次)。
        根據傳入參數 json_payload 的 Query 敘述 ，執行 POST。
    """
    for i in range(attempts):
        logger.info(f"Requesting graphQL API at attempt No. {i + 1}/{attempts}....")
        try:
            resp = requests.post(LEETCODE_GRAPHQL_URL,
                                 headers=headers,
                                 json=json_payload,
                                 timeout=30
                                 )
            if resp.status_code == 429:
                logger.warning(
                    f"Rate limit reached，wait for 300 seconds before retrying at attempt No. {i+2}")
                time.sleep(300)
                continue
            elif resp.status_code == 200:
                logger.info(f"Successfully requested leetcode graphQL.")

            #  HTTP 4xx/5xx（例如：409，排除403&429這種rate limit）
            resp.raise_for_status()

        except requests.ConnectionError as e:
            logger.error(f"Network error at attempt No. {i}/{attempts}: {e}")
            raise
        else:
            data = resp.json()

            # 處理非網路層的錯誤：可能是 Query 敘述不當導致 status code 是200但 reponse body 出現 errors key
            if "errors" in data:
                logger.error(f"GraphQL responsed error messages: {data['errors'][0]['message']}")
                raise Exception(f"GraphQL responsed error: {data['errors']}")

            logger.info(f"Completed decoding the response from GraphQL.")
            return data

    logger.critical(f"All {i+1} attempts failed for GraphQL request. Stop the tasks.")
    raise Exception(f"All {i+1} attempts failed for GraphQL request.")


def fetch_solved_problem_stats(headers: dict, username: str) -> list[dict]:
    """
        用 userProblemsSolved Query 查詢 problemsSolvedBeatsStats。
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
    payload = {"query": query,
               "variables": {"username": username}
               }

    data = _post_graphql(headers, payload)
    solved_problem_stats = data["data"]["matchedUser"]["submitStatsGlobal"]["acSubmissionNum"]
    logger.success(f"Successfully fetched problemsSolvedBeatsStats：{solved_problem_stats}")
    return solved_problem_stats


def fetch_solved_problems_features(headers: dict) -> list[dict]:
    """
        用 problemsetQuestionList Query 抓出所有 status=="AC" 的題目。
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
    variables = {"limit": 100,
                 "skip": 0,
                 "categorySlug": "",
                 "filters": {"status": "AC"}
                 }

    payload = {"query": query,
               "variables": variables
               }

    data = _post_graphql(headers, payload)
    problem_list = data["data"]["problemsetQuestionList"]

    ac_problems_num = problem_list.get("total", None)
    if ac_problems_num is None:
        logger.error(f"Cannot find solved problems, please check the query statements or cookies")
        return []

    logger.info(f"There are {ac_problems_num} problems solved on LeetCode. "
                f"Starting to fetch the features of each problems.")

    ac_problem_features = problem_list.get("questions", [])

    if ac_problems_num == 0 and len(ac_problem_features) == 0:
        logger.warning(f"Please check if COOKIES expired, and refresh it if does.")
    else:
        logger.success(f"Successfully fetch the features of all solved problems.")
    return ac_problem_features


def _login_and_get_csrf(account, password):
    """尚未完成、但保留用於刷新csrf"""
    session = requests.Session()

    # Step 1：取得初始 csrftoken
    session.get("https://leetcode.com")
    csrf_token = session.cookies.get("CSRF_TOKEN")
    leetcode_session = session.cookies.get("LEETCODE_SESSION")

    # Step 2：用 csrftoken 登入
    login_resp = session.post("https://leetcode.com/accounts/login/",
                              json={"login": account,
                                    "password": password,
                                    "csrfmiddlewaretoken": csrf_token,
                                    },
                              headers={"Referer": "https://leetcode.com",
                                       "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
                                       "Content-Type": "application/json",
                                       "x-csrftoken": csrf_token,
                                       }
                              )
    print(login_resp.status_code)

    # Step 3：登入成功後，session 會自動更新所有 cookies
    new_csrf = session.cookies.get("CSRF_TOKEN")
    leetcode_session = session.cookies.get("LEETCODE_SESSION")
    return csrf_token, new_csrf, leetcode_session


if __name__ == "__main__":
    # 測試區
    # 拼出 headers
    load_dotenv()
    csrf_token = os.getenv("CSRF_TOKEN")
    leetcode_session = os.getenv("LEETCODE_SESSION")
    username = os.getenv("LEETCODE_USERNAME")
    headers = _get_headers(csrf_token, leetcode_session, username)

    print(fetch_solved_problem_stats(headers, username))
    print(fetch_solved_problems_features(headers))
