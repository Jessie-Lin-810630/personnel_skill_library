import os

import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from pymongo import MongoClient
from pymongo.database import Database

load_dotenv()


def get_db():
    mongo_uri = os.getenv("MONGO_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([mongo_uri, db_name]):
        logger.error("請確認 .env 已設定 MONGO_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 .env 已設定 MONGO_URI / MONGO_DB_NAME")

    client = MongoClient(mongo_uri)
    return client[db_name]


def get_db_atlas() -> Database:
    """連線 MongoDB Atlas，回傳指定資料庫物件。

    從環境變數讀取 MONGO_ALTAS_URI 與 MONGO_DB_NAME 建立連線，
    為 agent / chat_history / vector_search 等線上查詢的資料來源。

    Returns:
        pymongo Database 物件（對應 MONGO_DB_NAME 指定的資料庫）。

    Raises:
        EnvironmentError: 缺少 MONGO_ALTAS_URI 或 MONGO_DB_NAME 時拋出。
    """
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([mongo_uri, db_name]):
        logger.error("請確認 .env 或 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 .env 或 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")

    client = MongoClient(mongo_uri)
    return client[db_name]


def get_radar_summary_df(db, collection: str) -> pd.DataFrame:
    """取得每張雷達圖最新的軸向標籤、軸向刻度的資料，並轉成 pandas dataframe。"""
    coll = db[collection]
    curr_summary = list(
        coll.aggregate(
            [
                {"$group": {"_id": "$snapshot_date", "docs": {"$push": "$$ROOT"}}},
                {"$sort": {"_id": -1}},
                {"$limit": 1},
                {"$unwind": "$docs"},
                {"$replaceRoot": {"newRoot": "$docs"}},
                {"$project": {"_id": 0, "雷達圖名稱": 1, "snapshot_date": 1, "雷達軸": 1, "level": 1}},
            ]
        )
    )  # aggregare is CommandCursor , use list() to convert to python list

    curr_summary_df = pd.DataFrame(curr_summary)
    return curr_summary_df


def get_a_radar_detail(db, collection: str) -> pd.DataFrame:
    coll = db[collection]
    data = coll.find({}, {"_id": 0, "雷達軸": 1, "經手任務": 1})

    radar_detail_df = pd.DataFrame(data)
    return radar_detail_df


def get_obsidian_kpi(db, collection: str = "obsidian_summary") -> tuple:
    #     # —— KPI ——
    # obsidian_total = 36
    # obsidian_delta = "+6"
    coll = db[collection]
    data = coll.find({}, {"_id": 0}).sort({"snapshot_date": -1}).limit(2)
    df = pd.DataFrame(data)
    if df.empty:
        logger.warning(f"{collection} not found!")
        return 0, 0, {}, None

    curr_total = df["total_notes"].iloc[0]
    if len(df) > 1:
        note_delta = df["total_notes"].iloc[0] - df["total_notes"].iloc[1]  # int
    else:
        note_delta = df["total_notes"].iloc[0]  # int
    topic_counts = df["by_topic"].iloc[0]  # dict
    snapshot_date = df["snapshot_date"].iloc[0]  # date
    return curr_total, note_delta, topic_counts, snapshot_date


def get_github_kpi(db, collection: str = "github_summary") -> tuple:
    # github_total = 15
    # github_delta = "+3 repos"
    coll = db[collection]
    data = coll.find({}, {"_id": 0}).sort({"snapshot_date": -1}).limit(2)
    df = pd.DataFrame(data)
    if df.empty:
        return 0, 0, None
    curr_total = df["total_repos"].iloc[0]  # int
    if len(df) > 1:
        repo_delta = df["total_repos"].iloc[0] - df["total_repos"].iloc[1]  # int
    else:
        repo_delta = df["total_repos"].iloc[0]  # int
    snapshot_date = df["snapshot_date"].iloc[0]  # date
    return curr_total, repo_delta, snapshot_date


def get_github_detail(db, collection: str = "github_repos") -> list[dict]:
    coll = db[collection]
    data = coll.find(
        {},
        {
            "_id": 0,
            "repo_name": 1,
            "commit_counts": 1,
            "description": 1,
            "language": 1,
            "pushed_at": 1,
            "readme_url": 1,
            "fetched_at": 1,
        },
    ).sort({"pushed_at": -1})
    return list(data)


def get_problem_kpi_donut(db, collection: str = "ccClub&leetcode_summary") -> dict:
    """取得刷題三相 donut 所需的 KPI 與環比變化量。

    範例回傳值：
        leetcode_sql = 156
        leetcode_python = 203
        ccclub_total = 204
        leetcode_sql_delta = "+12"
        leetcode_python_delta = "+24"
    """
    coll = db[collection]
    data = list(coll.find({}, {"_id": 0}).sort({"snapshot_date": -1}).limit(2))
    if not data:
        return {
            "leetcode_sql": 0,
            "leetcode_python": 0,
            "leetcode_sql_delta": 0,
            "leetcode_python_delta": 0,
            "ccclub_total": 0,
            "snapshot_date": 0,
        }

    leetcode_total_curr = data[0].get("totalSolvedProblemsOnLeetcode", 0)
    ccclub_total_curr = data[0].get("totalSolvedProblemsOnCCclub", 0)
    leetcode_topics_curr = data[0].get("topicsPercentOnLeetcode", {})
    leetcode_sql_curr = int(leetcode_topics_curr.get("Database", 0) / 100 * leetcode_total_curr)
    leetcode_python_curr = leetcode_total_curr - leetcode_sql_curr

    if len(data) > 1:
        leetcode_total_prev = data[1].get("totalSolvedProblemsOnLeetcode", 0)
        leetcode_topics_prev = data[1].get("topicsPercentOnLeetcode", {})
        leetcode_sql_delta = leetcode_sql_curr - int(
            leetcode_topics_prev.get("Database", 0) / 100 * leetcode_total_prev
        )

        leetcode_python_delta = leetcode_python_curr - int(
            (100 - leetcode_topics_prev.get("Database", 0)) / 100 * leetcode_total_prev
        )
        return {
            "leetcode_sql": leetcode_sql_curr,
            "leetcode_python": leetcode_python_curr,
            "leetcode_sql_delta": leetcode_sql_delta,
            "leetcode_python_delta": leetcode_python_delta,
            "ccclub_total": ccclub_total_curr,
            "snapshot_date": data[0]["snapshot_date"],
        }
    else:
        return {
            "leetcode_sql": leetcode_sql_curr,
            "leetcode_python": leetcode_python_curr,
            "leetcode_sql_delta": leetcode_sql_curr,
            "leetcode_python_delta": leetcode_python_curr,
            "ccclub_total": ccclub_total_curr,
            "snapshot_date": data[0]["snapshot_date"],
        }


def get_onenote_versioned_pages(db) -> list[dict]:
    """查詢 Collection onenote_note_metadata，回傳一篇筆記「目前哪些版本可審閱」。

    同一頁筆記的各版本坐落在不同資料列，dt 欄位代表版本好，以 (page_id, dt) 為主鍵鎖定筆記版本。
    以 aggregation 做兩層篩選，讓前端只看到需要審閱的版本：
    - 濾掉 review_result=rejected 的版本（已退件，不再出現）。
    - 每個 page_id 算出 lastArchivedAt = max(dateTrunc(archived_at, day))，只保留 dt≥最後歸檔日
      的版本（尚無歸檔時全留）；使歸檔後的新內容（新 dt）能重新進入審閱，舊版自動退場。

    Args:
        db: pymongo Database 物件。

    Returns:
        list[dict]: 可審閱的 (page_id, dt) 版本，依 html_downloaded_at 由新到舊排序。
    """
    coll = db["onenote_note_metadata"]
    pipeline = [
        {"$match": {"review_result": {"$ne": "rejected"}}},
        {"$addFields": {"dt_n": {"$convert": {"input": "$dt", "to": "date", "onError": None, "onNull": None}}}},
        {
            "$setWindowFields": {
                "partitionBy": "$page_id",
                "sortBy": {"archived_at": 1},
                "output": {
                    "lastArchivedAt": {
                        "$max": {"$dateTrunc": {"date": "$archived_at", "unit": "day"}},
                        "window": {"documents": ["unbounded", "unbounded"]},
                    }
                },
            }
        },
        {
            "$match": {
                "$expr": {
                    "$or": [
                        {"$eq": ["$lastArchivedAt", None]},
                        {"$gte": ["$dt_n", "$lastArchivedAt"]},
                    ]
                }
            }
        },
        {"$sort": {"html_downloaded_at": -1}},
        {"$project": {"_id": 0, "dt_n": 0, "lastArchivedAt": 0}},
    ]
    return list(coll.aggregate(pipeline))


def get_problem_features(db, collection: str = "ccClub&leetcode_summary") -> dict:
    coll = db[collection]
    data = list(coll.find({}, {"_id": 0}).sort({"snapshot_date": -1}).limit(1))
    if not data:
        return {"LeetCode": {}, "ccClub-Python": {}, "snapshot_date": None}

    return {
        "LeetCode": data[0]["topicsPercentOnLeetcode"],
        "ccClub-Python": data[0]["topicsPercentOnCCclub"],
        "snapshot_date": data[0]["snapshot_date"],
    }
