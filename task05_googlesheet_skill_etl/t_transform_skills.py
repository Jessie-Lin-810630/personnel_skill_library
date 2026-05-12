from datetime import datetime, timezone
import numpy as np
import pandas as pd
from loguru import logger

BIOTECH_RADAR_LABELS = ["製程技術 (細胞分注、反應器操作) 操作能力",
                        "流程設計能力",
                        "跨專案數據整合能力",
                        "文件撰寫能力",
                        "簡報口說能力"]

DE_RADER_LABELS = ["ETL/ELT pipeline 操作與維護",
                   "雲端 (GCP) 服務技術",
                   "Orchestration",
                   "資料庫資料模型設計",
                   "文案設計與歸納",
                   "資料視覺化",
                   "資料品質與血緣維護"]


def build_biotech_task_docs(df: pd.DataFrame,
                            task_type: list[str],
                            weight_complexity: tuple = (1, 3, 3, 3),
                            weight_independence: tuple = (1, 5, 9),
                            weight_influence: tuple = (9, 5, 1, 0),
                            score_weight: tuple = (1, 1, 2)) -> pd.DataFrame:
    """
    Transform raw biotech Google Worksheet rows into scored task documents.

    Parameters
    ----------
    df               : Raw DataFrame extracted from the biotech worksheet.
    task_type        : List of 雷達軸 labels to keep (subset of BIOTECH_RADAR_LABELS).
    weight_complexity: Weights for (純紀錄, 執行操作, 制定方向, 優化與故障排除).
    weight_independence: Weights for (需要指導, 不需指導, 自訂架構).
    weight_influence : Weights for (公司外, 跨部門, 部門內, 不具備).
    score_weight     : Weights for (複雜性, 獨立性, 影響力) in final task score.

    Returns
    -------
    """
    logger.info(f"Building biotech task docs for axes: {task_type}...")

    # 1. 留下核心軸向
    df_stats = df[df["雷達軸"].isin(task_type)].copy()
    logger.debug(f"Rows after axis filter: {len(df_stats)}")  # 部署到生產環境時可以濾掉debug logging level

    # 2. 若為 Y，置換成 1；若非 Y，置換成 0
    flag_cols = [col for col in df_stats.columns if any(flag in col for flag in ("複雜性", "獨立性", "影響力"))]
    for col in flag_cols:
        df_stats[col] = df_stats[col].apply(
            lambda x: 1 if isinstance(x, str) and x.strip().upper() == "Y" else 0)

    # 計算每個任務的三面向執行評分
    # 3. 複雜性:
    w1, w2, w3, w4 = weight_complexity
    df_stats["複雜性總分"] = (df_stats["複雜性 - 純紀錄"]*w1 +
                         df_stats["複雜性 - 執行操作"]*w2 +
                         df_stats["複雜性 - 制定方向"]*w3 +
                         df_stats["複雜性 - 優化與故障排除"]*w4
                         )
    # 4. 獨立性:
    w1, w2, w3 = weight_independence
    df_stats["獨立性總分"] = (df_stats["獨立性 - 需要指導後才能照規章做"]*w1 +
                         df_stats["獨立性 - 不需指導即可理解並遵照組織規章做"]*w2 +
                         df_stats["獨立性 - 自訂架構"]*w3
                         )
    # 5. 影響力:
    w1, w2, w3, w4 = weight_influence
    df_stats["影響力總分"] = (df_stats["影響力 - 具備公司外出教學經驗"]*w1 +
                         df_stats["影響力 - 具備跨部門教學經驗"]*w2 +
                         df_stats["影響力 - 具備部門內教學經驗"]*w3 +
                         df_stats["影響力 -  不具備教學的經驗"]*w4
                         )

    # 6. 單項任務總分
    w1, w2, w3 = score_weight
    df_stats["單項任務總分"] = (df_stats["複雜性總分"]*w1 +
                          df_stats["獨立性總分"]*w2 +
                          df_stats["影響力總分"]*w3
                          )

    logger.success(f"Built biotech task docs. Total rows: {len(df_stats)}")
    return df_stats


