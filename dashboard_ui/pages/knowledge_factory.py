"""Knowledge Factory — 資料工程風格的專案架構展示頁。

涵蓋 Tech Stack Overview（13 層技術堆疊卡片）與
以 9 張 DAG SVG 呈現的 Data Lineage（附 ERD 連結）。
"""

import os

import streamlit as st
from dotenv import load_dotenv
from utils.gcs_reader import read_text
from utils.tech_stack_diagram import render_tech_stack_diagram
from utils.ui_elements import color_map, render_side_bar

load_dotenv()
ERD_LINK = os.getenv("ERD_LINK")

# ─────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────
st.set_page_config(
    page_title="Knowledge factory",
    page_icon="⚡️",
    layout="wide",
    initial_sidebar_state="expanded",
)
render_side_bar()

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
    <h1 style="color:{color_map["FONT_CLR"]}; font-size:2.2rem; font-weight:800;
        margin:0 0 0.6rem 0; line-height:1.1;">
        Chasing Great Data Engineering
    </h1>
    <p style="color:{color_map["TEAL"]}; font-size:1rem; margin:0; letter-spacing:0.5px; font-weight:500;">
        以資料工程面向介紹此網站的架構，如願意交流歡迎透過
        <a href="https://github.com/Jessie-Lin-810630/personnel_skill_library"
        target="_blank"
        style="color:{color_map["LIGHTBLUE"]}; text-decoration:none;">
        Github
        </a>
          |
        <a href="https://www.linkedin.com/in/shu-jyuan-lin-6195b8130"
        target="_blank"
        style="color:{color_map["LIGHTBLUE"]}; text-decoration:none;">
        LinkedIn
    </p>
</div>
""",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────
# SECTION 1 — Tech Stack Overview
# ─────────────────────────────────────────
st.header("🛠 Tech Stack Overview")
st.caption("本網站的技術堆疊，依 13 個面向分層呈現")
st.html(render_tech_stack_diagram())
# 備用圖
# _, col, _ = st.columns([1,3,1])
# col.container(width=900).image("dashboard_ui/images/Gemini_Generated_Image_tech_stack.png")


# ─────────────────────────────────────────
# SECTION 2 — Data Lineage
# ─────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load_dag_svg(fname: str) -> str:
    """從 GCS personal-vaults 讀取 DAG SVG 文字並快取，避免每次 rerun／切 tab 重複下載。

    讀取失敗（回空字串）時拋 FileNotFoundError：st.cache_data 不會快取拋例外的呼叫，
    故失敗不會被鎖進快取，下次 rerun 會自動重試。
    """
    svg = read_text("personal-vaults", fname)
    if not svg:
        raise FileNotFoundError(fname)
    return svg


st.header("🔗 DAGs for Data Lineage")
st.caption("本網站由 9 項 Data pipeline (DAGs) 運作 — 點擊 tab 切換不同 DAGs")

_lineage_items = [
    (":red[DAG01 - Obsidian 文本清理]", "task01_v2_link.svg"),
    (":violet[DAG02 - GitHub 實作履歷擷取]", "task02_link.svg"),
    (":blue[DAG03 - Programming skill 履歷擷取]", "task03_link.svg"),
    (":green[DAG04 - Google Sheet 表格自動處理]", "task05_link.svg"),
    (":orange[DAG06 - Obsidian 文本向量化]", "task06_v2_link.svg"),
    (":3rd_place_medal: DAG07 - OneNote 文本萃取", "task07_v2_bronze_link.svg"),
    (":2nd_place_medal: DAG08 - OneNote 文本增強擴寫", "task07_v2_silver_link.svg"),
    (":1st_place_medal: DAG09 - OneNote 文本歸檔", "task07_v2_gold_link.svg"),
    (":rainbow[DAG10 - OneNote 文本向量化]", "task08_link.svg"),
]

_lineage_tabs = st.tabs([label for label, _ in _lineage_items])

for _tab, (_, _fname) in zip(_lineage_tabs, _lineage_items):
    with _tab:
        st.markdown(f"- [ERD Link 請參考此處連結]({ERD_LINK})")
        con = st.container(width=1250, height=600, border=False)
        con.caption("點擊圖片右上角可放大圖片")
        try:
            con.image(_load_dag_svg(_fname), width="stretch")
        except FileNotFoundError:
            con.error("Image Not Found")

# ─────────────────────────────────────────
# Footer
# ─────────────────────────────────────────
st.divider()
st.markdown(
    f"""
<div style="text-align:center; color:{color_map["FONT_CLR"]}; font-size:1.1rem; padding:0rem 0;">
    Sources from Leetcode.com |
    <a href="https://github.com/Jessie-Lin-810630/personnel_skill_library"
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
""",
    unsafe_allow_html=True,
)
