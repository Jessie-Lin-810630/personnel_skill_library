"""task05 Transform：把兩張技能工作表依權重算成任務分數，並彙整成雷達圖摘要。

1. 函式 build_biotech_task_docs 與 build_de_task_docs 依複雜度、獨立性與影響力等權重，把工作表的每一列算成任務分數。
2. 函式 build_summary_for_radar 把某一領域的任務分數彙整成單張雷達圖的軸摘要。
3. 函式 build_combined_summaries 把生技與資料工程兩張雷達摘要合併成一份，供 Streamlit 使用。
"""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
from loguru import logger

BIOTECH_RADAR_LABELS = [
    "製程技術 (細胞分注、反應器操作) 操作能力",
    "流程設計能力",
    "跨專案數據整合能力",
    "文件撰寫能力",
    "簡報口說能力",
]

DE_RADER_LABELS = [
    "ETL/ELT pipeline 操作與維護",
    "雲端 (GCP) 服務技術",
    "Orchestration",
    "資料庫資料模型設計",
    "文案設計與歸納",
    "資料視覺化",
    "資料品質與血緣維護",
]


def build_biotech_task_docs(
    df: pd.DataFrame,
    task_type: list[str],
    weight_complexity: tuple = (1, 3, 3, 3),
    weight_independence: tuple = (1, 5, 9),
    weight_influence: tuple = (9, 5, 1, 0),
    score_weight: tuple = (1, 1, 2),
) -> pd.DataFrame:
    """把生技工作表的原始列依權重算成帶分數的任務 document。

    1. 只留下 task_type 指定的雷達軸。
    2. 把複雜性、獨立性、影響力欄位的 Y 轉 1、其餘轉 0。
    3. 依三組權重分別算出複雜性、獨立性、影響力總分，再依 score_weight 加權成單項任務總分。

    Args:
        df: 從生技工作表 extract 出的原始 DataFrame。
        task_type: 要保留的雷達軸標籤清單，為 BIOTECH_RADAR_LABELS 的子集。
        weight_complexity: 複雜性四級（純紀錄、執行操作、制定方向、優化與故障排除）的權重。
        weight_independence: 獨立性三級（需要指導、不需指導、自訂架構）的權重。
        weight_influence: 影響力四級（公司外、跨部門、部門內、不具備）的權重。
        score_weight: 單項任務總分中複雜性、獨立性、影響力三面向的權重。

    Returns:
        每列多出複雜性總分、獨立性總分、影響力總分與單項任務總分欄位的 DataFrame。
    """
    logger.info(f"Building biotech task docs for axes: {task_type}...")

    # 1. 留下核心軸向
    df_stats = df[df["雷達軸"].isin(task_type)].copy()
    logger.debug(f"Rows after axis filter: {len(df_stats)}")  # 部署到生產環境時可以濾掉debug logging level

    # 2. 若為 Y，置換成 1；若非 Y，置換成 0
    flag_cols = [col for col in df_stats.columns if any(flag in col for flag in ("複雜性", "獨立性", "影響力"))]
    for col in flag_cols:
        df_stats[col] = df_stats[col].apply(lambda x: 1 if isinstance(x, str) and x.strip().upper() == "Y" else 0)

    # 計算每個任務的三面向執行評分
    # 3. 複雜性:
    w1, w2, w3, w4 = weight_complexity
    df_stats["複雜性總分"] = (
        df_stats["複雜性 - 純紀錄"] * w1
        + df_stats["複雜性 - 執行操作"] * w2
        + df_stats["複雜性 - 制定方向"] * w3
        + df_stats["複雜性 - 優化與故障排除"] * w4
    )
    # 4. 獨立性:
    w1, w2, w3 = weight_independence
    df_stats["獨立性總分"] = (
        df_stats["獨立性 - 需要指導後才能照規章做"] * w1
        + df_stats["獨立性 - 不需指導即可理解並遵照組織規章做"] * w2
        + df_stats["獨立性 - 自訂架構"] * w3
    )
    # 5. 影響力:
    w1, w2, w3, w4 = weight_influence
    df_stats["影響力總分"] = (
        df_stats["影響力 - 具備公司外出教學經驗"] * w1
        + df_stats["影響力 - 具備跨部門教學經驗"] * w2
        + df_stats["影響力 - 具備部門內教學經驗"] * w3
        + df_stats["影響力 -  不具備教學的經驗"] * w4
    )

    # 6. 單項任務總分
    w1, w2, w3 = score_weight
    df_stats["單項任務總分"] = df_stats["複雜性總分"] * w1 + df_stats["獨立性總分"] * w2 + df_stats["影響力總分"] * w3

    logger.success(f"Built biotech task docs. Total rows: {len(df_stats)}")
    return df_stats


