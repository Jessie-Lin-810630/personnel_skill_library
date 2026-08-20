"""task03 Extract（ccClub）：透過 ccClub Judge REST API 抓取使用者的已解題清單與題目細節。

1. 函式 get_session_and_headers 先拜訪 /api/profile 取得初始 csrftoken，再 POST /api/login
   登入並更新 csrftoken，回傳已認證的 session 與 headers。
2. 函式 _fetch_solved_problem_ids 從 /api/profile 讀出 ACM 與 OI 兩類的已解題 id 清單。
3. 函式 _fetch_problem_detail 逐題呼叫 /api/problem 查詢單題的 tags 與 difficulty。
4. 函式 fetch_all_solved_problems 整合上述步驟，回傳完整的 raw problem list。

Required .env keys:
    CCCLUB_USERNAME   ccClub Judge account name.
    CCCLUB_PASSWORD   ccClub Judge password.
"""

import os
import time

import requests
from loguru import logger
from requests import Session

CCCLUB_BASE_URL = "https://judge.ccclub.io/api"


def get_session_and_headers() -> tuple[Session, dict]:
    """建立並登入 ccClub 的連線工作階段，回傳已認證的 session 與 headers。

    1. 先確認帳號密碼兩個環境變數都有值。
    2. 拜訪 /api/profile 取得初始 csrf token，組成後續請求共用的 headers。
    3. 帶著 headers 登入，成功後再把 headers 裡的 csrf token 換成登入後的值。

    Note:
        - 登入後重新取一次 csrf token，是因為部分站台會在登入時換發新的，沿用舊值會讓後續請求被拒。
        - 帳號密碼在送出請求前就先檢查，避免帶著空值登入而拿到難以判讀的錯誤。
        - 回傳的 session 自己記著登入 cookie，後續請求都必須沿用同一個，換新的等於沒登入。

    Returns:
        已登入的 requests.Session 與帶 csrf token 的 headers 字典組成的 tuple。

    Raises:
        EnvironmentError: 環境變數 CCCLUB_USERNAME 或 CCCLUB_PASSWORD 未設定時拋出。
        requests.HTTPError: 取得初始 token 或登入的回應為非 2xx 時拋出。
        requests.ConnectionError: 連線失敗或中斷時拋出。
        requests.Timeout: 請求逾時時拋出。
    """
    # 確認環境變數可讀取再開始一連串連線準備
    username = os.getenv("CCCLUB_USERNAME")
    password = os.getenv("CCCLUB_PASSWORD")

    if not all([username, password]):
        logger.error("缺乏登入必要資訊，請確認 secret manager 已設定 CCCLUB_USERNAME / CCCLUB_PASSWORD")
        raise EnvironmentError("請確認 secret manager 已設定 CCCLUB_USERNAME / CCCLUB_PASSWORD")

    # 建立 Session，它會自動記錄登入後的 Cookie
    session = requests.Session()
    try:
        # Step 1：先 GET api/profile 取得初始 csrf token
        init_resp = session.get(f"{CCCLUB_BASE_URL}/profile", timeout=30)
        init_resp.raise_for_status()
        csrf_token = session.cookies.get("csrftoken")
        logger.info("Received initial csrftoken.")

        # 將 csrf token 放入 headers
        headers = {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf_token,
            "Referer": "https://judge.ccclub.io",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        }

        # Step 2：拿著含有 csrf token 的 headers 登入，使用POST
        login_resp = session.post(
            f"{CCCLUB_BASE_URL}/login",
            json={"username": username, "password": password},
            headers=headers,
            timeout=30,
        )
        login_resp.raise_for_status()
        logger.info(f"Status of logging: {login_resp.status_code}")
    except requests.ConnectionError as e:
        logger.error(f"Network error during ccClub login. Error msg: {e}")
        raise
    except requests.Timeout as e:
        logger.error(f"Network error during ccClub login. Error msg: {e}")
        raise
    else:
        # Step 3：登入後，有些網頁可能 rotate csrftoken，因此可以勤勞更新 headers
        csrf_token = session.cookies.get("csrftoken")
        headers["X-CSRFToken"] = csrf_token
        logger.success("Successfully loging ccClub judging system.")

        return session, headers


