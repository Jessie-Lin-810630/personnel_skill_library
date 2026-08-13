"""攝取品質頁（Ingestion & Data Quality），呈現關卡 1→3 的資料攝取健康度。

由上而下組裝四段：KPI 四卡（total/archived/rejected/embedded）→ 圖表 1 筆記
生命週期漏斗 → 圖表 2 archived vs rejected 標籤分佈 → 圖表 4 LLM token 累計與
cache hit rate。資料來自 MongoDB notes_summary 與 multimodal_llm_enrichment_logs
兩張表，查詢封裝於 utils.interact_with_mongodb，DB 結果以 st.cache_data 快取。

Usage:
    poetry run streamlit run dashboard_ui/app.py
"""

from collections import Counter

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
from utils.interact_with_mongodb import (
    get_db_atlas,
    get_enrichment_logs,
    get_notes_summary_snapshots,
    get_onenote_attachment_dismatch,
)
from utils.ui_elements import color_map, render_side_bar

# ─────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────
st.set_page_config(
    page_title="Data Ingestion Quality",
    page_icon="⚡️",
    layout="wide",
    initial_sidebar_state="expanded",
)
render_side_bar()

# ─────────────────────────────────────────
# 色票 — 沿用全站 color_map，另補語意用的綠(好)/紅(壞)
# ─────────────────────────────────────────
C_BLUE = color_map["LIGHTBLUE"]
C_GREEN = color_map["GREEN"]
C_RED = color_map["RED"]
C_PURPLE = color_map["PURPLE"]
C_AMBER = color_map["ORANGE"]
C_GRAY = color_map["GRAY"]
FONT = color_map["FONT_CLR"]

