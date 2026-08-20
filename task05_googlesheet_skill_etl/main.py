"""task05 入口：串接 Google Sheets 技能雷達 ETL 的 Extract、Transform、Load 三階段。

1. Extract 以 service account 開啟試算表，分別讀出生技與資料工程兩張工作表。
2. Transform 依權重把兩張工作表算成任務分數，再彙整成雷達圖摘要。
3. Load 以 upsert 把分數寫入 skill_scores_biotech 與 skill_scores_data_eng，摘要寫入 skill_radar_summary。

Usage:
    poetry run python -m task05_googlesheet_skill_etl.main

Required .env keys:
    GOOGLE_SHEET_KEY   Service account credential for Google Sheets access; a path to the
                       JSON key file when running locally, or the decoded JSON string on GCP.
    MONGO_ALTAS_URI    MongoDB Atlas connection string.
    MONGO_DB_NAME      Target database name.
"""

import os

from loguru import logger

from .e_fetch_google_sheet import get_google_sheet_client, open_spreadsheet_get_worksheet
from .l_load_to_mongodb import get_db, upsert_skill_radar_summary, upsert_skill_scores
from .t_transform_skills import (
    BIOTECH_RADAR_LABELS,
    DE_RADER_LABELS,
    build_biotech_task_docs,
    build_combined_summaries,
    build_de_task_docs,
    build_summary_for_radar,
)


def run_task05():
    """task05 總入口，依序執行 Google Sheets 技能雷達的 Extract、Transform、Load。

    1. 檢查 Google Sheets 與 MongoDB 連線用的環境變數，缺任一就中止。
    2. 依憑證的形式選擇授權方式，讀出生技與資料工程兩張工作表。
    3. 依權重把兩張工作表算成任務分數，再各彙整成一張雷達圖摘要並合併。
    4. 以 upsert 寫入 skill_scores_biotech、skill_scores_data_eng 與 skill_radar_summary。

    Note:
        - 憑證的形式以「這個值是不是一個存在的檔案路徑」判斷：是就當金鑰檔讀，
          不是就當成憑證內容放在環境變數裡，後者適用於將此函式放到 GCP 以 secret manager 管理
          環境變數的情境，一般來說，地端執行只需要符合前者、將金鑰檔的路徑傳入環境變數即可。
        - 試算表與工作表名稱都寫死在這支函式裡，改名時要一併改這裡。
        - 整條流程沒有逐張略過失敗的機制，任一步失敗就中止，這一輪不會有任何資料寫入 MongoDB。
        - 最外層只在此印一次完整 traceback 後往外拋，避免同一個例外在各層重複記錄。

    Returns:
        None: 資料寫進 MongoDB 的 skill_scores_biotech、skill_scores_data_eng 與
        skill_radar_summary，執行狀況只記進 log，不回傳值。

    Raises:
        EnvironmentError: GOOGLE_SHEET_KEY、MONGO_ALTAS_URI 或 MONGO_DB_NAME 任一未設定時拋出。
        Exception: 讀取、計算或寫入失敗時，記錄 traceback 後原樣往外拋。
    """
    google_sheet_key = os.getenv("GOOGLE_SHEET_KEY")
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([google_sheet_key, mongo_uri, db_name]):
        logger.error("請確認 secret manager 已設定 GOOGLE_SHEET_KEY / MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 secret manager 已設定 GOOGLE_SHEET_KEY / MONGO_ALTAS_URI / MONGO_DB_NAME")

    logger.info("=== Task 05: Google Sheet skills records ETL 開始 ===")

    # 最外層統一接住內層拋出的例外，只在此處印一次完整 traceback 後再往上拋
    # （loguru 不吃 exc_info=True，需用 logger.opt(exception=True) 才會帶出 traceback）
    try:
        # Extract
        if os.path.isfile(google_sheet_key):  # 地端可改用 path to service account JSON key file
            client = get_google_sheet_client(CREDENTIAL_FILE_PATH=google_sheet_key)
        else:
            client = get_google_sheet_client(CREDENTAIL_JSONS_FROM_ENVAR="GOOGLE_SHEET_KEY")
        df_biotech = open_spreadsheet_get_worksheet(client, "Personal Skill Radar Calculation", "生技")
        df_de = open_spreadsheet_get_worksheet(client, "Personal Skill Radar Calculation", "資料工程")

        # Transform
        df_biotech_stats = build_biotech_task_docs(df_biotech, BIOTECH_RADAR_LABELS)
        df_de_stats = build_de_task_docs(df_de, DE_RADER_LABELS)
        df_both_summary = build_combined_summaries(
            [
                build_summary_for_radar(df_biotech_stats, "雷達圖1生技"),
                build_summary_for_radar(df_de_stats, "雷達圖2資料工程"),
            ]
        )

        # Load
        db = get_db(mongo_uri, db_name)
        upsert_skill_scores(db, "skill_scores_biotech", df_biotech_stats)
        upsert_skill_scores(db, "skill_scores_data_eng", df_de_stats)
        upsert_skill_radar_summary(db, df_both_summary)
    except Exception:
        logger.opt(exception=True).critical("Task 05 job failed")
        raise

    logger.success("=== Task 05: Google Sheet skills records ETL 完成 ===")


if __name__ == "__main__":
    # # 地端執行時，需要 uncomment 下面兩行後再執行
    # from dotenv import load_dotenv
    # load_dotenv()
    run_task05()