def _fetch_solved_problem_ids(
    session: Session,
    headers: dict,
) -> list[dict]:
    """從 /api/profile 取出 ACM 與 OI 兩類的已解題清單。

    讀取 profile 回應中的兩類解題狀態，各自取出題號與分數，合併成同一份清單並標上題型。

    Note:
        - 題目的標籤與難度不在這個 endpoint，留給 _fetch_problem_detail 逐題補齊。
        - ACM 類的題目通常沒有分數，缺值時填 0。
        - profile 回應沒有 data 欄位時回空清單而不往外拋，此時後續步驟等於沒有題目可處理。

    Args:
        session: 已登入的 requests.Session。
        headers: 帶 csrf token 的 headers。

    Returns:
        已解題清單，每筆含 problem_id、problem_type 與 score；profile 沒有資料時為空清單。

    Raises:
        requests.HTTPError: 回應為非 2xx 時拋出。
        requests.ConnectionError: 連線失敗或中斷時拋出。
        requests.Timeout: 請求逾時時拋出。
        ValueError: 回應內容不是合法 JSON 時拋出。
        KeyError: 某題缺少題號欄位時拋出。
    """
    try:
        logger.info("Start to fetch problem list....")
        profile_resp = session.get(f"{CCCLUB_BASE_URL}/profile", headers=headers, timeout=30)
        profile_resp.raise_for_status()
        # .json() 移進 try，parse 錯誤才接得到
        profile_data = profile_resp.json().get("data", {})
    except requests.ConnectionError as e:
        logger.error(f"Network error when fetching ccClub profile. Error msg: {e}")
        raise
    except requests.Timeout as e:
        logger.error(f"Network error when fetching ccClub profile. Error msg: {e}")
        raise
    except ValueError:  # ValueError 已涵蓋 json.JSONDecodeError
        logger.error("Malformed JSON from ccClub profile")
        raise
    else:
        if not profile_data:
            logger.error("No data found in ccClub profile.")
            return []

    # ==================================================================
    # 正常來說，profile_data的 keys:
    # ['id', 'user', 'real_name', 'acm_problems_status', 'oi_problems_status',
    # #'avatar', 'blog', 'mood', 'github', 'school', 'major', 'language',
    # 'accepted_number', 'total_score', 'submission_number'])
    # ==================================================================
    acm_problems = profile_data.get("acm_problems_status", {}).get("problems", {})
    oi_problems = profile_data.get("oi_problems_status", {}).get("problems", {})

    raw_solved_problems = []

    for v in acm_problems.values():
        raw_solved_problems.append(
            {
                "problem_id": v["_id"],
                "problem_type": "ACM",
                "score": v.get("score", 0),  # ACM 通常無 score，預設 0
            }
        )

    for v in oi_problems.values():
        raw_solved_problems.append(
            {
                "problem_id": v["_id"],
                "problem_type": "OI",
                "score": v.get("score", 0),
            }
        )

    logger.info(
        f"Recevied the list of solved problems on ccClub. "
        f"{len(acm_problems)} ACM + {len(oi_problems)} OI = {len(raw_solved_problems)} problems."
    )
    return raw_solved_problems


