"""檢索品質頁（Retrieval & Search Quality），呈現關卡 4→8 的檢索端效能。

由上而下組裝三段：圖表 6 similarity vs rerank 散佈圖（含離群分類）→ 圖表 9
檢索輪數分佈 & 冷熱資料 treemap → 圖表 10 檢索品質健康度雷達（滿意度代理指標）。
資料來自 MongoDB chat_history 的 rag 對話紀錄，查詢封裝於
utils.interact_with_mongodb，DB 結果以 st.cache_data 快取。

Usage:
    poetry run streamlit run dashboard_ui/app.py
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from utils.interact_with_mongodb import (
    get_db_atlas,
    get_rag_file_retrieval_counts,
    get_rag_retrieved_chunks,
    get_rag_satisfaction_proxy,
    get_rag_session_rounds,
)
from utils.ui_elements import _render_side_bar, color_map

# ─────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────
st.set_page_config(
    page_title="Retrieval & Search Quality",
    page_icon="⚡️",
    layout="wide",
    initial_sidebar_state="expanded",
)
_render_side_bar()

# ─────────────────────────────────────────
# 常數
# ─────────────────────────────────────────
CONTENT_TRUNCATE_LIMIT = 2000  # chat_history 的 content 截斷上限

# ─────────────────────────────────────────
# metric 卡片
# ─────────────────────────────────────────
st.markdown(
    """
    <style>
    [data-testid="stMetricValue"] { font-size: 2.0rem !important; }
    [data-testid="stMetric"] {
        background: #55575AD8;
        border-radius: 12px;
        padding: 1rem 1.2rem;
        border: 1px solid #2a3550;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────
# 讀取 MongoDB 資料（DB 結果進 st.cache_data）
# ─────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_retrieved_chunks() -> pd.DataFrame:
    return get_rag_retrieved_chunks(get_db_atlas())


@st.cache_data(ttl=300)
def _load_session_rounds() -> pd.DataFrame:
    return get_rag_session_rounds(get_db_atlas())


@st.cache_data(ttl=300)
def _load_file_counts() -> pd.DataFrame:
    return get_rag_file_retrieval_counts(get_db_atlas())


@st.cache_data(ttl=300)
def _load_satisfaction() -> dict:
    return get_rag_satisfaction_proxy(get_db_atlas(), truncate_limit=CONTENT_TRUNCATE_LIMIT)


chunks_df = _load_retrieved_chunks()
rounds_df = _load_session_rounds()
file_counts_df = _load_file_counts()
satisfaction = _load_satisfaction()

# 平均輪數只算一次，histogram 與 satisfaction radar 兩張圖共用
avg_rounds = float(rounds_df["rounds"].mean()) if not rounds_df.empty else 0.0
satisfaction["avg_rounds"] = avg_rounds


# ─────────────────────────────────────────
# 標題
# ─────────────────────────────────────────
st.markdown(
    f"""
<div style="
    background: linear-gradient(135deg, #0f2040 50%, #0d1526 0%, #0f2040 50%, #1a1040 100%);
    border-radius: 16px;
    padding: 2rem 3rem;
    margin-bottom: 1.8rem;
    border: 1px solid #2a3550;
    text-align: center;
">
    <h1 style="color:{color_map["FONT_CLR"]}; font-size:2.2rem; font-weight:800; margin:0 0 0.4rem 0; line-height:1.1;">
    檢索系統品質監控儀表板<br>Retrieval Quality
    </h1>
    <p style="color:{color_map["GRAY"]}; font-size:1rem; margin:0; letter-spacing:0.5px; font-weight:500;">
        最近更新日：{satisfaction["last_date"]}
    </p>
</div>
""",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────
# 圖表 6 — Similarity vs Rerank Score 散佈圖
# ─────────────────────────────────────────
st.divider()
st.markdown("### Cosine Similarity Score vs. Rerank score 散佈圖")
st.caption("主要受眾: `ML Engineer`　｜　資料來源: `chat_history`")

if chunks_df.empty:
    st.info("尚無 RAG 檢索紀錄，無法繪製散佈圖。")
else:

    def classify_outlier(row):
        if row["score"] > 0.80 and row["rerank_score"] < 0.20:
            return "Similarity score 偏高、Rerank score 偏低"
        elif row["score"] < 0.60 and row["rerank_score"] > 0.60:
            return "Similarity score 偏低、Rerank score 偏高"
        return "Similarity score 與 Rerank score 屬常態"

    chunks_df["outlier_type"] = chunks_df.apply(classify_outlier, axis=1)
    chunks_df["file_name"] = chunks_df["file_path"].apply(lambda x: x.split("/")[-1] if isinstance(x, str) else x)
    color_map_outlier = {
        "Similarity score 與 Rerank score 屬常態": color_map["LIGHTBLUE"],
        "Similarity score 偏高、Rerank score 偏低": color_map["RED"],
        "Similarity score 偏低、Rerank score 偏高": color_map["ORANGE"],
    }

    fig_scatter = px.scatter(
        chunks_df,
        x="score",
        y="rerank_score",
        color="outlier_type",
        color_discrete_map=color_map_outlier,
        hover_data=["file_name", "chunk_index", "session_id"],
        opacity=0.75,
        labels={
            "score": "Vector similarity score",
            "rerank_score": "Rerank score",
            "outlier_type": "檢索品質",
            "file_name": "File name",
            "chunk_index": "Chunk #",
            "session_id": "Session",
        },
    )
    # 四象限分隔虛線（僅作視覺分區，非門檻值）
    fig_scatter.add_vline(x=0.6, line=dict(dash="dot", color=color_map["GRAY"], width=1))
    fig_scatter.add_hline(y=0.6, line=dict(dash="dot", color=color_map["GRAY"], width=1))
    fig_scatter.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=460,
        margin=dict(l=20, r=20, t=30, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(color=color_map["FONT_CLR"], size=14)),
        xaxis=dict(range=[0.5, 1.0], tickfont=dict(color=color_map["FONT_CLR"], size=14), showgrid=False),
        yaxis=dict(range=[0.0, 1.0], tickfont=dict(color=color_map["FONT_CLR"], size=14), showgrid=False),
        font=dict(size=16, color=color_map["FONT_CLR"]),
    )
    st.plotly_chart(fig_scatter, width="stretch")

    outlier_counts = chunks_df["outlier_type"].value_counts()
    o1, o2, o3 = st.columns(3)
    o1.metric(
        "正常 chunks",
        int(outlier_counts.get("Similarity score 與 Rerank score 屬常態", 0)),
        help="Similarity 和 Rerank 大致正相關",
    )
    o2.metric(
        "🔴 Similarity score 偏高、Rerank score 偏低",
        int(outlier_counts.get("Similarity score 偏高、Rerank score 偏低", 0)),
        help="Embedding 判定相似，但重排序後不相關，可能 chunking 策略破壞語意",
    )
    o3.metric(
        "🔶 Similarity score 偏低、Rerank score 偏高",
        int(outlier_counts.get("Similarity score 偏低、Rerank score 偏高", 0)),
        help="向量空間沒抓到但語意其實相關，embedding 維度或模型可能需要調整",
    )

    with st.expander("💡 解讀提示"):
        st.markdown(
            "**理想狀態**: 所有點沿虛線（正相關）分佈。\n\n"
            "**紅色離群（Sim 高 Rerank 低）**: 最危險的類型。"
            "embedding 判定兩段文字很近，但 reranker 認為語意不相關。"
            "常見原因：chunking 切在句子中間導致語意破碎，或 embedding dimension 過高造成假相似。\n\n"
            "**橘色離群（Sim 低 Rerank 高）**: 向量搜尋沒抓到但其實是好結果。"
            "這類點很多代表 top-k 的 recall 不足，可考慮增大 k 或調整 embedding 模型。"
        )


# ─────────────────────────────────────────
# 圖表 9 — 檢索輪數分佈 & 冷熱資料
# ─────────────────────────────────────────
st.divider()
st.markdown("### 檢索輪數分佈 & 檢索資料冷熱區")
st.caption("主要受眾: `ML Engineer`　｜　資料來源: `chat_history`")

col_left, col_right = st.columns([1, 2], gap="xsmall")

# ── 左: 檢索輪數 histogram ──
with col_left:
    st.markdown("#### 每次對話的檢索輪數")
    if rounds_df.empty:
        st.info("尚無對話輪數資料。")
    else:
        hist_values = rounds_df["rounds"].value_counts().sort_index()
        bar_colors = [
            color_map["LIGHTBLUE"] if r <= 3 else color_map["ORANGE"] if r <= 5 else color_map["RED"]
            for r in hist_values.index
        ]

        fig_rounds = go.Figure(
            go.Bar(
                x=hist_values.index,
                y=hist_values.values,
                marker_color=bar_colors,
                text=hist_values.values,
                textposition="outside",
                hovertemplate="輪數: %{x}<br>Session 數: %{y}<extra></extra>",
            )
        )
        fig_rounds.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=340,
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis=dict(
                title="檢索輪數（同一 session 中 user 訊息數）", dtick=1, tickfont=dict(color=color_map["GRAY"])
            ),
            yaxis=dict(title="Session 數", tickfont=dict(color=color_map["GRAY"]), showgrid=False),
            font=dict(size=12, color=color_map["FONT_CLR"]),
        )
        st.plotly_chart(fig_rounds, width="stretch")

        st.info(f"平均輪數 {avg_rounds:.1f}")
        if avg_rounds > 3:
            st.warning("平均超過 3 輪才找到資料，建議檢查 rewriter 品質或 tag 覆蓋率。")

