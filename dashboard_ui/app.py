import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import textwrap
from utils import interact_with_mongodb as mongo_utils
from utils.precomputing import (_format_delta,
                                _format_update_date,
                                _latest_date_from_df,
                                _show_updated_at,
                                _format_radar_label,
                                _radar_tasks_from_df,
                                _github_repos_for_cards,
                                _percent_to_counts)
from utils.ui_elements import (_render_side_bar,
                               _render_task_detail,
                               make_radar,
                               color_map)


# 用 st.cache_resource 儲存連線物件在快取層，避免反覆建立連線
@st.cache_resource
def get_mongo_db():
    from utils.interact_with_mongodb import get_db
    return get_db()


db = get_mongo_db()

# ─────────────────────────────────────────
# 讀取 MongoDB 資料
# ─────────────────────────────────────────

# —— A: 雷達圖資料 ——
radar_df = mongo_utils.get_radar_summary_df(db, "skill_radar_summary")
bio_radar_sum_df = radar_df[radar_df["雷達圖名稱"].str.contains("生技", na=False)]
de_radar_sum_df = radar_df[radar_df["雷達圖名稱"].str.contains("資料工程", na=False)]
biotech_updated_at = _latest_date_from_df(bio_radar_sum_df)
de_updated_at = _latest_date_from_df(de_radar_sum_df)

biotech_labels = [_format_radar_label(label) for label in bio_radar_sum_df["雷達軸"].to_list()]
biotech_values = bio_radar_sum_df["level"].to_list()
de_labels = [_format_radar_label(label) for label in de_radar_sum_df["雷達軸"].to_list()]
de_values = de_radar_sum_df["level"].to_list()

bio_radar_detail_df = mongo_utils.get_a_radar_detail(db, "skill_scores_biotech")
de_radar_detail_df = mongo_utils.get_a_radar_detail(db, "skill_scores_data_eng")
biotech_tasks = _radar_tasks_from_df(bio_radar_detail_df)
de_tasks = _radar_tasks_from_df(de_radar_detail_df)

# —— B: KPI ——
obsidian_total, obsidian_delta_raw, obsidian_topics, obsidian_updated_at = (
    mongo_utils.get_obsidian_kpi(db, "obsidian_summary"))
github_total, github_delta_raw, github_updated_at = (mongo_utils.get_github_kpi(
    db, "github_summary"))
problem_kpi = mongo_utils.get_problem_kpi_donut(db, "ccClub&leetcode_summary")
obsidian_updated_at = _format_update_date(obsidian_updated_at)
github_updated_at = _format_update_date(github_updated_at)
problem_updated_at = _format_update_date(problem_kpi["snapshot_date"])

leetcode_sql = problem_kpi["leetcode_sql"]
leetcode_python = problem_kpi["leetcode_python"]
ccclub_total = problem_kpi["ccclub_total"]
obsidian_delta = _format_delta(
    obsidian_delta_raw, f" nodes | 最近更新日期：{obsidian_updated_at}")
github_delta = _format_delta(
    github_delta_raw, f" repos | 最近更新日期：{github_updated_at}")
leetcode_sql_delta = _format_delta(
    problem_kpi["leetcode_sql_delta"], f"｜最近更新日期：{problem_updated_at}")
leetcode_python_delta = _format_delta(
    problem_kpi["leetcode_python_delta"], f"｜最近更新日期：{problem_updated_at}")

# —— C: GitHub 最近專案 ——
recent_repos = _github_repos_for_cards(mongo_utils.get_github_detail(db, "github_repos"))

# —— D: 刷題三相 donut ——
donut_labels = ["ccClub Python", "LeetCode SQL", "LeetCode Python"]
donut_values = [ccclub_total, leetcode_sql, leetcode_python]

# —— E: 各相的題目特徵資料 ——
problem_features = mongo_utils.get_problem_features(db, "ccClub&leetcode_summary")
leetcode_total = leetcode_sql + leetcode_python
topic_features = {"LeetCode SQL": _percent_to_counts(problem_features.get("LeetCode", {}),
                                                     leetcode_total, include={"Database"}
                                                     ),
                  "LeetCode Python": _percent_to_counts(problem_features.get("LeetCode", {}),
                                                        leetcode_total, exclude={"Database"}
                                                        ),
                  "ccClub Python": _percent_to_counts(problem_features.get("ccClub-Python", {}),
                                                      ccclub_total
                                                      ),
                  }

# ─────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────
st.set_page_config(page_title="Jessie Lin技能儀表與知識庫",
                   page_icon="⚡️",
                   layout="wide",
                   initial_sidebar_state="expanded",
                   )