def _fetch_problem_detail(
    problem_id: str,
    session: Session,
    headers: dict,
) -> dict:
    """從 /api/problem 取得單題的標籤與難度，難度改寫成與 LeetCode 一致的寫法後回傳。

    取回單題資料後，依難度原始值中的關鍵字對應成 Easy、Med. 或 Hard。

    Note:
        - 難度改寫成與 LeetCode 相同的三個值，是為了讓兩個來源的統計能放在同一張圖上比較；
          對應不到任何關鍵字時原樣保留，缺欄位時填 Unknown，都不會中斷流程。
        - 查無此題會回應 404，這是正常情形，此時回空字典、不視為失敗，
          由 fetch_all_solved_problems 補上預設值。

    Args:
        problem_id: 要查詢的題目 id。
        session: 已登入的 requests.Session。
        headers: 帶 csrf token 的 headers。

    Returns:
        含 topic 與 difficulty 兩個鍵的字典；查無此題時為空字典。

    Raises:
        requests.HTTPError: 回應為 404 以外的非 2xx 時拋出。
        requests.ConnectionError: 連線失敗或中斷時拋出。
        requests.Timeout: 請求逾時時拋出。
        ValueError: 回應內容不是合法 JSON 時拋出。
    """
    try:
        resp = session.get(
            f"{CCCLUB_BASE_URL}/problem",
            params={"problem_id": problem_id},
            headers=headers,
            timeout=30,
        )

        if resp.status_code == 404:
            logger.warning(f"Not found problem_id {problem_id}, skip this")
            return {}

        resp.raise_for_status()
        # .json() 移進 try，parse 錯誤才接得到
        data = resp.json().get("data", {})
    except requests.ConnectionError as e:
        logger.error(f"Network error when fetching problem_id {problem_id}. Error msg: {e}")
        raise
    except requests.Timeout as e:
        logger.error(f"Network error when fetching problem_id {problem_id}. Error msg: {e}")
        raise
    except ValueError:  # ValueError 已涵蓋 json.JSONDecodeError
        logger.error(f"Malformed JSON for problem_id {problem_id}")
        raise

    # difficulty 標準化，與 leetcode 標示一致
    raw_difficulty = data.get("difficulty", "Unknown")
    if "mid" in raw_difficulty.lower():
        difficulty = "Med."
    elif "high" in raw_difficulty.lower():
        difficulty = "Hard"
    elif "easy" in raw_difficulty.lower() or "low" in raw_difficulty.lower():
        difficulty = "Easy"
    else:
        difficulty = raw_difficulty

    return {
        "topic": data.get("tags", ["Unknown"]),
        "difficulty": difficulty,
    }


def fetch_all_solved_problems(
    session: Session,
    headers: dict,
    throttle_sec: float = 0.3,
) -> list[dict]:
    """取得已解題清單，並逐題補上標籤與難度。

    先取回已解題清單，再對每一題各查一次細節，把標籤與難度補進原本那筆資料。

    Note:
        - 這是就地修改，補上的欄位直接寫進 _fetch_solved_problem_ids 回傳的那些字典。
        - 查不到細節的題目填 Unknown 而不是略過，因為題目本身確實已解，
          只是細節查不到，略過會讓總題數少算。
        - 每題之間刻意停一小段時間，避免短時間內對 ccClub 送出大量請求；
          題數多時整輪耗時主要花在這裡。

    Args:
        session: 已登入的 requests.Session。
        headers: 帶 csrf token 的 headers。
        throttle_sec: 每次請求之間的間隔秒數，預設 0.3。

    Returns:
        補齊細節的已解題清單，每筆含 problem_id、problem_type、score、topic 與 difficulty；
        這是就地修改後的同一份清單，不是另一份複本。

    Raises:
        requests.HTTPError: 取清單或查任一題細節的回應為非 2xx 時拋出。
        requests.ConnectionError: 連線失敗或中斷時拋出。
        requests.Timeout: 請求逾時時拋出。
        ValueError: 回應內容不是合法 JSON 時拋出。
    """
    raw_solved_problems = _fetch_solved_problem_ids(session, headers)
    total = len(raw_solved_problems)

    for i, problem in enumerate(raw_solved_problems, start=1):
        problem_id = problem["problem_id"]
        logger.info(f"Fetching the detail of No. {i} / {total} solved problems. {problem_id=}")

        detail = _fetch_problem_detail(problem_id, session, headers)

        # 找不到 detail 或是 detail 是空字典時，給予預設值，不中斷整體流程
        problem["topic"] = detail.get("topic", ["Unknown"])
        problem["difficulty"] = detail.get("difficulty", "Unknown")

        # 每次請求間隔 0.3 秒，避免對 ccClub server 造成太大壓力。
        time.sleep(throttle_sec)

    logger.success(f"Successfully fetching all {len(raw_solved_problems)} solved problems information on ccClub.")
    return raw_solved_problems