# ── 右: 冷熱資料 treemap ──
with col_right:
    st.markdown("#### 文件被檢索次數（冷熱資料）")
    if file_counts_df.empty:
        st.info("尚無文件檢索紀錄。")
    else:

        def heat_label(count):
            if count >= 15:
                return "🔥 熱門"
            elif count >= 5:
                return "🌤 中等"
            elif count >= 1:
                return "❄️ 冷門"
            return "🧊 凍得邦邦硬"

        file_counts_df["heat"] = file_counts_df["count"].apply(heat_label)
        # color_map_heat = {"🔥 熱門": color_map["RED"], "🌤 中等": color_map["ORANGE"],
        #                   "❄️ 冷門": color_map["LIGHTBLUE"], "🧊 凍得邦邦硬": color_map["GRAY"]}

        # 避免 treemap 顯示 count=0 的方塊消失
        treemap_df = file_counts_df.copy()
        treemap_df["display_count"] = treemap_df["count"].clip(lower=1)

        fig_tree = px.treemap(
            treemap_df,
            path=["heat", "file_name"],
            values="display_count",
            color="display_count",
            # color_discrete_map=color_map_heat,
            # https://plotly.com/python/builtin-colorscales/
            color_continuous_scale="viridis",
            color_continuous_midpoint=np.average(treemap_df["display_count"], weights=treemap_df["display_count"]),
            hover_data={"count": True, "days_since": True},
        )
        fig_tree.update_traces(
            textinfo="label+value",
            textposition="top center",
            hovertemplate=(
                "<b>%{label}</b><br>被檢索次數: %{customdata[0]}<br>距上次檢索: %{customdata[1]} 天<extra></extra>"
            ),
        )
        fig_tree.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=340,
            margin=dict(l=10, r=0, t=10, b=10),
            font=dict(size=14, color=color_map["FONT_CLR"], lineposition="under"),
        )
        st.plotly_chart(fig_tree, width="stretch")

        cold_files = file_counts_df[file_counts_df["count"] <= 2]
        if not cold_files.empty:
            st.info(
                f"有 {len(cold_files)} 份文件檢索次數 ≤ 2，可考慮調整 tags 增加 recall，"
                "或評估文件是否已經過時，從向量資料庫中移除。"
            )

