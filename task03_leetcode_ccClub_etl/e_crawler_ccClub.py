import os
import time

import requests
from dotenv import load_dotenv
from loguru import logger
from requests import Session

"""
程式架構：
Extract：透過 ccClub Judge REST API 抓取已解題清單。拜訪四次 Endpoints：
(1) GET /api/profile          : 取得初始 csrftoken
(2) POST /api/login           : 登入，session 自動記錄 cookie
(3) GET /api/profile          : 取得個人 acm_problems_status & oi_problems_status
(4) GET /api/problem          : 逐題查詢 tags & difficulty

函式設計：
- _get_session_and_headers()  : 建立 session、登入、回傳 (session, headers)
- _fetch_solved_problem_ids()  : 從 profile 取得所有已解題的 id 清單 (ACM + OI)
- _fetch_problem_detail()      : 從 problem 查詢單題的 tags & difficulty
- fetch_all_solved_problems() : 整合上方兩支函式，回傳 raw problem list
"""

load_dotenv()

CCCLUB_BASE_URL = "https://judge.ccclub.io/api"


def _get_session_and_headers() -> tuple[Session, dict]:
    """建立 requests.Session，初步拜訪網站取得 csrftoken，然後正式登入，最後再更新 csrftoken。

    回傳已認證的 (session, headers)。
    """
    # 確認環境變數可讀取再開始一連串連線準備
    username = os.getenv("CCCLUB_USERNAME")
    password = os.getenv("CCCLUB_PASSWORD")

    if not all([username, password]):
        logger.error("缺乏登入必要資訊，請確認 .env 或 secret manager 已設定 CCCLUB_USERNAME / CCCLUB_PASSWORD")
        raise EnvironmentError("請確認 .env 或 secret manager 已設定 CCCLUB_USERNAME / CCCLUB_PASSWORD")

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
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            ),
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
        logger.error(f"Some errors happended during logging. Error msg: {e}")
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
    """GET /api/profile 取得 acm_problems_status & oi_problems_status。

    回傳 raw problem list，每筆只含 problem_id、problem_type、score。
    tags & difficulty 需要從另一個endpoint進入，留給 _fetch_problem_detail() 補齊。
    """
    try:
        logger.info("Start to fetch problem list....")
        profile_resp = session.get(f"{CCCLUB_BASE_URL}/profile", headers=headers, timeout=30)
        profile_resp.raise_for_status()
    except requests.ConnectionError as e:
        logger.error(f"Some errors happended during logging. Error msg: {e}")
        raise
    else:
        if profile_resp is None:
            logger.error("No response after logging in.")
            return []

        profile_data = profile_resp.json().get("data", {})
        if profile_data == {}:
            logger.error("No data found.")
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
    """GET /api/problem?problem_id={id} 取得單題的 tags & difficulty。

    difficulty 原始值為 "Low" / "Mid" / "High"，統一標準化後回傳。
    找不到資料回傳空 dict。
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
    except requests.ConnectionError as e:
        logger.error(f"Some errors happended when getting {problem_id}. Error msg: {e}")
        raise
    else:
        if resp is None:
            logger.warning(f"No responses from problem_id {problem_id}, skip this.")
            return {}

    data = resp.json().get("data", {})

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
    """整合 fetch_solved_problem_ids() + fetch_problem_detail()。

    逐題查詢 detail，補齊 topic & difficulty 後回傳完整 raw problem list。

    throttle_sec：每次請求之間的間隔秒數，避免對 ccClub server 造成太大壓力。
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