def build_de_task_docs(
    df: pd.DataFrame,
    task_type: list[str],
    weight_complexity: tuple = (1, 3, 3, 3),
    weight_independence: tuple = (1, 5, 9),
    weight_influence: tuple = (9, 5, 1, 0),
    score_weight: tuple = (1, 2, 1),
) -> pd.DataFrame:
    """把資料工程工作表的原始列依權重算成帶分數的任務 document。

    1. 只留下 task_type 指定的雷達軸。
    2. 把複雜性、獨立性、影響力欄位的 Y 轉 1、其餘轉 0。
    3. 依三組權重分別算出複雜性、獨立性、影響力總分，再依 score_weight 加權成單項任務總分。

    Args:
        df: 從資料工程工作表 extract 出的原始 DataFrame。
        task_type: 要保留的雷達軸標籤清單，為 DE_RADER_LABELS 的子集。
        weight_complexity: 複雜性四級（純紀錄與理解、開發測試、接手部署、優化與故障排除）的權重。
        weight_independence: 獨立性三級（需要指導、不需指導、自訂架構）的權重。
        weight_influence: 影響力四級（公司外、跨部門、部門內、不具備）的權重。
        score_weight: 單項任務總分中複雜性、獨立性、影響力三面向的權重。

    Returns:
        每列多出複雜性總分、獨立性總分、影響力總分與單項任務總分欄位的 DataFrame。
    """
    logger.info(f"Building data engineering task docs for axes: {task_type}...")

    # 1. 留下核心軸向
    df_stats = df[df["雷達軸"].isin(task_type)].copy()
    logger.debug(f"Rows after axis filter: {len(df_stats)}")  # 部署到生產環境時可以濾掉debug logging level

    # 2. 若為 Y，置換成 1；若非 Y，置換成 0
    flag_cols = [col for col in df_stats.columns if any(flag in col for flag in ("複雜性", "獨立性", "影響力"))]
    for col in flag_cols:
        df_stats[col] = df_stats[col].apply(lambda x: 1 if isinstance(x, str) and x.strip().upper() == "Y" else 0)

    # 計算每個任務的三面向執行評分
    # 3. 複雜性:
    w1, w2, w3, w4 = weight_complexity
    df_stats["複雜性總分"] = (
        df_stats["複雜性 - 純紀錄與理解"] * w1
        + df_stats["複雜性 - 開發測試"] * w2
        + df_stats["複雜性 - 接手部署"] * w3
        + df_stats["複雜性 - 優化與故障排除"] * w4
    )
    # 4. 獨立性:
    w1, w2, w3 = weight_independence
    df_stats["獨立性總分"] = (
        df_stats["獨立性 - 需要指導後才能照規章做"] * w1
        + df_stats["獨立性 - 不需指導即可理解並遵照組織規章做"] * w2
        + df_stats["獨立性 - 自訂架構"] * w3
    )
    # 5. 影響力:
    w1, w2, w3, w4 = weight_influence
    df_stats["影響力總分"] = (
        df_stats["影響力 - 具備公司外出教學經驗"] * w1
        + df_stats["影響力 - 具備跨部門教學經驗"] * w2
        + df_stats["影響力 - 具備部門內教學經驗"] * w3
        + df_stats["影響力 -  不具備教學的經驗"] * w4
    )

    # 6. 單項任務總分
    w1, w2, w3 = score_weight
    df_stats["單項任務總分"] = df_stats["複雜性總分"] * w1 + df_stats["獨立性總分"] * w2 + df_stats["影響力總分"] * w3
    logger.success(f"Built DE task docs built. Total rows: {len(df_stats)}")
    return df_stats


def build_summary_for_radar(df: pd.DataFrame, radar_plot_name) -> pd.DataFrame:
    """把每個任務的分數彙整成各雷達軸一列的摘要，並分級成 level。

    以雷達軸 groupby 統計經手任務個數與各軸最高分，換算任務經驗值與單軸總分後，
    依邊界分成 1 到 5 級，最後附上雷達圖名稱與 snapshot_date。

    Args:
        df: build_biotech_task_docs 或 build_de_task_docs 的輸出 DataFrame。
        radar_plot_name: 此雷達圖的名稱，例如「雷達圖1生技」。

    Returns:
        每個雷達軸一列、含 level 與 snapshot_date 的摘要 DataFrame。
    """
    logger.info(f"Building radar summary for: {radar_plot_name}...")

    df_group = df.groupby(by="雷達軸", as_index=False).agg(
        經手任務個數=("經手任務", "count"),
        各軸向任務最高分=("單項任務總分", "max"),
    )

    df_group["任務經驗值"] = np.round((np.log10(df_group["經手任務個數"])), 6)
    df_group["單軸總分"] = np.round((df_group["各軸向任務最高分"] + df_group["任務經驗值"]), 2)

    # 定義邊界 (Bins) 與 對應的標籤 (Labels)
    # bins 的設定包含左邊界，不包含右邊界
    bins = [-float("inf"), 5, 12, 15, 23, float("inf")]
    labels = [1, 2, 3, 4, 5]

    df_group["level"] = pd.cut(df_group["單軸總分"], bins=bins, labels=labels, right=False).astype(int)

    df_group["雷達圖名稱"] = radar_plot_name
    # snapshot_date 存 datetime 物件、但只表示到日（時分秒毫秒歸零），供以日為粒度的複合鍵 upsert 與排序。
    df_group["snapshot_date"] = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    df_final = df_group.loc[
        :,
        [
            "雷達圖名稱",
            "雷達軸",
            "經手任務個數",
            "任務經驗值",
            "各軸向任務最高分",
            "單軸總分",
            "level",
            "snapshot_date",
        ],
    ].sort_values(by=["單軸總分"], ascending=False)

    logger.success(f"Built Radar summary. Axes count: {len(df_final)}")
    return df_final


def build_combined_summaries(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """把生技與資料工程兩張雷達摘要合併成一張 DataFrame。

    Args:
        dfs: 要合併的雷達摘要 DataFrame 清單。

    Returns:
        合併後的 DataFrame。
    """
    logger.info("Combining biotech and DE radar summaries.")
    if dfs:
        df_combined = pd.concat(dfs, ignore_index=True)
        logger.success(f"Combined Radar summary rows: {len(df_combined)}")
        return df_combined