# ─────────────────────────────────────────
# metric 卡片
# ─────────────────────────────────────────
st.markdown(
    """
    <style>
    [data-testid="stMetricValue"] { font-size: 2.2rem !important; }
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
@st.cache_data(ttl=600)
def _load_notes_snapshots() -> list[dict]:
    """讀取 notes_summary 最新兩筆快照並快取十分鐘，供 KPI 卡片與生命週期漏斗使用。

    上游快照為週頻更新，十分鐘的快取時間已足夠反映最新狀態。

    Returns:
        依 snapshot_date 由新到舊排序的快照文件清單，最多兩筆；無資料時為空 list。
    """
    return get_notes_summary_snapshots(get_db_atlas())


@st.cache_data(ttl=600)
def _load_enrichment_logs() -> pd.DataFrame:
    """讀取 LLM enrichment 的成功紀錄並快取十分鐘，供 token 累計量與快取命中率圖表使用。

    Returns:
        含 timestamp、各項 token 數、cache_hit 與 latency_ms 的 DataFrame；無資料時為空 DataFrame。
    """
    return get_enrichment_logs(get_db_atlas())


@st.cache_data(ttl=600)
def _load_attachment_dismatch() -> list[dict]:
    """讀取 OneNote 筆記的附件遺失統計並快取十分鐘，供附件遺失量長條圖使用。

    Returns:
        每組含 status、embedded_status 與遺失附件統計的 dict 清單；無資料時為空 list。
    """
    return get_onenote_attachment_dismatch(get_db_atlas())


snapshots = _load_notes_snapshots()
if not snapshots:
    st.warning("尚無 notes_summary 快照資料，請先執行 task01 / task07 的 summary 快照。")
    st.stop()

latest = snapshots[0]
previous = snapshots[1] if len(snapshots) > 1 else None


def _delta(field: str):
    """計算指定欄位在最新快照與前一筆快照之間的環比變化量。

    只有一筆快照時無從比較，回傳 None 讓 KPI 卡片不顯示變化箭頭。

    Args:
        field: 要比較的快照欄位名稱。

    Returns:
        int | None: 兩筆快照的差值；沒有前一筆快照時為 None。
    """
    if previous is None:
        return None
    return latest.get(field, 0) - previous.get(field, 0)


# 雙 y 軸等高用：把最大值向上取到 unit 的倍數，dtick 由 N_TICKS 平均切
Y_TICKS = 5


def _nice_ceiling(value: float, unit: int) -> int:
    """把數值換算成刻度上界，供雙 y 軸設定等距刻度時對齊格線。

    以級距為單位取整後再多留 20 個級距，讓資料點不會頂到圖表上緣。
    數值為零或負值時直接回傳一個級距，避免上界落在零而畫不出刻度。

    Args:
        value: 該軸資料的最大值。
        unit: 刻度級距。

    Returns:
        級距的整數倍，作為該軸的刻度上界。
    """
    if value <= 0:
        return unit
    return (int(value // unit) + 20) * unit


# ─────────────────────────────────────────
# 標題
# ─────────────────────────────────────────
snapshot_label = latest["snapshot_date"].strftime("%Y-%m-%d") if latest.get("snapshot_date") else "—"
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
    檢索系統品質與進度監控儀表板<br>Data Ingestion Quality
    </h1>
    <p style="color:{color_map["GRAY"]}; font-size:1rem; margin:0; letter-spacing:0.5px; font-weight:500;">
        最近更新日：{snapshot_label}
    </p>
</div>
""",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────
# KPI 四卡
# ─────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
k1.metric(
    "📓 Total documents",
    latest.get("total_notes", 0),
    delta=_delta("total_notes"),
    delta_color="normal" if (_delta("total_notes") != 0) else "off",
    delta_arrow="auto" if (_delta("total_notes") != 0) else "off",
    delta_description="份 vs. last week",
    help="Obsidian + OneNote 元數據表中記載的所有歸檔與被退件之筆記總數",
)
k2.metric(
    "✅ Archived documents",
    latest.get("archived_notes", 0),
    delta=_delta("archived_notes"),
    delta_color="normal" if (_delta("archived_notes") != 0) else "off",
    delta_arrow="auto" if (_delta("archived_notes") != 0) else "off",
    delta_description="份 vs. last week",
    help="已被歸檔的 Obsidian / OneNote 的文件數",
)
k3.metric(
    "🚫 Rejected documents",
    latest.get("rejected_notes", 0),
    delta=_delta("rejected_notes"),
    delta_color="normal" if (_delta("rejected_notes") != 0) else "off",
    delta_arrow="auto" if (_delta("rejected_notes") != 0) else "off",
    delta_description="份 vs. last week",
    help="被退件的 Obsidian / OneNote 的文件數（越少越好）",
)
k4.metric(
    "🧬 Embedded documents",
    latest.get("embedded_notes", 0),
    delta=_delta("embedded_notes"),
    delta_color="normal" if (_delta("embedded_notes") != 0) else "off",
    delta_arrow="auto" if (_delta("embedded_notes") != 0) else "off",
    delta_description="份 vs. last week",
    help="已進入向量資料庫的文件數",
)


# ─────────────────────────────────────────
# 圖表 1 — 筆記生命週期漏斗
# ─────────────────────────────────────────
st.divider()

funnel_stages = ["Total documents", "Archived documents", "Embedded documents"]
funnel_values = [
    latest.get("total_notes", 0),
    latest.get("archived_notes", 0),
    latest.get("embedded_notes", 0),
]

fig_funnel = go.Figure(
    go.Funnel(
        y=funnel_stages,
        x=funnel_values,
        textinfo="value+percent initial",
        textfont=dict(color=color_map["WHITE"]),
        marker=dict(color=[color_map["LIGHTBLUE"], color_map["GREEN"], color_map["PURPLE"]]),
        connector=dict(line=dict(color=color_map["GRAY"], width=1)),
    )
)
fig_funnel.update_layout(
    paper_bgcolor="rgba(0,0,0,0)",  # 代表完全透明 (Alpha = 0)
    plot_bgcolor="rgba(0,0,0,0)",
    height=280,
    margin=dict(l=20, r=10, t=10, b=10),
    font=dict(size=16, color=color_map["FONT_CLR"]),
)
# rejected 不在漏斗主幹，另用箭頭標注
fig_funnel.add_annotation(
    x=latest.get("rejected_notes", 0),
    y="Total notes",
    text=f"Rejected: {latest.get('rejected_notes', 0)}",
    showarrow=True,
    arrowhead=2,
    xshift=20,
    yshift=90,
    ax=50,
    ay=-10,
    font=dict(color=color_map["RED"], size=12),
    arrowcolor=color_map["RED"],
)
# ── 附件遺失量堆疊長條圖：OneNote 各狀態筆記依「失效張數」堆疊計數 ──
# 三種狀態 → x 軸標籤；(status, embedded_status) 對應如下（無 rejected+embedded=true）
CAT_MAP = {
    ("archived", False): "archived (未embed)",
    ("archived", True): "archived (已embed)",
    ("rejected", False): "rejected",
}
X_ORDER = ["archived (未embed)", "archived (已embed)", "rejected"]
# 每個狀態：{失效張數: 筆記篇數}
per_cat: dict[str, Counter] = {c: Counter() for c in X_ORDER}
for row in _load_attachment_dismatch():
    cat = CAT_MAP.get((row.get("status"), row.get("embedded_status")))
    if cat is None:
        continue
    for v in row.get("dismatched_img_count") or []:
        if v:  # 略過 0 / None（該篇無附件遺失）
            per_cat[cat][int(v)] += 1

loss_levels = sorted({k for cnt in per_cat.values() for k in cnt})
# 失效張數越多，顏色越偏警示
LOSS_COLORS = [C_BLUE, C_PURPLE, C_AMBER, C_RED]

fig_dismatch = go.Figure()
for i, k in enumerate(loss_levels):
    fig_dismatch.add_trace(
        go.Bar(
            x=X_ORDER,
            y=[per_cat[c][k] for c in X_ORDER],
            name=f"失效 {k} 張",
            marker_color=LOSS_COLORS[min(i, len(LOSS_COLORS) - 1)],
            hovertemplate="%{x}<br>失效 " + str(k) + " 張: %{y} 篇<extra></extra>",
        )
    )
fig_dismatch.update_layout(
    barmode="stack",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=280,
    margin=dict(l=20, r=20, t=10, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(color=FONT, size=12)),
    font=dict(size=14, color=FONT),
    xaxis=dict(tickfont=dict(color=C_GRAY), showgrid=False),
    yaxis=dict(title_text="筆記篇數", tickfont=dict(color=C_GRAY), showgrid=False),
)

# ── 並排：左漏斗 / 右附件遺失量 ──
fn_col, ds_col = st.columns([2, 1], gap="xsmall")
with fn_col:
    st.markdown("### 最新知識庫文件生命週期追蹤")
    st.caption("主要受眾: `AI-PM`, `Data Engineer`　｜　資料來源: `notes_summary`, `onenote_note_metadata`")
    st.plotly_chart(fig_funnel, width="stretch")
with ds_col:
    st.markdown("### 文件的附件完整度")
    if loss_levels:
        st.plotly_chart(fig_dismatch, width="stretch")
    else:
        st.info("目前 ingestion 階段沒有發生附件遺失的文件。")

with st.expander("💡 解讀提示"):
    st.markdown(
        "**左圖**漏斗每一層的百分比代表相對於 Total documents 的留存率。"
        "如果 **Archived documents 進入 Embedded documents** 的折損率過高，"
        "代表向量化流程可能有錯誤需要檢查。\n\n"
        "**右圖**堆疊每一段代表「失效 N 張附件」的筆記篇數，"
        "用來檢視 OneNote 附件在歸檔／向量化過程的遺失情況。"
    )


# ─────────────────────────────────────────
# 圖表 2 — Archived vs Rejected Tag 分佈
# ─────────────────────────────────────────
st.divider()
st.markdown("### Archived documents 與 Rejected documents 的 tags 分佈")
st.caption(
    "主要受眾: `AI-PM`, `Data Engineer`, `End-user`　｜　資料來源: `notes_summary.by_tag_in_archived/rejected_notes`"
)

archived_tags: dict = latest.get("by_tag_in_archived_notes", {}) or {}
rejected_tags: dict = latest.get("by_tag_in_rejected_notes", {}) or {}
union_tags = set(archived_tags) | set(rejected_tags)


def _build_tag_diverging_fig(display_tags: list[str]) -> go.Figure:
    """繪製標籤分佈的分歧長條圖，比較同一個標籤在歸檔與退件文件中的出現次數。

    歸檔數以綠色畫在中軸右側，退件數以紅色畫在中軸左側。
    左右兩側先取共同的最大值再向上進位到級距的倍數，讓兩側刻度對稱，
    軸標籤則取絕對值顯示，避免左側出現負數。

    Args:
        display_tags: 要顯示的標籤清單，由上而下依序排列。

    Returns:
        已套用全站配色與版面設定的分歧長條圖物件，高度依標籤數量調整。
    """
    # 先算左右兩側的最大值，決定對稱刻度範圍
    step = 4
    max_abs = max(
        max((archived_tags.get(t, 0) for t in display_tags), default=0),
        max((rejected_tags.get(t, 0) for t in display_tags), default=0),
    )
    max_tick = int((max_abs // step + 1) * step)  # 向上取到 step 的倍數
    tickvals = list(range(-max_tick, max_tick + 1, step))  # [-8, ..., 0, ..., 8]
    ticktext = [str(abs(v)) for v in tickvals]  # ['8', ..., '0', ..., '8']

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=display_tags,
            x=[-rejected_tags.get(t, 0) for t in display_tags],
            name="出現在退件文件中",
            orientation="h",
            marker_color=color_map["RED"],
            text=[rejected_tags.get(t, 0) for t in display_tags],
            textposition="inside",
            hovertemplate="Tag: %{y}<br>Rejected: %{text}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            y=display_tags,
            x=[archived_tags.get(t, 0) for t in display_tags],
            name="出現在歸檔文件中",
            orientation="h",
            marker_color=color_map["GREEN"],
            text=[archived_tags.get(t, 0) for t in display_tags],
            textposition="inside",
            hovertemplate="Tag: %{y}<br>Archived: %{text}<extra></extra>",
        )
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=10, b=40),
        barmode="relative",
        height=50 + len(display_tags) * 36,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, font_size=16, font=dict(color=color_map["FONT_CLR"])),
        xaxis=dict(
            title="使用該 tag 的文件數量",
            tickvals=tickvals,  # [-8, ..., 0, ..., 8]
            ticktext=ticktext,  # ['8', ..., '0', ..., '8']
            zeroline=True,
            zerolinewidth=1.5,
            zerolinecolor=color_map["GRAY"],
            showgrid=False,
            tickfont=dict(color=color_map["GRAY"]),
        ),
        yaxis=dict(autorange="reversed", tickfont=dict(color=color_map["FONT_CLR"])),
        font=dict(size=13, color=color_map["FONT_CLR"]),
    )
    return fig