def build_de_task_docs(df: pd.DataFrame,
                       task_type: list[str],
                       weight_complexity: tuple = (1, 3, 3, 3),
                       weight_independence: tuple = (1, 5, 9),
                       weight_influence: tuple = (9, 5, 1, 0),
                       score_weight: tuple = (1, 2, 1)) -> pd.DataFrame:
    """
    Transform raw data-engineering Google Sheet rows into scored task documents.

    Parameters
    ----------
    df               : Raw DataFrame extracted from the DE worksheet.
    task_type        : List of 雷達軸 labels to keep (subset of DE_RADAR_LABELS).
    weight_complexity: Weights for (純紀錄與理解, 開發測試, 接手部署, 優化與故障排除).
    weight_independence: Weights for (需要指導, 不需指導, 自訂架構).
    weight_influence : Weights for (公司外, 跨部門, 部門內, 不具備).
    score_weight     : Weights for (複雜性, 獨立性, 影響力) in final task score.

    Returns
    -------
    DataFrame with individual task scores appended.
    """
    logger.info(f"Building data engineering task docs for axes: {task_type}...")

    # 1. 留下核心軸向
    df_stats = df[df["雷達軸"].isin(task_type)].copy()
    logger.debug(f"Rows after axis filter: {len(df_stats)}")  # 部署到生產環境時可以濾掉debug logging level

    # 2. 若為 Y，置換成 1；若非 Y，置換成 0
    flag_cols = [col for col in df_stats.columns if any(flag in col for flag in ("複雜性", "獨立性", "影響力"))]
    for col in flag_cols:
        df_stats[col] = df_stats[col].apply(
            lambda x: 1 if isinstance(x, str) and x.strip().upper() == "Y" else 0)

    # 計算每個任務的三面向執行評分
    # 3. 複雜性:
    w1, w2, w3, w4 = weight_complexity
    df_stats["複雜性總分"] = (df_stats["複雜性 - 純紀錄與理解"]*w1 +
                         df_stats["複雜性 - 開發測試"]*w2 +
                         df_stats["複雜性 - 接手部署"]*w3 +
                         df_stats["複雜性 - 優化與故障排除"]*w4
                         )
    # 4. 獨立性:
    w1, w2, w3 = weight_independence
    df_stats["獨立性總分"] = (df_stats["獨立性 - 需要指導後才能照規章做"]*w1 +
                         df_stats["獨立性 - 不需指導即可理解並遵照組織規章做"]*w2 +
                         df_stats["獨立性 - 自訂架構"]*w3
                         )
    # 5. 影響力:
    w1, w2, w3, w4 = weight_influence
    df_stats["影響力總分"] = (df_stats["影響力 - 具備公司外出教學經驗"]*w1 +
                         df_stats["影響力 - 具備跨部門教學經驗"]*w2 +
                         df_stats["影響力 - 具備部門內教學經驗"]*w3 +
                         df_stats["影響力 -  不具備教學的經驗"]*w4
                         )

    # 6. 單項任務總分
    w1, w2, w3 = score_weight
    df_stats["單項任務總分"] = (df_stats["複雜性總分"]*w1 +
                          df_stats["獨立性總分"]*w2 +
                          df_stats["影響力總分"]*w3
                          )
    logger.success(f"Built DE task docs built. Total rows: {len(df_stats)}")
    return df_stats


def build_summary_for_radar(df: pd.DataFrame, radar_plot_name) -> pd.DataFrame:
    """
    Aggregate per-task scores into a per-axis radar summary with level bucketing.

    Parameters
    ----------
    df              : Output of build_biotech_task_docs or build_de_task_docs.
    radar_plot_name : Label for this radar chart (e.g. '雷達圖1生技').

    Returns
    -------
    DataFrame with one row per 雷達軸, including level and snapshot_date.
    """
    logger.info(f"Building radar summary for: {radar_plot_name}...")

    df_group = df.groupby(by="雷達軸", as_index=False).agg(經手任務個數=("經手任務", "count"),
                                                        各軸向任務最高分=("單項任務總分", "max"),
                                                        )

    df_group["任務經驗值"] = np.round((np.log10(df_group["經手任務個數"])), 6)
    df_group["單軸總分"] = np.round((df_group["各軸向任務最高分"] + df_group["任務經驗值"]), 2)

    # 定義邊界 (Bins) 與 對應的標籤 (Labels)
    # bins 的設定包含左邊界，不包含右邊界
    bins = [-float('inf'), 5, 12, 15, 23, float('inf')]
    labels = [1, 2, 3, 4, 5]

    df_group["level"] = pd.cut(df_group["單軸總分"], bins=bins,
                               labels=labels, right=False
                               ).astype(int)

    df_group["雷達圖名稱"] = radar_plot_name
    df_group["snapshot_date"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    df_final = df_group.loc[:,
                            ["雷達圖名稱", "雷達軸", "經手任務個數",
                             "任務經驗值", "各軸向任務最高分", "單軸總分",
                             "level", "snapshot_date"]].sort_values(by=["單軸總分"], ascending=False)

    logger.success(f"Built Radar summary. Axes count: {len(df_final)}")
    return df_final


def build_combined_summaries(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate two radar summaries (biotech + DE) into one DataFrame.

    Parameters
    ----------
    dfs: A list of DataFrames to concatenate.

    Returns
    -------
    A concatenated DataFrame
    """

    logger.info("Combining biotech and DE radar summaries.")
    if dfs:
        df_combined = pd.concat(dfs, ignore_index=True)
        logger.success(f"Combined Radar summary rows: {len(df_combined)}")
        return df_combined


# if __name__ == "__main__":
#     # 測試區
#     from .e_fetch_google_sheet import get_google_sheet_client, open_spreadsheet_get_worksheet
#     import os
#     from dotenv import load_dotenv

#     load_dotenv()
#     CREDENTIAL_FILE_PATH = os.getenv("GS_CREDENTIAL_FILE_PATH")
#     client = get_google_sheet_client(CREDENTIAL_FILE_PATH)

#     # E
#     df_biotech = open_spreadsheet_get_worksheet(client, "Personal Skill Radar Calculation",
#                                                 "生技")
#     df_de = open_spreadsheet_get_worksheet(client, "Personal Skill Radar Calculation",
#                                            "資料工程")

#     # T
#     df_biotech_stats = build_biotech_task_docs(df_biotech, BIOTECH_RADAR_LABELS)
#     df_de_stats = build_de_task_docs(df_de, DE_RADER_LABELS)
#     df_both_summary = build_combined_summaries([build_summary_for_radar(df_biotech_stats, "雷達圖1生技"),
#                                                build_summary_for_radar(df_de_stats, "雷達圖2資料工程")
#                                                 ])
