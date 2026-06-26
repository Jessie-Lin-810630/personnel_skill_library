import os
import re

import markdown as md_lib
import requests
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from utils.gcs_reader import (
    SRC_BUCKET,
    local_path_to_gcs_blob,
    read_bytes_as_base64,
    read_text,
)
from utils.interact_with_mongodb import get_db_atlas, get_onenote_pages
from utils.ui_elements import _render_side_bar, color_map

load_dotenv()

PLACEHOLDER = "請選擇"

# ─────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────
st.set_page_config(
    page_title="AI 協作知識平台: OneNote to Markdown Review",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)
_render_side_bar()

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────
# Demo 登入 gate（帳密決定角色）
# ─────────────────────────────────────────
CREDENTIALS = [
    (os.getenv("ROLE_ML_USERNAME", ""), os.getenv("ROLE_ML_PASSWORD", ""), "ML/DL Engineer"),
    (os.getenv("ROLE_OWNER_USERNAME", ""), os.getenv("ROLE_OWNER_PASSWORD", ""), "Note Owner"),
    (os.getenv("ROLE_SENIOR_USERNAME", ""), os.getenv("ROLE_SENIOR_PASSWORD", ""), "Dept. Senior Specialist"),
]

if not st.session_state.get("authenticated"):
    # ── Hero banner ──
    st.markdown(
        f"""
<div style="
    background: linear-gradient(135deg, #0d1526 0%, #0f2040 60%, #1a1040 100%);
    border-radius: 20px;
    padding: 3rem 3.5rem 2.5rem;
    margin-bottom: 1.8rem;
    border: 1px solid #2a3550;
    text-align: center;
">
    <div style="font-size:2.8rem; margin-bottom:0.6rem;">🧠</div>
    <h1 style="color:{color_map["FONT_CLR"]}; font-size:1.9rem; font-weight:800;
        margin:0 0 0.6rem 0; line-height:1.35;">
        歡迎來到 AI 知識協作平台
    </h1>
    <p style="color:{color_map["TEAL"]}; font-size:1.05rem; margin:0; letter-spacing:0.5px; font-weight:500;">
        從日常筆記到企業智慧的關鍵一步
    </p>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── 兩欄：左邊文案 / 右邊登入表單 ──
    content_col, form_col = st.columns([3, 2], gap="large")

    with content_col:
        st.markdown(
            f"""
<div style="color:{color_map["FONT_CLR"]}; line-height:1.85; font-size:0.95rem;">

<p>在 AI 浪潮湧現的時代，企業數位轉型的關鍵往往不在於引進多強大的 AI 模型，而是在於
<strong style="color:{color_map["TEAL"]};">我們如何餵養它正確的知識</strong>。</p>

<p>您在 OneNote 中記錄的點點滴滴，是部門歷經無數專案累積下來的珍貴業務結晶。然而，OneNote
背後隱藏的大量 HTML 程式碼，對人類好看的格式，卻會成為 AI 閱讀時的「雜訊」，導致 AI
在檢索時產生誤解、遺漏甚至胡言亂語。</p>

<p>這個系統透過自動化 ETL 數據管道，將 OneNote 筆記萃取、清洗並轉換為
<strong style="color:{color_map["TEAL"]};">AI 最喜歡的純淨結構（Markdown）</strong>。</p>

<p style="color:{color_map["TEAL"]}; font-weight:700; font-size:1rem; margin-top:1.4rem;">
    為什麼需要您的參與？
</p>

<p>AI 雖然運算快速，但它不懂您部門的真實業務邏輯。與其擔心被 AI 取代，我們更應該成為
<strong>「督導 AI 的決策者」</strong>。當您在審核時，請帶著以下三個眼光做最後把關：</p>

</div>
""",
            unsafe_allow_html=True,
        )

        # 三個評估面向卡片
        c1, c2, c3 = st.columns(3)
        card_style = """
            border-radius:12px;
            padding:1rem 1rem 1.2rem;
            height:100%;
            border:1px solid {border};
            background:{bg};
        """
        with c1:
            st.markdown(
                f"""
<div style="{card_style.format(border=color_map["TEAL"], bg="rgba(0,212,200,0.07)")}">
    <div style="font-size:1.6rem; margin-bottom:0.4rem;">🎯</div>
    <div style="color:{color_map["TEAL"]}; font-weight:700; font-size:0.9rem; margin-bottom:0.5rem;">
        準確性 Accuracy
    </div>
    <div style="color:{color_map["FONT_CLR"]}; font-size:0.82rem; line-height:1.6;">
        AI 真的讀懂業務痛點了嗎？確認摘要是否精準捕捉核心重點，有無遺漏關鍵步驟或報錯邏輯。
    </div>
</div>
""",
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"""
<div style="{card_style.format(border=color_map["PURPLE"], bg="rgba(155,109,255,0.07)")}">
    <div style="font-size:1.6rem; margin-bottom:0.4rem;">⚖️</div>
    <div style="color:{color_map["PURPLE"]}; font-weight:700; font-size:0.9rem; margin-bottom:0.5rem;">
        可靠性 Reliability
    </div>
    <div style="color:{color_map["FONT_CLR"]}; font-size:0.82rem; line-height:1.6;">
        在雜訊中，AI 是否依然清醒？檢視它面對口語化文字與不完美輸入時，是否仍穩定輸出清晰結構。
    </div>
</div>
""",
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                f"""
<div style="{card_style.format(border=color_map["ORANGE"], bg="rgba(249,115,22,0.07)")}">
    <div style="font-size:1.6rem; margin-bottom:0.4rem;">🛡️</div>
    <div style="color:{color_map["ORANGE"]}; font-weight:700; font-size:0.9rem; margin-bottom:0.5rem;">
        隱私與資安 Privacy
    </div>
    <div style="color:{color_map["FONT_CLR"]}; font-size:0.82rem; line-height:1.6;">
        敏感資料是否被妥善阻擋？確認 AI 未外洩個資或客戶機密，且能防禦 Prompt Injection 攻擊。
    </div>
</div>
""",
                unsafe_allow_html=True,
            )

    with form_col:
        st.markdown(
            f"""
<div style="
    background: rgba(255,255,255,0.03);
    border: 1px solid #2a3550;
    border-radius: 16px;
    padding: 2rem 2rem 1.5rem;
">
    <p style="color:{color_map["TEAL"]}; font-weight:700; font-size:1rem; margin:0 0 1.2rem 0; text-align:center;">
        🔐 知識守護者登入
    </p>
""",
            unsafe_allow_html=True,
        )

        username = st.text_input("帳號", key="login_user", placeholder="輸入您的帳號")
        password = st.text_input("密碼", type="password", key="login_pwd", placeholder="輸入您的密碼")

        if st.button("登入", use_container_width=True, type="primary"):
            if not username or not password:
                st.warning("請輸入帳號與密碼。")
            else:
                matched_role = next(
                    (role for u, p, role in CREDENTIALS if u and p and u == username and p == password),
                    None,
                )
                if matched_role:
                    st.session_state.authenticated = True
                    st.session_state.role = matched_role
                    st.rerun()
                else:
                    st.error("帳號或密碼錯誤，請重試。")

        st.markdown(
            """
    <p style="color:#4a5568; font-size:0.78rem; text-align:center; margin-top:1rem;">
        此平台僅供授權人員使用<br>登入即代表您同意以指定角色進行審核操作
    </p>
</div>
""",
            unsafe_allow_html=True,
        )

    st.stop()

# ─────────────────────────────────────────
# 標題
# ─────────────────────────────────────────
st.markdown(
    f"""
<div style="
    background: linear-gradient(135deg, #0d1526 0%, #1a2a4a 100%);
    border-radius: 16px;
    padding: 2rem 3rem;
    margin-bottom: 1.2rem;
    border: 1px solid #2a3550;
    text-align: center;
">
    <h1 style="color:{color_map["FONT_CLR"]}; font-size:2.2rem; margin:0 0 0.4rem 0; font-weight:800;">
        🔍 OneNote Review
    </h1>
    <p style="color:{color_map["TEAL"]}; font-size:1rem; margin:0; letter-spacing:1px;">
        HTML vs Markdown 並排對照 — 審核 Gemini LLM 輸出品質
    </p>
</div>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────
# 登入角色顯示 + 登出按鈕
# ─────────────────────────────────────────
role_col, logout_col = st.columns([8, 1])
with role_col:
    st.markdown(f"目前角色：**{st.session_state.role}**")
with logout_col:
    if st.button("登出", use_container_width=True):
        st.session_state.pop("authenticated", None)
        st.session_state.pop("role", None)
        st.rerun()

st.divider()


# ─────────────────────────────────────────
# 載入 MongoDB 頁面清單
# ─────────────────────────────────────────


@st.cache_data(ttl=60)
def _load_pages() -> list[dict]:
    db = get_db_atlas()
    return get_onenote_pages(db)


pages = _load_pages()

if not pages:
    st.warning("尚無 OneNote 頁面資料，請先執行 task07 pipeline。")
    st.stop()

# ─────────────────────────────────────────
# 三層下拉選擇器（key 連動：換筆記本時章節/頁面自動重置）
# ─────────────────────────────────────────
notebooks_opts = [PLACEHOLDER] + sorted({p["notebook"] for p in pages if p.get("notebook")})
col_nb, col_sec, col_pg = st.columns(3)

with col_nb:
    selected_nb = st.selectbox("📓 筆記本", notebooks_opts, key="sel_notebook")

sections_raw = (
    sorted({p["section"] for p in pages if p.get("notebook") == selected_nb and p.get("section")})
    if selected_nb != PLACEHOLDER
    else []
)
sections_opts = [PLACEHOLDER] + sections_raw

with col_sec:
    # key 含 selected_nb：換筆記本時 widget key 改變，自動回到 index 0（請選擇）
    selected_sec = st.selectbox("📂 章節", sections_opts, key=f"sel_section_{selected_nb}")

page_options_raw = (
    [p for p in pages if p.get("notebook") == selected_nb and p.get("section") == selected_sec]
    if selected_sec != PLACEHOLDER
    else []
)
page_titles_raw = [p.get("page_title", p.get("page_id", "未知")) for p in page_options_raw]
page_opts_display = [PLACEHOLDER] + page_titles_raw

with col_pg:
    # key 含 selected_nb + selected_sec：換任一層時頁面下拉自動重置
    selected_pg_label = st.selectbox(
        "📄 頁面",
        page_opts_display,
        key=f"sel_page_{selected_nb}_{selected_sec}",
    )

# ─────────────────────────────────────────
# 未選滿 → 留白狀態，只顯示標題區
# ─────────────────────────────────────────
all_selected = selected_nb != PLACEHOLDER and selected_sec != PLACEHOLDER and selected_pg_label != PLACEHOLDER

if not all_selected:
    st.markdown("")
    col_html, col_md = st.columns(2)
    with col_html:
        st.markdown("#### 原始 HTML")
    with col_md:
        st.markdown("#### Gemini 輸出 Markdown")
    st.stop()

page = page_options_raw[page_titles_raw.index(selected_pg_label)]
page_id = page.get("page_id", "")
status = page.get("status", "")
review_result = page.get("review_result")
reviewed_at = page.get("reviewed_at")

# ─────────────────────────────────────────
# 狀態標籤
# ─────────────────────────────────────────
STATUS_STYLE = {
    "pending_review": ("🟠 待審核", "#f97316", "#1a0f00"),
    "archived": ("✅ 已歸檔", "#22c55e", "#001a0a"),
    "summarized failed": ("❌ LLM 失敗", "#ef4444", "#1a0000"),
    "saved failed": ("❌ 存檔失敗", "#ef4444", "#1a0000"),
}
label_text, label_fg, label_bg = STATUS_STYLE.get(status, ("⬜ " + status, "#94a3b8", "#1e293b"))

st.markdown(
    f"""
<div style="
    display:inline-block;
    background:{label_bg};
    color:{label_fg};
    border:1px solid {label_fg};
    border-radius:8px;
    padding:0.3rem 1rem;
    font-weight:700;
    font-size:0.95rem;
    margin-bottom:0.5rem;
">
    {label_text}
</div>
""",
    unsafe_allow_html=True,
)

if status == "archived":
    st.success(f"此頁面已於 {reviewed_at} 歸檔（{review_result}）。")

st.divider()

# ─────────────────────────────────────────
# 圖片 base64 替換工具
# ─────────────────────────────────────────


def _replace_images_in_html(html: str, section_blob_prefix: str) -> str:
    def replacer(m):
        blob = f"{section_blob_prefix}/_images/{m.group(1)}"
        data_uri = read_bytes_as_base64(SRC_BUCKET, blob)
        return f'src="{data_uri}"' if data_uri else m.group(0)

    return re.sub(r'src="_images/([^"]+)"', replacer, html)


def _replace_images_in_md(md: str, section_blob_prefix: str) -> str:
    def replacer(m):
        blob = f"{section_blob_prefix}/_images/{m.group(2)}"
        data_uri = read_bytes_as_base64(SRC_BUCKET, blob)
        return f"![{m.group(1)}]({data_uri})" if data_uri else m.group(0)

    return re.sub(r"!\[([^\]]*)\]\(_images/([^)]+)\)", replacer, md)


# ─────────────────────────────────────────
# GCS blob 路徑
# ─────────────────────────────────────────
html_local = page.get("html_path", "")
md_local = page.get("md_path", "")
html_blob = local_path_to_gcs_blob(html_local) if html_local else ""
md_blob = local_path_to_gcs_blob(md_local) if md_local else ""
section_blob_prefix = "/".join(html_blob.split("/")[:-1]) if html_blob else ""

# 白底渲染用的 wrapper
_WHITE_FRAME = """
<html><head><meta charset="utf-8">
<style>
  body {{ margin:0; background:#ffffff; color:#111; font-family:sans-serif;
         font-size:14px; line-height:1.6; padding:1rem; }}
  img {{ max-width:100%; }}
  pre, code {{ background:#f3f4f6; border-radius:4px; padding:2px 6px; }}
  table {{ border-collapse:collapse; width:100%; }}
  th, td {{ border:1px solid #ccc; padding:0.4rem 0.6rem; }}
</style>
</head><body>{content}</body></html>
"""

# ─────────────────────────────────────────
# 並排渲染（白底）
# ─────────────────────────────────────────
col_html, col_md = st.columns(2)

with col_html:
    st.markdown(f"#### 原始 HTML　`{page.get('page_title', '')}`")
    if html_blob:
        raw_html = read_text(SRC_BUCKET, html_blob)
        if raw_html:
            rendered_html = _replace_images_in_html(raw_html, section_blob_prefix)
            components.html(_WHITE_FRAME.format(content=rendered_html), height=700, scrolling=True)
        else:
            st.warning("GCS 上找不到 HTML 檔案。")
    else:
        st.info("此頁面沒有記錄 html_path。")

with col_md:
    st.markdown(f"#### Gemini 輸出 Markdown　`{page.get('page_title', '')}`")
    if md_blob:
        raw_md = read_text(SRC_BUCKET, md_blob)
        if raw_md:
            replaced_md = _replace_images_in_md(raw_md, section_blob_prefix)
            md_as_html = md_lib.markdown(
                replaced_md,
                extensions=["fenced_code", "tables", "nl2br"],
            )
            components.html(_WHITE_FRAME.format(content=md_as_html), height=700, scrolling=True)
        else:
            st.warning("GCS 上找不到 MD 檔案。")
    else:
        st.info("此頁面尚無 md_path（可能 LLM 尚未執行）。")

st.divider()

# ─────────────────────────────────────────
# Approve / Reject 按鈕
# ─────────────────────────────────────────
ARCHIVE_URL = os.getenv("ARCHIVE_ENDPOINT_URL", "")
is_archived = status == "archived"

st.markdown("#### 審核確認")
if is_archived:
    st.info("此頁面已歸檔，按鈕已停用。")

btn_col1, btn_col2, _ = st.columns([1, 1, 4])


def _call_archive(action: str):
    if not ARCHIVE_URL:
        st.error("ARCHIVE_ENDPOINT_URL 未設定，無法呼叫 Archive 端點。")
        return
    try:
        resp = requests.post(
            ARCHIVE_URL,
            json={"page_id": page_id, "role": st.session_state.role, "action": action},
            timeout=120,
        )
        if resp.ok:
            _load_pages.clear()
            st.rerun()
        else:
            st.error(f"端點回應錯誤：{resp.status_code} — {resp.text[:200]}")
    except requests.exceptions.ReadTimeout:
        st.error("Archive 端點回應逾時（GCS 操作耗時，請稍後重新整理頁面確認是否已歸檔）。")
    except requests.exceptions.ConnectionError:
        st.error("無法連線至 Archive 端點，請確認服務是否啟動。")
    except Exception as e:
        st.error(f"呼叫 Archive 端點時發生錯誤：{e}")


with btn_col1:
    if st.button("✅ Approve", disabled=is_archived, use_container_width=True):
        _call_archive("approved")

with btn_col2:
    if st.button("❌ Reject", disabled=is_archived, use_container_width=True):
        _call_archive("rejected")