_render_side_bar()

# ─────────────────────────────────────────
# 最小化 CSS（只做 streamlit 預設元件微調）
# ─────────────────────────────────────────
st.markdown("""
            <style>
            /* 移除 Streamlit 預設上方留白 */
            .block-container { padding-top: 2rem; padding-bottom: 2rem; }
            /* metric 數值字體放大 */
            [data-testid="stMetricValue"] { font-size: 2.5rem !important; }
            /* KPI 卡片底色 */
            [data-testid="stMetric"] {
                background: #55575AD8;
                border-radius: 12px;
                padding: 1rem 1.2rem;
                border: 1px solid #2a3550;
            }
            </style>
            """,
            unsafe_allow_html=True)


plotly_layout_base = dict(
    paper_bgcolor="rgba(0,0,0,0)",  # 代表完全透明 (Alpha = 0)
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=color_map["FONT_CLR"], family="sans-serif"),
    margin=dict(l=10, r=10, t=30, b=10),
)

# ─────────────────────────────────────────
# 標題
# ─────────────────────────────────────────
st.markdown(f"""
<div style="
    background: linear-gradient(135deg, #0d1526 0%, #1a2a4a 100%);
    border-radius: 16px;
    padding: 2.5rem 3rem;
    margin-bottom: 1.5rem;
    border: 1px solid #2a3550;
    text-align: center;
">
    <p style="color:#7a9cc0; font-size:0.95rem; margin:0 0 0.3rem 0; letter-spacing:3px;">
        PERSONAL SKILLS DASHBOARD
    </p>
    <h1 style="color:#e0e8f8; font-size:2.6rem; margin:0 0 0.5rem 0; font-weight:800;">
        Jessie Lin 生技製藥 x 資料工程雙棲夢
    </h1>
    <p style="color:{color_map["TEAL"]}; font-size:1.1rem; margin:0 0 1.5rem 0; letter-spacing:1px;">
        我是 Jessie，一個沈浸8年生技製藥產業，領悟對數據的熱忱，並且在未來10年追求極致有效率的資料治理工程的化工人。<br>
        這裡紀錄著我的學習歷程、工作產出，與知識庫。
    </p>
    <p style="color:{color_map["TEAL"]}; font-size:1.1rem; margin:0 0 1.5rem 0; letter-spacing:1px;">
        <a href="https://github.com/Jessie-Lin-810630" 
        target="_blank" 
        style="color:#90c2ff; text-decoration:none;">
        Github
        </a>
        <a href="https://www.linkedin.com/in/shu-jyuan-lin-6195b8130" 
        target="_blank" 
        style="color:#90c2ff; text-decoration:none;">
          |  LinkedIn
    </p>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────
# SECTION 1 — 雙雷達圖
# ─────────────────────────────────────────
st.markdown("### 🚀 技能雷達")

# Level 說明 + 生技雷達並排
level_col, biotech_col, de_col = st.columns([0.6, 1.5, 1.5])

with level_col:
    st.markdown("##### 📊 Level 定義")
    level_defs = [
        ("Lv 1", "#96a8d0", "缺乏實操，純具備認知"),
        ("Lv 2", "#8292b6", "具備基本操作，部分狀況需照範本"),
        ("Lv 3", "#545f79", "能獨立實作，可自行初步故障排除"),
        ("Lv 4", "#535f79", "能構思完整架構，解釋設計選擇"),
        ("Lv 5", "#54607a", "能提出優化方向、成本控制、帶人理解"),
    ]
    for lv, clr, desc in level_defs:
        st.markdown(
            f'''<div style="
                display:flex; align-items:flex-start; gap:0.4rem;
                margin-bottom:0.9rem;
            ">
                <span style="
                    background:{clr}; color:#fff;
                    border-radius:5px; padding:2px 8px;
                    font-size:0.78rem; font-weight:700;
                    white-space:nowrap; min-width:38px; text-align:center;
                ">{lv}</span>
                <span style="color:#b0c4de; font-size:0.82rem; line-height:1.4;">{desc}</span>
            </div>''',
            unsafe_allow_html=True,
        )

with biotech_col:
    st.markdown("##### 💊 生技製藥技能雷達")
    _show_updated_at(biotech_updated_at)
    biotech_radar_event = st.plotly_chart(
        make_radar(biotech_labels,
                   biotech_values,
                   color_map["TEAL"],
                   "",
                   biotech_tasks),
        use_container_width=True,
        key="biotech_radar_chart",
        on_select="rerun",
        selection_mode="points",
    )
with de_col:
    st.markdown("##### 💻 資料工程技能雷達")
    _show_updated_at(de_updated_at)
    de_radar_event = st.plotly_chart(
        make_radar(de_labels,
                   de_values,
                   color_map["PURPLE"],
                   "",
                   de_tasks),
        use_container_width=True,
        key="de_radar_chart",
        on_select="rerun",
        selection_mode="points",
    )

detail_biotech_col, detail_de_col = st.columns(2)
with detail_biotech_col:
    _render_task_detail("💊 生技製藥任務明細", biotech_labels, biotech_tasks, biotech_radar_event, "biotech")
with detail_de_col:
    _render_task_detail("💻 資料工程任務明細", de_labels, de_tasks, de_radar_event, "de")

# ─────────────────────────────────────────
# (c) KPI 卡片 — 四格
# ─────────────────────────────────────────
st.markdown("### 📊 KPI 總覽")
k1, k2, k3, k4 = st.columns(4)

with k1:
    st.metric("📓 個人知識庫節點", obsidian_total, obsidian_delta)
with k2:
    st.metric("🐙 GitHub 專案", github_total, github_delta)
with k3:
    st.metric("👖 LeetCode SQL", leetcode_sql, leetcode_sql_delta)
with k4:
    st.metric("💻 LeetCode Python", leetcode_python, leetcode_python_delta)

st.markdown("<br>", unsafe_allow_html=True)

# ─────────────────────────────────────────
# SECTION 2 — Obsidian 技術主題橫向 bar chart
# ─────────────────────────────────────────
col_obs, col_lc = st.columns([3, 2])

with col_obs:
    df_obs = pd.DataFrame(
        {"topic": list(obsidian_topics.keys()),
         "count": list(obsidian_topics.values())}
    ).sort_values("count")

    colors = [color_map["PINK"] if c == df_obs["count"].max() else color_map["PURPLE"] for c in df_obs["count"]]

    fig_bar = go.Figure(go.Bar(x=df_obs["count"],
                               y=df_obs["topic"],
                               orientation="h",
                               marker_color=colors,
                               text=df_obs["count"],
                               textposition="outside",
                               textfont=dict(color=color_map["FONT_CLR"]),
                               ))
    fig_bar.update_layout(**plotly_layout_base,
                          title=dict(text="📚 知識文檔技術主題分佈",
                                     font=dict(size=18, color=color_map["FONT_CLR"]), x=0),
                          xaxis=dict(showgrid=False, zeroline=False,
                                     tickfont=dict(color="#4a6a8a")),
                          yaxis=dict(showgrid=False, tickfont=dict(color=color_map["FONT_CLR"])),
                          height=320,
                          )
    st.plotly_chart(fig_bar, use_container_width=True)

# ─────────────────────────────────────────
# SECTION 3 — 刷題三相 Donut
# ─────────────────────────────────────────
with col_lc:
    total_problems = sum(donut_values)
    fig_donut = go.Figure(go.Pie(
        labels=donut_labels,
        values=donut_values,
        hole=0.55,
        marker=dict(colors=[color_map["TEAL"], color_map["PURPLE"], color_map["ORANGE"]]),
        textfont=dict(color=color_map["WHITE"], size=12),
        hovertemplate="%{label}<br>%{value} 題 (%{percent})<extra></extra>",
    ))
    fig_donut.update_layout(
        **plotly_layout_base,
        title=dict(text="🏆 刷題三相分佈",
                   font=dict(size=18, color=color_map["FONT_CLR"]), x=0),
        annotations=[dict(
            text=f"<b>{total_problems}</b><br>總題數",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=15, color=color_map["FONT_CLR"]),
        )],
        showlegend=True,
        legend=dict(font=dict(color=color_map["FONT_CLR"]), orientation="h", y=-0.15),
        height=340,
    )

    st.plotly_chart(fig_donut, use_container_width=True, key="donut_chart")

# ─────────────────────────────────────────
# SECTION 4 — 題目特徵明細（下拉選單切換）
# ─────────────────────────────────────────
st.markdown("#### 🔍 題目特徵明細")

selected = st.selectbox(
    "選擇查看哪一刷題平台的題型分佈",
    options=donut_labels,
    index=0,
    key="phase_select",
)

badge_color = dict(zip(donut_labels,  [color_map["TEAL"], color_map["PURPLE"], color_map["ORANGE"]]))[selected]
phase_total = dict(zip(donut_labels, donut_values))[selected]
st.markdown(f'<span style="background:{badge_color};color:#fff;border-radius:6px;'
            f'padding:3px 14px;font-size:0.9rem;font-weight:700;">{selected}</span>'
            f'　共 <b>{phase_total}</b> 題',
            unsafe_allow_html=True,
            )
st.markdown("<br>", unsafe_allow_html=True)

# 建立 DataFrame
feat_data = topic_features[selected]
df_feat = (pd.DataFrame(feat_data.items(),
                        columns=["題目特徵", "題數"]
                        ).sort_values("題數", ascending=False).reset_index(drop=True)
           )
df_feat.index += 1       # 排名從 1 開始
total_feat = df_feat["題數"].sum()
df_feat["佔比 (%)"] = (df_feat["題數"] / total_feat * 100).round(1)

# 顯示範圍切換
view_mode = st.radio(
    "顯示範圍",
    options=["Top 1 - 5", "Top 5 - 10", "All"],
    index=0,
    horizontal=True,
    key="view_mode_radio",
)

if view_mode == "Top 1 - 5":
    df_show = df_feat.head(5)
elif view_mode == "Top 5 - 10":
    df_show = df_feat.tail(5)
else:
    df_show = df_feat

st.dataframe(
    df_show,
    use_container_width=True,
    column_config={
        "題數": st.column_config.ProgressColumn(
            "題數",
            min_value=0,
            max_value=int(df_feat["題數"].max()),
            format="%d 題",
        ),
        "佔比 (%)": st.column_config.NumberColumn("佔比 (%)", format="%.1f %%"),
    },
    hide_index=False,
)

# ─────────────────────────────────────────
# SECTION 5 - GitHub 最近三個專案卡片
# ─────────────────────────────────────────
st.markdown("### 🐙 GitHub 最近專案")
st.caption(f"左右滑動查看")
# 用一個 HTML 容器包所有卡片，overflow-x: auto 實現橫向捲動
cards_html = '''
<div style="
    display: flex;
    gap: 1rem;
    overflow-x: auto;
    padding-bottom: 0.8rem;
    scrollbar-width: thin;
    scrollbar-color: #2a3550 transparent;
">
'''

for repo in recent_repos:
    readme_display = repo["readme_url"].replace("https://", "").replace("github.com/", "")
    cards_html += f'''
<div style="
    min-width: 240px;
    max-width: 260px;
    flex-shrink: 0;
    background: {color_map["CARD_BG"]};
    border: 1px solid #2a3550;
    border-radius: 12px;
    padding: 1.1rem 1.3rem;
">
    <p style="color:{color_map["TEAL"]}; font-size:0.95rem; font-weight:700; margin:0 0 0.6rem 0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
        🗂 {repo["name"]}
    </p>
    <p style="color:#7a9cc0; font-size:0.8rem; margin:0 0 0.25rem 0;">
        Language: <span style="color:{color_map["FONT_CLR"]};">{repo["lang"]}</span>
    </p>
    <p style="color:#7a9cc0; font-size:0.8rem; margin:0 0 0.25rem 0;">
        Commits: <span style="color:{color_map["FONT_CLR"]}; font-weight:700;">{repo["commits"]}</span>
    </p>
    <p style="color:#7a9cc0; font-size:0.8rem; margin:0 0 0.5rem 0;">
        Last push: <span style="color:{color_map["FONT_CLR"]};">{repo["pushed"]}</span>
    </p>
    <a href="{repo["readme_url"]}" target="_blank" style="
        display:inline-block;
        font-size:0.75rem;
        color:{color_map["TEAL"]};
        text-decoration:none;
        border:1px solid {color_map["TEAL"]};
        border-radius:5px;
        padding:2px 8px;
        word-break:break-all;
    ">📄 README</a>
</div>
'''

cards_html += "</div>"
st.markdown(cards_html, unsafe_allow_html=True)

# ─────────────────────────────────────────
# Footer
# ─────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("""
<div style="text-align:center; color:#e0e8f8; font-size:1.1rem; padding:1rem 0;">
    Sources from Leetcode.com | 
    <a href="https://github.com/Jessie-Lin-810630" 
       target="_blank" 
       style="color:#90c2ff; text-decoration:none;">
       Github
    </a> | Personal Obsidian Vault | ccClub.io 💗 Feel free to reach out me on 
    <a href="https://www.linkedin.com/in/shu-jyuan-lin-6195b8130" 
       target="_blank" 
       style="color:#90c2ff; text-decoration:none;">
       LinkedIn
    </a>.
</div>
""", unsafe_allow_html=True)
