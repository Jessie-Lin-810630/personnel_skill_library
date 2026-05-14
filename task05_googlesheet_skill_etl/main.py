import os
from loguru import logger
from .e_fetch_google_sheet import get_google_sheet_client, open_spreadsheet_get_worksheet
from .t_transform_skills import (build_biotech_task_docs,
                                 build_de_task_docs,
                                 build_summary_for_radar,
                                 build_combined_summaries,
                                 BIOTECH_RADAR_LABELS,
                                 DE_RADER_LABELS)
from .l_load_to_mongodb import get_db, upsert_skill_scores, upsert_skill_radar_summary

"""
執行E、T、L。
"""


def run_task05():
    google_sheet_key = os.getenv("GOOGLE_SHEET_KEY")
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([google_sheet_key, mongo_uri, db_name]):
        logger.error("請確認 secret manager 已設定 GOOGLE_SHEET_KEY / MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 secret manager 已設定 GOOGLE_SHEET_KEY / MONGO_ALTAS_URI / MONGO_DB_NAME")

    logger.info("=== Task 05: Google Sheet skills records ETL 開始 ===")

    # Extract
    client = get_google_sheet_client(CREDENTAIL_JSONS_FROM_ENVAR=google_sheet_key)
    df_biotech = open_spreadsheet_get_worksheet(client, "Personal Skill Radar Calculation",
                                                "生技")
    df_de = open_spreadsheet_get_worksheet(client, "Personal Skill Radar Calculation",
                                           "資料工程")

    # Transform
    df_biotech_stats = build_biotech_task_docs(df_biotech, BIOTECH_RADAR_LABELS)
    df_de_stats = build_de_task_docs(df_de, DE_RADER_LABELS)
    df_both_summary = build_combined_summaries([
        build_summary_for_radar(df_biotech_stats, "雷達圖1生技"),
        build_summary_for_radar(df_de_stats, "雷達圖2資料工程")
    ])

    # Load
    db = get_db(mongo_uri, db_name)
    upsert_skill_scores(db, "skill_scores_biotech", df_biotech_stats)
    upsert_skill_scores(db, "skill_scores_data_eng", df_de_stats)
    upsert_skill_radar_summary(db, df_both_summary)

    logger.success("=== Task 05: Google Sheet skills records ETL 完成 ===")


if __name__ == "__main__":
    run_task05()
