import streamlit as st
from utils.ui_elements import color_map, _render_side_bar

# ─────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────
st.set_page_config(page_title="Knowledge factory",
                   page_icon="⚡️",
                   layout="wide",
                   initial_sidebar_state="expanded",
                   )
_render_side_bar()

# ── 最小化 CSS：只設定背景色、字體、少量卡片樣式 ──
st.markdown("""
            <style>
            /* 移除 Streamlit 預設上方留白 */
            .block-container { padding-top: 2rem; padding-bottom: 2rem; }
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
    <h1 style="color:{color_map["FONT_CLR"]}; font-size:2.6rem; margin:0 0 0.5rem 0; font-weight:800;">
        Knowledge Factory
    </h1>
    <p style="color:{color_map["TEAL"]}; font-size:1.1rem; margin:0 0 1.5rem 0; letter-spacing:1px;">
        專案架構 — 不斷演進、不斷學習
    </p>
    <p style="color:{color_map["TEAL"]}; font-size:1.1rem; margin:0 0 1.5rem 0; letter-spacing:1px;">
        <a href="https://github.com/Jessie-Lin-810630"
        target="_blank"
        style="color:{color_map["LIGHTBLUE"]}; text-decoration:none;">
        Github
        </a>
        <a href="www.linkedin.com/in/shu-jyuan-lin-6195b8130"
        target="_blank"
        style="color:{color_map["LIGHTBLUE"]}; text-decoration:none;">
          |  LinkedIn
    </p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────
# SECTION 1 — 技術堆疊
# ─────────────────────────────────────────
st.header("🛠 Tech. Stack 技術堆疊")

stacks = [
    ("Frontend",        "Python-Streamlit"),
    ("Backend",         "Python, Python-Pymongo"),
    ("Database",        "MongoDB Atlas"),
    ("Container",       "Docker"),
    ("Cloud",           "Google Cloud: <br>Cloud Run Services, "
                        "<br>Cloud Run Jobs, GCS, "
                        "<br>Pub/Sub, Artifact Registry"),
    ("CI/CD",           "GitHub Actions"),
    ("AI Layer",        "TBD"),
    ("Tool Management", "pyenv, poetry"),
]

cols = st.columns(4)
for i, (cat, val) in enumerate(stacks):
    with cols[i % 4]:
        with st.container(border=False):
            st.markdown(
                f"""
                <div style="
                    background: #55575AD8;
                    border-radius: 12px;
                    padding: 1rem 1.5rem;
                    border: 1px solid #2a3550;
                    margin-bottom: 0.5rem;
                    min-height: 165px;
                ">
                    <strong style="
                        color:{color_map["WHITE"]};
                        font-size:1.2rem;
                        text-transform:uppercase;
                        letter-spacing:0.05em;
                    ">
                        {cat}
                    </strong>
                    <br>
                    <strong style="
                        color:{color_map["WHITE"]};
                        font-size:1rem;
                        line-height:1.6;
                        font-weight:600;
                    ">
                        {val}
                    </strong>
                </div>
                """,
                unsafe_allow_html=True
            )

# ─────────────────────────────────────────
# SECTION 2 — ETL Pipeline 總覽
# ─────────────────────────────────────────
st.header("⚙️ ETL Pipeline 數據管道 x 5")

ETL_TASKS = [
    {
        "icon": "📝", "title": "Obsidian ETL", "badge": "task01",
        "flow": "Obsidian Vault (.md) 遞迴掃描  →  frontmatter 解析  →  清洗  →  🗄 MongoDB",
        "tags": ["obsidian_notes", "obsidian_summary"],
    },
    {
        "icon": "🔀", "title": "GitHub ETL", "badge": "task02",
        "flow": "GitHub REST API  →  repo / commit metadata  →  README 摘要  →  🗄 MongoDB",
        "tags": ["github_repos", "github_summary"],
    },
    {
        "icon": "💻", "title": "LeetCode & ccClub ETL", "badge": "task03",
        "flow": "LeetCode GraphQL API & ccClub REST API →  刷題紀錄 → 清洗  →  🗄 MongoDB",
        "tags": ["solved_problems_on_ccClub", "solved_problems_on_leetcode", "ccClub&leetcode_summary"],
    },
    {
        "icon": "📊", "title": "Skill Radar ETL", "badge": "task05",
        "flow": "Google Sheets  →  Sheets API  →  技能分數  →  雷達圖數據  →  🗄 MongoDB",
        "tags": ["skill_scores_biotech", "skill_scores_data_eng", "skill_radar_summary"],
    },
    {
        "icon": "🧠", "title": "Vector Embedding ETL", "badge": "task06",
        "flow": "Obsidian Vault (content)  →  文檔切塊  →  text-embedding-004  →  向量化  →  🗄 MongoDB Atlas",
        "tags": ["obsidian_vectors", "obsidian_metadata", "chat_history"],
    },
]

for task in ETL_TASKS:
    with st.container(border=True):
        col_icon, col_body = st.columns([0.05, 0.95])
        with col_icon:
            st.markdown(f"<div style='font-size:1.8rem;margin-top:4px'>{task['icon']}</div>",
                        unsafe_allow_html=True)
        with col_body:
            st.markdown(
                f"**{task['title']}** &nbsp;"
                f"<span class='mono' style='background:#1c2333;border:1px solid #30363d;"
                f"border-radius:4px;padding:1px 7px;color:#8b949e'>{task['badge']}</span>",
                unsafe_allow_html=True
            )
            st.caption(task["flow"])

            tag_html = "Collections: " + " ".join(
                f"<span class='mono' style='background:rgba(88,166,255,0.08);"
                f"border:1px solid rgba(88,166,255,0.25);border-radius:20px;"
                f"padding:2px 10px;color:#58a6ff'>{t}</span>"
                for t in task["tags"]
            )
            st.markdown(tag_html, unsafe_allow_html=True)

# ─────────────────────────────────────────
# SECTION 3 — 專案架構演進
# ─────────────────────────────────────────
st.header("🗺 Four milestones 專案架構演進時程")

PHASES = {
    "Phase I": {
        "icon": "🗃️",
        "status": "✅ 已完成",
        "name": "On-Premise 地端開發",
        "desc": "Docker 容器化，地端執行 ETL + Streamlit Dashboard",
        "items": [
            ("開發 ETL Task01~03, 05", "Obsidian / GitHub / LeetCode / Google Sheets，存入本地 MongoDB"),
            ("MongoDB 本地部署", "Docker Compose 啟動 python-base environment 、 MongoDB containers"),
            ("Streamlit 前端開發", "Home & Knowledge Factory"),
            (".env 環境變數管理", "API tokens、cookies 全部存於 .env，由 python-dotenv 載入"),
            ("工具鏈", "pyenv + poetry 管理 Python 版本與相依套件"),
        ],
    },
    "Phase II": {
        "icon": "☁️",
        "status": "🔄 進行中",
        "name": "GCP 雲端部署",
        "desc": "Cloud Run Service / Job + Secret Manager + GCS + MongoDB Atlas",
        "items": [
            ("MongoDB Atlas M0", "本地 MongoDB 遷移至雲端 Atlas"),
            ("Obsidian → GCS", "gsutil rsync 手動同步 .md 檔至 GCS Bucket"),
            ("Cloud Run Job（ETL）", "task01~03, 05 各自打包成 image，由 Cloud Scheduler 定時觸發"),
            ("Secret Manager", "API tokens、LeetCode cookies、Atlas URI 統一管理"),
            ("Cloud Run Service（Streamlit）", "無伺服器部署"),
            ("GitHub Actions CI/CD", "push → 測試 → build image → push Artifact Registry → deploy")
        ],
    },
    "Phase III": {
        "icon": "🤖",
        "status": "🔄 進行中",
        "name": "AI Agent 串接",
        "desc": "RAG 架構 + Claude API + Streamlit Chat UI",
        "items": [
            ("ETL task06 開發", "Obsidian .md 切塊 → Google text-embedding-004 → obsidian_vectors"),
            ("增量更新機制", "file hash 比對，避免重複向量化已存在的 chunk"),
            ("MongoDB Atlas Vector Search", "建立 vector index，語意檢索 top-K 筆記片段"),
            ("Claude API 串接", "claude-sonnet-4，傳入 user question + retrieved chunks，輸出摘要 / 學習地圖"),
            ("Streamlit page AI agent", "st.chat_message + st.chat_input，對話歷史存入 chat_history collection"),
            ("Cloud Run Job task06 部署", "從 GCS 讀取 .md → embedding → upsert Atlas"),
        ],
    },
    "Phase IV": {
        "icon": "🔔", "status": "📋 待開發",
        "name": "告警與監控",
        "desc": "ETL 失敗通知 + Cookie 過期管理",
        "items": [
            ("ETL 失敗捕捉", "Cloud Run Job 回傳非 200 / 403 時捕捉例外"),
            ("Pub/Sub + Email 通知", "觸發 Pub/Sub topic，為資料工程師寄送告警 Email"),
            ("Secret Manager 更新流程", "cookie 過期時手動更新 Secrets，Job 標記失敗易於追蹤"),
            ("GCP Console 監控", "Cloud Run Job 執行狀態紅色標記，配合 Log Explorer 除錯"),],
    },
}

# 同一個 container 包住 radio + 標題 + 條列內容
with st.container(border=True):
    phase = st.radio(
        "選擇 phase No.",
        list(PHASES.keys()),
        horizontal=True,
        label_visibility="collapsed",
    )
    st.write("")  # 間距

    info = PHASES[phase]
    st.markdown(
        f"##### {info['icon']} {info['name']} &nbsp;"
        f"<span style='font-size:0.8rem;background:#1c2333;border:1px solid #30363d;"
        f"border-radius:20px;padding:3px 12px;color:#8b949e'>{info['status']}</span>",
        unsafe_allow_html=True
    )
    st.caption(info["desc"])
    st.write("")

    for title, detail in info["items"]:
        col_dot, col_text = st.columns([0.02, 0.98])
        with col_dot:
            st.markdown("<span style='color:#58a6ff;font-size:1.1rem'>•</span>",
                        unsafe_allow_html=True)
        with col_text:
            st.markdown(f"**{title}** — {detail}")

st.divider()

# ─────────────────────────────────────────
# SECTION 4 — GCP 雲端架構
# ─────────────────────────────────────────
st.subheader("☁️ 雲端部署架構總覽")
st.caption("CI/CD + Serverless 完整部署流程")

# CI/CD Pipeline
with st.container(border=True):
    st.markdown("**🔀 CI/CD Pipeline**")
    st.markdown(
        "<span style='font-family:monospace'>"
        "Git Push &nbsp;→&nbsp; "
        "<span style='color:#bc8cff'>GitHub Actions</span>"
        " &nbsp;→&nbsp; "
        "<span style='color:#58a6ff'>Build Docker Image</span>"
        " &nbsp;→&nbsp; "
        "<span style='color:#3fb950'>Push to Artifact Registry</span>"
        " &nbsp;→&nbsp; "
        "<span style='color:#ffb958'>Deploy Cloud Run</span>"
        "</span>",
        unsafe_allow_html=True,
    )

# ETL Job + Web Service
col_etl, col_web = st.columns(2)
with col_etl:
    with st.container(border=True):
        st.markdown("**⏰ 定時 ETL 執行**")
        st.caption("Cloud Scheduler 觸發 → Cloud Run Jobs")
        for job in [
            "task01-job (Obsidian .md)",
            "task02-job (GitHub API)",
            "task03-job (LeetCode GraphQL)",
            "task05-job (Skill Radar)",
            "task06-job (Obsidian .md Vector Embedding)",
        ]:
            st.markdown(f"&nbsp;&nbsp;• {job}")

with col_web:
    with st.container(border=True):
        st.markdown("**🚀 Web Service 部署**")
        st.caption("Cloud Run Service — 無伺服器常駐")
        for item in [
            "Streamlit App microservice",
            "自動水平擴展Autoscaling if needed",
            "Allow ingress HTTPS",
            "Flexible on cold-start optimization",
            ""
        ]:
            st.markdown(f"&nbsp;&nbsp;• {item}")

# Storage 三欄
col_gcs, col_secret, col_atlas = st.columns(3)
with col_gcs:
    with st.container(border=True):
        st.markdown("**🪣 GCS (Data Lake)**")
        st.caption("Obsidian .md 檔案暫存  \ngsutil rsync 同步  \ntask01&task06 讀取來源")

with col_secret:
    with st.container(border=True):
        st.markdown("**🔐 Secret Manager**")
        st.caption("some credentials  \n token  \n api keys/ cookies")

with col_atlas:
    with st.container(border=True):
        st.markdown("**🗄 MongoDB Atlas**")
        st.caption("雲端 NoSQL  \nVector Search  \n11個collections")

# ─────────────────────────────────────────
# Footer
# ─────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown(f"""
<div style="text-align:center; color:{color_map["FONT_CLR"]} font-size:1.1rem; padding:1rem 0;">
    💗 Feel free to reach out me on 
    <a href="www.linkedin.com/in/shu-jyuan-lin-6195b8130" 
       target="_blank" 
       style="color:#90c2ff; text-decoration:none;">
       LinkedIn
    </a>.
</div>
""", unsafe_allow_html=True)
