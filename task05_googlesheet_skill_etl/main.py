"""task05 入口：串接 Google Sheets 技能雷達 ETL 的 Extract、Transform、Load 三階段。

1. Extract 以 service account 開啟試算表，分別讀出生技與資料工程兩張工作表。
2. Transform 依權重把兩張工作表算成任務分數，再彙整成雷達圖摘要。
3. Load 以 upsert 把分數寫入 skill_scores_biotech 與 skill_scores_data_eng，摘要寫入 skill_radar_summary。

Usage:
    poetry run python -m task05_googlesheet_skill_etl.main

Required .env keys:
    GOOGLE_SHEET_KEY   Decoded service account JSON string for Google Sheets access.
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

    1. 檢查 Google Sheets 與 MongoDB 連線用的環境變數，缺任一就拋 EnvironmentError。
    2. Extract 讀出生技與資料工程兩張工作表。
    3. Transform 依權重把兩張工作表算成任務分數，再彙整成雷達圖摘要。
    4. Load 以 upsert 寫入 skill_scores_biotech、skill_scores_data_eng 與 skill_radar_summary。
    """
    google_sheet_key = os.getenv("GOOGLE_SHEET_KEY")
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([google_sheet_key, mongo_uri, db_name]):
        logger.error("請確認 secret manager 已設定 GOOGLE_SHEET_KEY / MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 secret manager 已設定 GOOGLE_SHEET_KEY / MONGO_ALTAS_URI / MONGO_DB_NAME")

    logger.info("=== Task 05: Google Sheet skills records ETL 開始 ===")

    # Extract
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

    logger.success("=== Task 05: Google Sheet skills records ETL 完成 ===")


if __name__ == "__main__":
    run_task05()
