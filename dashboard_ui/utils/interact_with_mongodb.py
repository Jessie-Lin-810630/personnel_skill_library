import pandas as pd
from pymongo import MongoClient, UpdateOne
from pymongo.collection import Collection
from loguru import logger
import os
from dotenv import load_dotenv


load_dotenv()


def get_db():
    mongo_uri = os.getenv("MONGO_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([mongo_uri, db_name]):
        logger.error("請確認 .env 已設定 MONGO_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 .env 已設定 MONGO_URI / MONGO_DB_NAME")

    client = MongoClient(mongo_uri)
    return client[db_name]


def get_radar_summary_df(db, collection: str) -> pd.DataFrame:
    """取得每張雷達圖最新的軸向標籤、軸向刻度的資料，並轉成 pandas dataframe。"""
    coll = db[collection]
    curr_summary = list(coll.aggregate([{"$group": {"_id": "$snapshot_date",
                                                    "docs": {"$push": "$$ROOT"}}
                                         },
                                        {"$sort": {"_id": -1}},
                                        {"$limit": 1},
                                        {"$unwind": "$docs"},
                                        {"$replaceRoot": {"newRoot": "$docs"}
                                         },
                                        {"$project": {"_id": 0,
                                                      "雷達圖名稱": 1,
                                                      "snapshot_date": 1,
                                                      "雷達軸": 1,
                                                      "level": 1}
                                         }
                                        ])
                        )  # aggregare is CommandCursor , use list() to convert to python list

    curr_summary_df = pd.DataFrame(curr_summary)
    return curr_summary_df


def get_a_radar_detail(db, collection: str) -> pd.DataFrame:
    coll = db[collection]
    data = coll.find({}, {"_id": 0,
                          "雷達軸": 1,
                          "經手任務": 1}
                     )

    radar_detail_df = pd.DataFrame(data)
    return radar_detail_df


def get_obsidian_kpi(db, collection: str = "obsidian_summary") -> tuple:
    #     # —— KPI ——
    # obsidian_total = 36
    # obsidian_delta = "+6"
    coll = db[collection]
    data = coll.find({},
                     {"_id": 0}
                     ).sort({"snapshot_date": -1}
                            ).limit(2)
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
    data = coll.find({},
                     {"_id": 0}
                     ).sort({"snapshot_date": -1}
                            ).limit(2)
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
    data = coll.find({},
                     {"_id": 0,
                      "repo_name": 1,
                      "commit_counts": 1,
                      "description": 1,
                      "language": 1,
                      "pushed_at": 1,
                      "readme_url": 1,
                      "fetched_at": 1}
                     ).sort({"pushed_at": -1})
    return list(data)


def get_problem_kpi_donut(db, collection: str = "ccClub&leetcode_summary") -> dict:
    """
    leetcode_sql = 156
    leetcode_python = 203
    ccclub_total= 204
    leetcode_sql_delta = "+12"
    leetcode_python_delta = "+24"
    """
    coll = db[collection]
    data = list(coll.find({},
                          {"_id": 0}
                          ).sort({"snapshot_date": -1}
                                 ).limit(2))
    if not data:
        return {"leetcode_sql": 0,
                "leetcode_python": 0,
                "leetcode_sql_delta": 0,
                "leetcode_python_delta": 0,
                "ccclub_total": 0,
                "snapshot_date": 0}

    leetcode_total_curr = data[0].get("totalSolvedProblemsOnLeetcode", 0)
    ccclub_total_curr = data[0].get("totalSolvedProblemsOnCCclub", 0)
    leetcode_topics_curr = data[0].get("topicsPercentOnLeetcode", {})
    leetcode_sql_curr = int(leetcode_topics_curr.get("Database", 0) / 100 * leetcode_total_curr)
    leetcode_python_curr = leetcode_total_curr - leetcode_sql_curr

    if len(data) > 1:
        leetcode_total_prev = data[1].get("totalSolvedProblemsOnLeetcode", 0)
        leetcode_topics_prev = data[1].get("topicsPercentOnLeetcode", {})
        leetcode_sql_delta = leetcode_sql_curr - int(leetcode_topics_prev.get("Database", 0)/100 *
                                                     leetcode_total_prev
                                                     )

        leetcode_python_delta = leetcode_python_curr - int((100 - leetcode_topics_prev.get("Database", 0)
                                                            ) / 100 * leetcode_total_prev
                                                           )
        return {"leetcode_sql": leetcode_sql_curr,
                "leetcode_python": leetcode_python_curr,
                "leetcode_sql_delta": leetcode_sql_delta,
                "leetcode_python_delta": leetcode_python_delta,
                "ccclub_total": ccclub_total_curr,
                "snapshot_date": data[0]["snapshot_date"]}
    else:
        return {"leetcode_sql": leetcode_sql_curr,
                "leetcode_python": leetcode_python_curr,
                "leetcode_sql_delta": leetcode_sql_curr,
                "leetcode_python_delta": leetcode_python_curr,
                "ccclub_total": ccclub_total_curr,
                "snapshot_date": data[0]["snapshot_date"]}


def get_problem_features(db, collection: str = "ccClub&leetcode_summary") -> dict:
    coll = db[collection]
    data = list(coll.find({},
                          {"_id": 0}
                          ).sort({"snapshot_date": -1}
                                 ).limit(1))
    if not data:
        return {"LeetCode": {}, "ccClub-Python": {}, "snapshot_date": None}

    return {"LeetCode": data[0]["topicsPercentOnLeetcode"],
            "ccClub-Python": data[0]["topicsPercentOnCCclub"],
            "snapshot_date": data[0]["snapshot_date"]}