if not union_tags:
    st.info("最新快照沒有標籤分佈資料。")
else:
    # Slider 控制兩張圖各自顯示前 N 名
    top_n = st.slider(
        "選擇要顯示前 N 名高頻出現的 tags",
        min_value=min(5, len(union_tags)),
        max_value=min(10, len(union_tags)),
        value=min(10, len(union_tags)),
        key="tag_slider",
    )
    archived_sorted = sorted(union_tags, key=lambda t: archived_tags.get(t, 0), reverse=True)[:top_n]
    rejected_sorted = sorted(union_tags, key=lambda t: rejected_tags.get(t, 0), reverse=True)[:top_n]

    col_21, col_22 = st.columns(2)
    with col_21:
        st.markdown("#### 1 · 依已歸檔文件群的高頻 tags 排序")
        st.plotly_chart(_build_tag_diverging_fig(archived_sorted), width="stretch")
    with col_22:
        st.markdown("#### 2 · 依已退件文件群的高頻 tags 排序")
        st.plotly_chart(_build_tag_diverging_fig(rejected_sorted), width="stretch")

with st.expander("💡 解讀提示"):
    st.markdown(
        "(1) 如果某個 tag **只出現在已退件的一側**（紅色）而從未出現在已歸檔的一側（綠色），"
        "表示帶該 tag 的筆記品質可能系統性偏低、或是 tag 不應該出現在業務單位的資料字典，"
        "需要檢視 LLM 語意擴寫關卡或人工審查標準是否需調整。"
    )
    st.markdown(
        "(2) 相近但未合併的 tag（如 `docker` vs `dockerize`）也會在這張圖上暴露，"
        "此時應調整業務單位的資料字典，減少知識庫的文檔的語意發散程度。"
    )


