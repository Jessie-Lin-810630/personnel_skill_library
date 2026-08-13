"""Dashboard 的 MongoDB 查詢封裝：集中連線建立與各頁所需的 collection 讀取。

1. 函式 get_db_atlas 以 MONGO_ALTAS_URI 建立連線，後者為跨頁共用的 module-level 單例。
2. 其餘查詢函式把各 collection 讀成 Streamlit 頁面直接可用的 DataFrame 或 dict。

Required .env keys:
    MONGO_ALTAS_URI   MongoDB Atlas connection string (used by get_db_atlas singleton).
    MONGO_DB_NAME     Target database name.
"""

import os

import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from pymongo import MongoClient
from pymongo.database import Database

load_dotenv()


_atlas_db: Database | None = None


def get_db_atlas() -> Database:
    """連線 MongoDB Atlas 並回傳目標資料庫物件，全站共用同一份 client。

    連線字串與資料庫名稱都從環境變數讀取，是 agent、chat_history、vector_search 等線上查詢的共同入口。
    MongoClient 本身自帶連線池且為 thread-safe，因此只在首次呼叫時建立、之後重複使用，
    避免各頁反覆建立 client 而耗盡 Atlas 的連線數上限。

    Returns:
        對應 MONGO_DB_NAME 的 pymongo Database 物件。

    Raises:
        EnvironmentError: 環境變數 MONGO_ALTAS_URI 或 MONGO_DB_NAME 未設定時拋出。
    """
    global _atlas_db
    if _atlas_db is not None:
        return _atlas_db

    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([mongo_uri, db_name]):
        logger.error("請確認 .env 或 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 .env 或 secret manager 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")

    _atlas_db = MongoClient(mongo_uri)[db_name]
    return _atlas_db


def get_radar_summary_df(db: Database, collection: str) -> pd.DataFrame:
    """取得每張雷達圖最新一次快照的軸向標籤與軸向刻度。

    先依 snapshot_date 分組並取最新的一組，再攤平回單筆文件，
    只保留繪製雷達圖需要的雷達圖名稱、快照日期、雷達軸與 level 四個欄位。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱。

    Returns:
        含雷達圖名稱、snapshot_date、雷達軸、level 四欄的 DataFrame；無資料時為空 DataFrame。
    """
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


def get_a_radar_detail(db: Database, collection: str) -> pd.DataFrame:
    """取得單一張雷達圖各軸向底下的經手任務明細。

    不限定快照日期，讀出全部文件的雷達軸與經手任務兩欄，供圖表 hover 與任務表格展開使用。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱。

    Returns:
        含雷達軸與經手任務兩欄的 DataFrame；無資料時為空 DataFrame。
    """
    coll = db[collection]
    data = coll.find({}, {"_id": 0, "雷達軸": 1, "經手任務": 1})

    radar_detail_df = pd.DataFrame(data)
    return radar_detail_df


def get_obsidian_kpi(db: Database, collection: str = "obsidian_summary") -> tuple:
    """取得 Obsidian 筆記總數 KPI 與環比變化量，供首頁 KPI 卡片使用。

    依 snapshot_date 由新到舊取兩筆快照，以最新一筆為現值、前一筆為基準算出環比變化量；
    只有一筆快照時，把現值本身視為變化量。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱，預設 obsidian_summary。

    Returns:
        四元組，依序為筆記總數、環比變化量、各主題筆記數的分佈 dict、最新快照日期；
        無資料時回傳 0、0、空 dict 與 None。
    """
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
    topic_counts = df["by_topic_in_archived_notes"].iloc[0]  # dict
    snapshot_date = df["snapshot_date"].iloc[0]  # date
    return curr_total, note_delta, topic_counts, snapshot_date


def get_github_kpi(db: Database, collection: str = "github_summary") -> tuple:
    """取得 GitHub repo 總數 KPI 與環比變化量，供首頁 KPI 卡片使用。

    依 snapshot_date 由新到舊取兩筆快照，以最新一筆為現值、前一筆為基準算出環比變化量；
    只有一筆快照時，把現值本身視為變化量。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱，預設 github_summary。

    Returns:
        三元組，依序為 repo 總數、環比變化量、最新快照日期；無資料時回傳 0、0 與 None。
    """
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