# 冷資料明細表（可選展開）
with st.expander("📋 冷資料清單（檢索次數 ≤ 2 的文件）"):
    if file_counts_df.empty:
        st.info("尚無文件檢索紀錄。")
    else:
        cold = file_counts_df[file_counts_df["count"] <= 2][["file_name", "count", "days_since"]].rename(
            columns={"file_name": "檔案", "count": "檢索次數", "days_since": "距上次檢索(天)"}
        )

        if cold.empty:
            st.success("目前沒有冷資料~")
        else:
            st.dataframe(cold, width="stretch", hide_index=True)


# ─────────────────────────────────────────
# 圖表 10 — 檢索品質健康度（滿意度代理指標）
# ─────────────────────────────────────────
st.divider()
st.markdown("### 整體檢索品質健康度（滿意度代理指標）")
st.caption("主要受眾: `AI-PM`, `End-user`, `ML Engineer`　｜　資料來源: `chat_history`")

st.error(
    "💡 此面板使用 4 個可量化技術指標替代「使用者滿意度分數」，作為檢索階段的品質績效分數，"
    "但後續會逐漸改用 RAGAS 評測方式收斂「檢索」與「生成」階段的績效。"
)


def health_icon(val, good_threshold, bad_threshold, higher_is_better=True):
    """依門檻回傳 🟢🟡🔴；higher_is_better=False 時方向反轉（越低越好）。"""
    if higher_is_better:
        if val >= good_threshold:
            return "🟢"
        elif val >= bad_threshold:
            return "🟡"
        return "🔴"
    else:
        if val <= good_threshold:
            return "🟢"
        elif val <= bad_threshold:
            return "🟡"
        return "🔴"


rerank_val = satisfaction["rerank_top1_p50"]
rounds_val = satisfaction["avg_rounds"]
files_val = satisfaction["avg_note_files"]
trunc_val = satisfaction["truncation_rate"]