# ─────────────────────────────────────────
# 圖表 4 — LLM Token 累計 & Cache Hit Rate
# ─────────────────────────────────────────
st.divider()
st.markdown("### LLM enrichment token 累計 & cache hit rate")
st.caption("主要受眾: `Data Engineer`　｜　資料來源: `multimodal_llm_enrichment_logs`")

enrichment_df = _load_enrichment_logs()

if enrichment_df.empty:
    st.info("尚無 multimodal_llm_enrichment_logs 紀錄，無法繪製 token 趨勢。")
else:
    # 按日彙總
    df = enrichment_df.copy()
    df["date"] = pd.to_datetime(df["timestamp"]).dt.date
    daily = (
        df.groupby("date")
        .agg(
            daily_tokens=("total_tokens", "sum"),
            daily_input_tokens=("input_tokens", "sum"),
            daily_output_tokens=("output_tokens", "sum"),
            total_calls=("cache_hit", "count"),
            cache_hits=("cache_hit", "sum"),
            p50_latency=("latency_ms", "median"),
        )
        .reset_index()
    )
    daily["cumulative_totaltokens"] = daily["daily_tokens"].cumsum()
    daily["cache_hit_rate"] = (daily["cache_hits"] / daily["total_calls"] * 100).round(1)

    # 上方小 metric
    m1, m2, m3 = st.columns(3)
    m1.metric("Total tokens 累計", f"{int(daily['cumulative_totaltokens'].iloc[-1]):,}")
    m2.metric("平均 cache hit rate", f"{daily['cache_hit_rate'].mean():.1f}%")
    m3.metric("LLM latency 中位數", f"{daily['p50_latency'].median():,.0f} ms")

    # 雙軸圖
    fig_token = make_subplots(specs=[[{"secondary_y": True}]])

    fig_token.add_trace(
        go.Scatter(
            x=daily["date"],
            y=daily["cumulative_totaltokens"],
            name="Cumulative total tokens",
            mode="lines+markers",
            line=dict(color=color_map["LIGHTBLUE"], width=2),
            marker=dict(size=8),
            hovertemplate="日期: %{x}<br>累計 tokens: %{y:,}<extra></extra>",
        ),
        secondary_y=False,
    )
    fig_token.add_trace(
        go.Scatter(
            x=daily["date"],
            y=daily["cache_hit_rate"],
            name="Cache hit rate %",
            mode="lines+markers",
            line=dict(color=color_map["GREEN"], width=2, dash="dash"),
            marker=dict(size=8),
            hovertemplate="日期: %{x}<br>Cache hit: %{y:.1f}%<extra></extra>",
        ),
        secondary_y=True,
    )
    fig_token.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=10, b=10),
        height=350,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.1, xanchor="center", x=0.46, font=dict(color=color_map["FONT_CLR"])
        ),
        font=dict(size=13, color=color_map["FONT_CLR"]),
        xaxis=dict(tickfont=dict(color=color_map["GRAY"]), showgrid=False),
    )
    # 雙軸各切 Y_TICKS 段（各 Y_TICKS+1 條刻度線），確保左右等高對齊
    cum_top = _nice_ceiling(max(daily["cumulative_totaltokens"]), 1000)
    fig_token.update_yaxes(
        title_text="Cumulative toal tokens",
        secondary_y=False,
        range=[0, cum_top],
        dtick=cum_top / Y_TICKS,
        tickfont=dict(color=color_map["GRAY"]),
        showgrid=True,
    )
    fig_token.update_yaxes(
        title_text="Cache hit rate %",
        secondary_y=True,
        range=[0, 100],
        dtick=100 / Y_TICKS,
        tickfont=dict(color=color_map["GRAY"]),
        showgrid=False,
    )
    st.plotly_chart(fig_token, width="stretch")

    with st.expander("📊 每日 token 使用量 & latency 明細", expanded=True):
        # 逐日 input/output 佔比，供 hover 顯示
        io_total = (daily["daily_input_tokens"] + daily["daily_output_tokens"]).replace(0, pd.NA)
        pct_in = (daily["daily_input_tokens"] / io_total * 100).fillna(0)
        pct_out = (daily["daily_output_tokens"] / io_total * 100).fillna(0)

        fig_daily = make_subplots(specs=[[{"secondary_y": True}]])
        fig_daily.add_trace(
            go.Bar(
                x=daily["date"],
                y=daily["daily_input_tokens"],
                name="Input tokens",
                marker_color=color_map["SKYBLUE"],
                customdata=pct_in,
                hovertemplate="日期: %{x}<br>Input: %{y:,} (%{customdata:.1f}%)<extra></extra>",
            ),
            secondary_y=False,
        )
        fig_daily.add_trace(
            go.Bar(
                x=daily["date"],
                y=daily["daily_output_tokens"],
                name="Output tokens",
                marker_color=color_map["PURPLE"],
                customdata=pct_out,
                hovertemplate="日期: %{x}<br>Output: %{y:,} (%{customdata:.1f}%)<extra></extra>",
            ),
            secondary_y=False,
        )
        fig_daily.add_trace(
            go.Scatter(
                x=daily["date"],
                y=daily["p50_latency"],
                name="Latency p50 (ms)",
                mode="lines+markers",
                line=dict(color=color_map["ORANGE"], width=1.5),
                marker=dict(size=8),
            ),
            secondary_y=True,
        )
        fig_daily.update_layout(
            barmode="stack",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=20, r=20, t=10, b=20),
            height=260,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(color=color_map["FONT_CLR"])),
            font=dict(size=12, color=color_map["FONT_CLR"]),
            xaxis=dict(tickfont=dict(color=color_map["GRAY"]), showgrid=False),
        )
        # 雙軸各切 Y_TICKS 段，左右刻度線等高對齊
        tok_top = _nice_ceiling(max(daily["daily_tokens"]), 1000)
        lat_top = _nice_ceiling(max(daily["p50_latency"]), 1000)
        fig_daily.update_yaxes(
            title_text="Tokens",
            secondary_y=False,
            range=[0, tok_top],
            dtick=tok_top / Y_TICKS,
            tickfont=dict(color=color_map["GRAY"]),
            showgrid=True,
        )
        fig_daily.update_yaxes(
            title_text="Latency ms",
            secondary_y=True,
            range=[0, lat_top],
            dtick=lat_top / Y_TICKS,
            tickfont=dict(color=color_map["GRAY"]),
            showgrid=False,
        )
        st.plotly_chart(fig_daily, width="stretch")

    with st.expander("💡 解讀提示"):
        st.markdown(
            "**累計 token 線**持續攀升是正常的，但斜率突然變陡代表有大量新筆記同時觸發 enrichment。\n\n"
            "**Cache hit rate** 理想值 > 30%，代表相同 `html_sha_hash` 的筆記不會重複呼叫 LLM。"
            "如果 cache hit rate 長期偏低，檢查 `html_sha_hash` 是否因為 OneNote API 回傳的 HTML "
            "每次都有微小差異而導致 hash 變動。"
        )