def get_github_detail(db: Database, collection: str = "github_repos") -> list[dict]:
    """取得 GitHub 各 repo 的活動明細，依最後推送時間由新到舊排序。

    只取專案卡片需要的欄位，供首頁的最近專案區塊渲染。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱，預設 github_repos。

    Returns:
        每筆含 repo_name、commit_counts、description、language、pushed_at、readme_url、
        fetched_at 的 dict 清單；無資料時為空 list。
    """
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


def get_problem_kpi_donut(db: Database, collection: str = "ccClub&leetcode_summary") -> dict:
    """取得刷題三相 donut chart 所需的題數 KPI 與環比變化量。

    依 snapshot_date 由新到舊取兩筆快照。LeetCode 未直接記錄 SQL 題數，
    而是以 Database 主題的百分比乘上總題數推算，其餘題數一律歸為 Python 題。
    只有一筆快照時，把現值本身視為變化量。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱，預設 ccClub&leetcode_summary。

    Returns:
        含 leetcode_sql、leetcode_python、leetcode_sql_delta、leetcode_python_delta、
        ccclub_total、snapshot_date 六個鍵的 dict；無資料時各值皆為 0。
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


def get_onenote_versioned_pages(db: Database) -> list[dict]:
    """查詢 onenote_note_metadata，回傳目前還需要人工審閱的筆記版本。

    同一頁筆記的各個版本分別存成獨立資料列，dt 欄位即版本日期，
    page_id 與 dt 兩欄合起來是鎖定單一版本的複合唯一鍵。
    aggregation 做兩層篩選，讓審查頁只看到還需要處理的版本：
    第一層濾掉 status 為 review_closed 的版本，這類版本已退役，含退件與被覆寫兩種情形。
    第二層以 page_id 分組算出最後一次歸檔日期，只保留 dt 不早於該日期的版本，尚未歸檔過的筆記則全數保留。
    如此一來，歸檔之後新抓到的內容會帶著更新的 dt 重新進入審閱，舊版本則自動退場。

    Args:
        db: pymongo Database 物件。

    Returns:
        待審閱的筆記版本文件清單，依 html_downloaded_at 由新到舊排序；無資料時為空 list。
    """
    coll = db["onenote_note_metadata"]
    pipeline = [
        {"$match": {"status": {"$ne": "review_closed"}}},
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


def get_notes_summary_snapshots(db: Database, collection: str = "notes_summary", limit: int = 2) -> list[dict]:
    """取得 notes_summary 最新的幾筆快照，供攝取品質頁的 KPI 卡片與生命週期漏斗使用。

    依 snapshot_date 由新到舊取前幾筆，第一筆是最新快照，第二筆是前一次快照，兩者相減即為 KPI 的環比變化量。
    每筆快照含 total、archived、rejected、embedded 四個計數，以及歸檔與退件筆記各自的標籤分佈。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱，預設 notes_summary。
        limit: 取回的快照筆數，預設 2 筆，即最新一筆加上前一筆。

    Returns:
        依 snapshot_date 由新到舊排序的快照文件清單；無資料時為空 list。
    """
    coll = db[collection]
    data = coll.find({}, {"_id": 0}).sort("snapshot_date", -1).limit(limit)
    return list(data)


def get_onenote_attachment_dismatch(db: Database, collection: str = "onenote_note_metadata") -> list[dict]:
    """彙總 OneNote 各狀態筆記的附件遺失情形，供攝取品質頁的附件遺失量長條圖使用。

    只取 status 為 archived 或 rejected 的筆記，依 status 與 embedded_status 兩欄分組，
    每組回傳含遺失附件的筆記篇數，以及各篇的遺失張數陣列，頁面端再據此堆疊出各遺失張數的筆記篇數。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱，預設 onenote_note_metadata。

    Returns:
        每組含 status、embedded_status、md_cnt_has_dismatched_img 與
        dismatched_img_count 四個欄位的 dict 清單；無資料時為空 list。
    """
    coll = db[collection]
    pipeline = [
        {"$match": {"status": {"$in": ["archived", "rejected"]}}},
        {
            "$group": {
                "_id": {"status": "$status", "embedded_status": "$embedded_status"},
                "md_cnt_has_dismatched_img": {"$sum": {"$cond": ["$md_has_dismatched", 1, 0]}},
                "dismatched_img_count": {"$push": "$dismatched_img_count"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "status": "$_id.status",
                "embedded_status": "$_id.embedded_status",
                "md_cnt_has_dismatched_img": 1,
                "dismatched_img_count": 1,
            }
        },
    ]
    return list(coll.aggregate(pipeline))


def get_enrichment_logs(db: Database, collection: str = "multimodal_llm_enrichment_logs") -> pd.DataFrame:
    """取得 LLM enrichment 的成功紀錄，供 token 累計量與快取命中率圖表使用。

    只取 status 為 success 的紀錄，藉此濾掉 token 欄位為 null 的失敗筆。
    命中快取的紀錄依 schema 定義會把 token 數與延遲時間記為 0。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱，預設 multimodal_llm_enrichment_logs。

    Returns:
        含 timestamp、input_tokens、output_tokens、total_tokens、cache_hit、latency_ms
        六欄的 DataFrame，依 timestamp 由新到舊排序；無資料時為空 DataFrame。
    """
    coll = db[collection]
    cursor = coll.find(
        {"status": {"$in": ["success"]}},
        {
            "_id": 0,
            "timestamp": 1,
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 1,
            "cache_hit": 1,
            "latency_ms": 1,
        },
    ).sort("timestamp", -1)
    return pd.DataFrame(list(cursor))


def get_rag_retrieved_chunks(db: Database, collection: str = "chat_history") -> pd.DataFrame:
    """把 RAG 回應中檢索到的 chunk 攤平成每列一筆，供向量相似度與重排分數的散佈圖使用。

    只取 agent_type 為 rag 且 role 為 model 的紀錄，展開 metadata 裡的 retrieved_chunks 陣列，
    取出每個 chunk 的向量相似度分數與重排分數。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱，預設 chat_history。

    Returns:
        含 session_id、timestamp、file_path、chunk_index、score、rerank_score
        六欄的 DataFrame；無資料時為空 DataFrame。
    """
    coll = db[collection]
    pipeline = [
        {"$match": {"agent_type": "rag", "role": "model", "metadata.retrieved_chunks": {"$exists": True}}},
        {"$project": {"session_id": 1, "timestamp": 1, "chunks": "$metadata.retrieved_chunks"}},
        {"$unwind": "$chunks"},
        {
            "$project": {
                "_id": 0,
                "session_id": 1,
                "timestamp": 1,
                "file_path": "$chunks.file_path",
                "chunk_index": "$chunks.chunk_index",
                "score": "$chunks.score",
                "rerank_score": "$chunks.rerank_score",
            }
        },
    ]
    return pd.DataFrame(list(coll.aggregate(pipeline)))


def get_rag_session_rounds(db: Database, collection: str = "chat_history") -> pd.DataFrame:
    """統計每個 session 的檢索輪數，供輪數分佈圖使用。

    一輪即一則使用者提問，因此以同一個 session 中 role 為 user 的訊息筆數作為輪數。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱，預設 chat_history。

    Returns:
        含 session_id 與 rounds 兩欄的 DataFrame；無資料時為空 DataFrame。
    """
    coll = db[collection]
    pipeline = [
        {"$match": {"agent_type": "rag", "role": "user"}},
        {"$group": {"_id": "$session_id", "rounds": {"$sum": 1}}},
        {"$project": {"_id": 0, "session_id": "$_id", "rounds": 1}},
    ]
    return pd.DataFrame(list(coll.aggregate(pipeline)))


def get_rag_file_retrieval_counts(db: Database, collection: str = "chat_history") -> pd.DataFrame:
    """統計各筆記檔被 RAG 檢索到的次數與最後檢索時間，供冷熱資料 treemap 使用。

    展開 metadata 裡已去重的 note_files 陣列後，依檔名分組計數，
    並把最後檢索時間換算成距今天數。

    Note:
        統計範圍只涵蓋至少被檢索過一次的檔案。從未被檢索的檔案不會出現在 chat_history，
        因此要列出零檢索的檔案需另行與語料庫做 join。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱，預設 chat_history。

    Returns:
        含 file_name、count、last_retrieved、days_since 四欄的 DataFrame，
        依檢索次數由多到少排序；無資料時為空 DataFrame。
    """
    coll = db[collection]
    pipeline = [
        {"$match": {"agent_type": "rag", "role": "model", "metadata.note_files": {"$exists": True}}},
        {"$unwind": "$metadata.note_files"},
        {
            "$group": {
                "_id": "$metadata.note_files",
                "count": {"$sum": 1},
                "last_retrieved": {"$max": "$timestamp"},
            }
        },
        {"$sort": {"count": -1}},
        {"$project": {"_id": 0, "file_name": "$_id", "count": 1, "last_retrieved": 1}},
    ]
    df = pd.DataFrame(list(coll.aggregate(pipeline)))
    if not df.empty:
        last = pd.to_datetime(df["last_retrieved"])
        if last.dt.tz is not None:
            last = last.dt.tz_localize(None)
        df["days_since"] = (pd.Timestamp.now() - last).dt.days
    return df


def get_rag_satisfaction_proxy(db: Database, collection: str = "chat_history", truncate_limit: int = 2000) -> dict:
    """彙總三項用來代理檢索滿意度的指標：重排首名分數中位數、來源檔案發散度與回應截斷率。

    以一次 aggregation 掃過 agent_type 為 rag 且 role 為 model 的紀錄，計算三件事：
    每次回應中重排分數最高那筆的中位數、每次回應引用的筆記檔數平均值，
    以及回應長度達到截斷上限的比例。平均輪數不在此計算，由呼叫端以輪數資料另行補上。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱，預設 chat_history。
        truncate_limit: 回應長度達到多少字元即視為被截斷，預設 2000。

    Returns:
        含 rerank_top1_p50、avg_note_files、truncation_rate、last_date 四個鍵的 dict；
        無資料時三項指標皆為 0，日期顯示為無資料。
    """
    coll = db[collection]
    pipeline = [
        {"$match": {"agent_type": "rag", "role": "model"}},
        {
            "$project": {
                "top1_rerank": {"$arrayElemAt": ["$metadata.retrieved_chunks.rerank_score", 0]},
                "n_files": {"$size": {"$ifNull": ["$metadata.note_files", []]}},
                "is_truncated": {"$gte": [{"$strLenCP": {"$ifNull": ["$content", ""]}}, truncate_limit]},
                "date": {"$dateTrunc": {"date": "$timestamp", "unit": "day"}},
            }
        },
        {
            "$group": {
                "_id": None,
                "top1_scores": {"$push": "$top1_rerank"},
                "avg_files": {"$avg": "$n_files"},
                "total": {"$sum": 1},
                "truncated": {"$sum": {"$cond": ["$is_truncated", 1, 0]}},
                "last_time": {"$max": "$date"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "top1_scores": 1,
                "avg_files": 1,
                "total": 1,
                "truncated": 1,
                "last_date": {"$dateToString": {"date": "$last_time", "format": "%Y-%m-%d"}},
            }
        },
    ]
    agg = list(coll.aggregate(pipeline))
    if not agg:
        return {"rerank_top1_p50": 0.0, "avg_note_files": 0.0, "truncation_rate": 0.0, "last_date": "無資料"}

    row = agg[0]
    top1 = pd.Series([s for s in row.get("top1_scores", []) if s is not None], dtype="float64")
    total = row.get("total", 0) or 0
    return {
        "rerank_top1_p50": float(top1.median()) if not top1.empty else 0.0,
        "avg_note_files": float(row.get("avg_files") or 0.0),
        "truncation_rate": (row.get("truncated", 0) / total * 100) if total else 0.0,
        "last_date": row.get("last_date", "無資料"),
    }


def get_problem_features(db: Database, collection: str = "ccClub&leetcode_summary") -> dict:
    """取得最新一次快照中，LeetCode 與 ccClub 兩個來源的題目主題佔比。

    Args:
        db: pymongo Database 物件。
        collection: 來源 collection 名稱，預設 ccClub&leetcode_summary。

    Returns:
        含 LeetCode、ccClub-Python 兩份主題佔比 dict 與 snapshot_date 的 dict；
        無資料時兩份佔比為空 dict、快照日期為 None。
    """
    coll = db[collection]
    data = list(coll.find({}, {"_id": 0}).sort({"snapshot_date": -1}).limit(1))
    if not data:
        return {"LeetCode": {}, "ccClub-Python": {}, "snapshot_date": None}

    return {
        "LeetCode": data[0]["topicsPercentOnLeetcode"],
        "ccClub-Python": data[0]["topicsPercentOnCCclub"],
        "snapshot_date": data[0]["snapshot_date"],
    }