g1, g2, g3, g4 = st.columns(4)
g1.metric(
    f"{health_icon(rerank_val, 0.7, 0.5)} Rerank top-1 p50",
    f"{rerank_val:.2f}",
    help="最相關結果的 rerank score 中位數。≥ 0.7 為健康，但後續報告建議採用 RAGAS 進行"
    " recall & precision 打分更有穩健。",
)
g2.metric(
    f"{health_icon(rounds_val, 3.0, 4.0, higher_is_better=False)} 平均輪數",
    f"{rounds_val:.1f}",
    help="使用者平均幾輪找到需要的資料。≤ 3 為健康。",
)
g3.metric(
    f"{health_icon(files_val, 3.0, 5.0, higher_is_better=False)} 多文件發散度",
    f"{files_val:.1f}",
    help="每次回應平均參考幾份不同文件。≤3 為健康。太高代表可能切塊太細或是使用者提出刁鑽問題，"
    "但後續報告建議採用 RAGAS 進行 recall & precision 打分更有穩健。",
)
g4.metric(
    f"{health_icon(trunc_val, 5.0, 15.0, higher_is_better=False)} 回應截斷率",
    f"{trunc_val:.1f}%",
    help=f"content 長度達 {CONTENT_TRUNCATE_LIMIT} 字元上限的比例。≤5% 代表模型能力足夠應付使用者需求，"
    f"，但後續報告建議採用 RAGAS 進行 faithfulness & relevance 打分更有穩健。",
)

# ── Radar chart ──
categories = ["Rerank top-1\np50", "輪數效率\n(反向)", "發散度控制\n(反向)", "截斷率控制\n(反向)"]


def normalize(val, min_v, max_v, invert=False):
    """把 val 壓進 0–1；invert=True 時翻面，讓「越低越好」的軸統一成「越高越好」。"""
    normed = (val - min_v) / (max_v - min_v)
    normed = max(0, min(1, normed))
    return 1 - normed if invert else normed


radar_values = [
    normalize(rerank_val, 0.0, 1.0),
    normalize(rounds_val, 1.0, 7.0, invert=True),
    normalize(files_val, 1.0, 6.0, invert=True),
    normalize(trunc_val, 0.0, 30.0, invert=True),
]
radar_values_closed = radar_values + [radar_values[0]]
categories_closed = categories + [categories[0]]

fig_radar = go.Figure()
fig_radar.add_trace(
    go.Scatterpolar(
        r=radar_values_closed,
        theta=categories_closed,
        fill="toself",
        fillcolor="rgba(144,194,255,0.15)",
        line=dict(color=color_map["LIGHTBLUE"], width=2),
        name="目前狀態",
    )
)
# 健康基準線（0.7 正規化值）
fig_radar.add_trace(
    go.Scatterpolar(
        r=[0.7] * 5,
        theta=categories_closed,
        line=dict(color=color_map["GREEN"], width=1, dash="dash"),
        name="健康基準",
        fill=None,
    )
)
fig_radar.update_layout(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    polar=dict(
        bgcolor="rgba(255,255,255,0.03)",
        radialaxis=dict(visible=True, range=[0, 1], showticklabels=False, gridcolor=color_map["WHITE"]),
        angularaxis=dict(tickfont=dict(color=color_map["FONT_CLR"], size=12), gridcolor=color_map["WHITE"]),
    ),
    height=380,
    margin=dict(l=60, r=60, t=40, b=40),
    legend=dict(orientation="h", yanchor="bottom", y=1.05, font=dict(color=color_map["FONT_CLR"])),
    font=dict(size=13, color=color_map["FONT_CLR"]),
)
st.plotly_chart(fig_radar, width="stretch")

with st.expander("💡 各指標判定標準"):
    st.markdown(
        """
| 指標 | 🟢 健康 | 🟡 注意 | 🔴 需處理 | 計算方式 |
|---|---|---|---|---|
| Rerank top-1 p50 | ≥ 0.70 | 0.50 – 0.69 | < 0.50 | `retrieved_chunks[0].rerank_score` 的中位數 |
| 平均輪數 | ≤ 3.0 | 3.1 – 4.0 | > 4.0 | 同 session 中 `role=user` 的訊息數平均 |
| 多文件發散度 | ≤ 3.0 | 3.1 – 5.0 | > 5.0 | `note_files` 長度平均 |
| 回應截斷率 | ≤ 5.0% | 5.1% – 15.0% | > 15% | `content` 長度 ≥ 2000 的比例 |
"""
    )

with st.expander("💡 解讀提示"):
    st.markdown(
        "**雷達圖的綠色虛線**是粗估的健康基準（0.7 正規化值）。\n\n"
        "如果藍色區域在某個軸向內縮到虛線以內，代表該指標需要改善。"
        "四個軸都超過虛線時，AI-PM 可以有信心地說「系統品質達標」，"
        "而不只是根據使用者滿意度高低來「感覺」系統可上線。\n\n"
        "**補充建議**: 若日後想追蹤多輪對話離題程度，可在 RAG agent 的 "
        "`save_chat_history()` 中新增 `session_topic_drift_score` 欄位，"
        "用第一輪 `rewritten_query` embedding 與當前輪的 cosine distance 來量化。"
    )
