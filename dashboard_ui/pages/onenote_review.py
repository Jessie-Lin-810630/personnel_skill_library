"""OneNote 審查頁：登入 hero + 多版本對照 + on-demand Silver enrichment + Gold 歸檔/退件。

登入沿用原 onenote_review 的 hero 版面（帳密→角色）；登入後採 task07 lazy_loading 變體的多版本審查。
執行流程：讀 onenote_note_metadata（唯讀）依 page_id 分組 → 三層下拉選頁 →
以 dt= 圓鈕切換同名筆記多版本 → 左渲染 bronze html、右渲染 silver md（皆自 gs:// URI）→
選到 md_path=null 版本時 POST 呼叫 Silver enrich 端點即時生成 md、已生成則直接讀 GCS（cache hit）。
含 regenerate（trigger=regenerate、受 quota）與 approve/reject 佔位按鈕（Gold 後端下一階段接）。

Required .env keys:
    MONGO_ALTAS_URI        MongoDB Atlas connection URI.
    MONGO_DB_NAME          MongoDB database name.
    SILVER_ENDPOINT_URL    Silver enrich Flask endpoint URL (e.g. http://localhost:8002/enrich).

Optional .env keys:
    ROLE_ML_USERNAME / ROLE_ML_PASSWORD          Demo login credential for ML/DL Engineer.
    ROLE_OWNER_USERNAME / ROLE_OWNER_PASSWORD    Demo login credential for Note Owner.
    ROLE_SENIOR_USERNAME / ROLE_SENIOR_PASSWORD  Demo login credential for Dept. Senior Specialist.
"""

import os
import re

import markdown as md_lib
import requests
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from utils.gcs_reader import read_image_base64_by_uri, read_text_by_uri
from utils.interact_with_mongodb import get_db_atlas, get_onenote_versioned_pages
from utils.ui_elements import _render_side_bar, color_map

load_dotenv()

PLACEHOLDER = "請選擇"
SILVER_URL = os.getenv("SILVER_ENDPOINT_URL", "")
GOLD_URL = os.getenv("GOLD_ENDPOINT_URL", "")

st.set_page_config(
    page_title="AI 協作知識平台: OneNote 多版本對照審查",
    page_icon="🗂️",
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
# Demo 登入 gate（帳密決定角色；與 onenote_review 共用 session_state）
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
# 標題 + 角色 + 登出
# ─────────────────────────────────────────
st.markdown(
    f"""
<div style="
    background: linear-gradient(135deg, #0d1526 0%, #1a2a4a 100%);
    border-radius: 16px; padding: 2rem 3rem; margin-bottom: 1.2rem;
    border: 1px solid #2a3550; text-align: center;">
    <h1 style="color:{color_map["FONT_CLR"]}; font-size:2.2rem; margin:0 0 0.4rem 0; font-weight:800;">
        🗂️ OneNote 多版本對照審查
    </h1>
    <p style="color:{color_map["TEAL"]}; font-size:1rem; margin:0; letter-spacing:1px;">
        切換同名筆記各 dt= 版本 — 點到未處理版本即時 on-demand 生成 Markdown
    </p>
</div>
""",
    unsafe_allow_html=True,
)

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
# 載入多版本清單
# ─────────────────────────────────────────


@st.cache_data(ttl=60)
def _load_versions() -> list[dict]:
    db = get_db_atlas()
    return get_onenote_versioned_pages(db)


versions_all = _load_versions()

if not versions_all:
    st.warning("尚無 Bronze 資料，請先執行 task07 lazy_loading Bronze ETL。")
    st.stop()

# ─────────────────────────────────────────
# 三層下拉選定一頁筆記（notebook → section → page_title）
# ─────────────────────────────────────────
notebooks_opts = [PLACEHOLDER] + sorted({v["notebook"] for v in versions_all if v.get("notebook")})
col_nb, col_sec, col_pg = st.columns(3)

with col_nb:
    selected_nb = st.selectbox("📓 筆記本", notebooks_opts, key="vr_notebook")

sections_raw = (
    sorted({v["section"] for v in versions_all if v.get("notebook") == selected_nb and v.get("section")})
    if selected_nb != PLACEHOLDER
    else []
)
with col_sec:
    selected_sec = st.selectbox("📂 章節", [PLACEHOLDER] + sections_raw, key=f"vr_section_{selected_nb}")

titles_raw = (
    sorted(
        {
            v["page_title"]
            for v in versions_all
            if v.get("notebook") == selected_nb and v.get("section") == selected_sec and v.get("page_title")
        }
    )
    if selected_sec != PLACEHOLDER
    else []
)
with col_pg:
    selected_title = st.selectbox("📄 頁面", [PLACEHOLDER] + titles_raw, key=f"vr_page_{selected_nb}_{selected_sec}")

all_selected = selected_nb != PLACEHOLDER and selected_sec != PLACEHOLDER and selected_title != PLACEHOLDER
if not all_selected:
    st.info("請由上方依序選擇筆記本 / 章節 / 頁面，以載入該頁的多版本對照。")
    st.stop()

# ─────────────────────────────────────────
# 該頁的所有 dt= 版本（依 html_downloaded_at 由新到舊；圓鈕切換）
# ─────────────────────────────────────────
page_versions = [
    v
    for v in versions_all
    if v.get("notebook") == selected_nb and v.get("section") == selected_sec and v.get("page_title") == selected_title
]
page_versions.sort(key=lambda v: str(v.get("html_downloaded_at", "")), reverse=True)


def _version_label(v: dict) -> str:
    """圓鈕顯示文字：dt + 下載時間 + 是否已生成 md。"""
    dt = v.get("dt", "?")
    ts = str(v.get("html_downloaded_at", ""))[:19]
    mark = "✅ 已生成" if v.get("md_path") else "🟠 未生成"
    return f"dt={dt}　({ts})　{mark}"


selected_idx = st.radio(
    "🕘 版本（同名筆記的各 dt= 分區）",
    options=list(range(len(page_versions))),
    format_func=lambda i: _version_label(page_versions[i]),
    key=f"vr_ver_{selected_nb}_{selected_sec}_{selected_title}",
)
version = page_versions[selected_idx]
page_id = version.get("page_id", "")
dt = version.get("dt", "")
html_uri = version.get("html_path", "")
md_uri = version.get("md_path")
status = version.get("status", "")

# 逐版本判斷：只有選中版本自己已歸檔時，該版唯讀、按鈕失效（不影響其他版本）。
# review_closed（rejected/overwritten）版本已由 get_onenote_versioned_pages 過濾掉、不會出現在此。
is_version_archived = status == "archived"
if is_version_archived:
    st.success(
        f"✅ 此版本已於 {str(version.get('archived_at', ''))[:19]} 歸檔"
        f"（{version.get('reviewed_by_role', '')}），唯讀。"
    )

st.divider()

# ─────────────────────────────────────────
# on-demand 觸發 Silver 端點
# ─────────────────────────────────────────
if "enrich_attempted" not in st.session_state:
    st.session_state.enrich_attempted = {}  # {(page_id, dt): error_msg or None}


def _call_silver(trigger: str) -> tuple[dict | None, str | None]:
    """POST Silver enrich 端點，回傳 (result_dict, error_msg)。"""
    if not SILVER_URL:
        return None, "SILVER_ENDPOINT_URL 未設定，無法呼叫 Silver 端點。"
    try:
        resp = requests.post(
            SILVER_URL,
            json={"page_id": page_id, "dt": dt, "trigger": trigger},
            timeout=180,
        )
    except requests.exceptions.ReadTimeout:
        return None, "Silver 端點回應逾時（LLM 生成耗時，請稍後重新整理確認）。"
    except requests.exceptions.ConnectionError:
        return None, "無法連線至 Silver 端點，請確認服務是否啟動。"
    except Exception as e:  # noqa: BLE001
        return None, f"呼叫 Silver 端點時發生錯誤：{e}"

    data = resp.json() if resp.content else {}
    if resp.status_code == 404:
        return None, data.get("error", f"查無版本 (page_id={page_id}, dt={dt})")
    if not resp.ok:
        return None, data.get("error", f"端點回應錯誤：{resp.status_code}")
    return data, None


def _trigger(trigger: str) -> None:
    """呼叫端點、依結果更新 UI 狀態；成功產出 md 則清快取重載。"""
    with st.spinner("Silver enrichment 進行中（首次生成需呼叫 LLM）…"):
        data, err = _call_silver(trigger)
    if err:
        st.session_state.enrich_attempted[(page_id, dt)] = err
        st.error(err)
        return
    if data.get("circuit_open"):
        msg = "Silver 服務暫停中（LLM 連續失敗觸發斷路器），請稍後再試。"
        st.session_state.enrich_attempted[(page_id, dt)] = msg
        st.warning(msg)
        return
    if data.get("error"):  # 例如 regenerate quota exceeded
        st.warning(data["error"])
        return
    # 成功產出（cache hit / miss 皆有 md_path）→ 清快取重載，讓右側渲染新 md
    st.session_state.enrich_attempted.pop((page_id, dt), None)
    _load_versions.clear()
    st.rerun()


# md_path 為 null 且本 session 尚未嘗試過 → 首次點到即 on-demand 觸發
# （選中版本自己已歸檔則不燒 LLM；新內容版本仍可正常生成）
if not md_uri and not is_version_archived and (page_id, dt) not in st.session_state.enrich_attempted:
    _trigger("on_demand")

# ─────────────────────────────────────────
# 左右對照渲染（白底）
# ─────────────────────────────────────────
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

# 圖片實體存在 bronze raw-notes 的 dt= 分區 _images/ 下；html 與 md 皆以此為準
img_prefix = html_uri.rsplit("/", 1)[0] if html_uri else ""


def _replace_images_in_html(html: str) -> str:
    def repl(m):
        data_uri = read_image_base64_by_uri(f"{img_prefix}/_images/{m.group(1)}")
        return f'src="{data_uri}"' if data_uri else m.group(0)

    return re.sub(r'src="_images/([^"]+)"', repl, html)


def _replace_images_in_md(md: str) -> str:
    def repl(m):
        data_uri = read_image_base64_by_uri(f"{img_prefix}/_images/{m.group(2)}")
        return f"![{m.group(1)}]({data_uri})" if data_uri else m.group(0)

    return re.sub(r"!\[([^\]]*)\]\(_images/([^)]+)\)", repl, md)


col_html, col_md = st.columns(2)

with col_html:
    st.markdown(f"#### 原始 HTML　`{selected_title}`")
    if html_uri:
        raw_html = read_text_by_uri(html_uri)
        if raw_html:
            components.html(_WHITE_FRAME.format(content=_replace_images_in_html(raw_html)), height=700, scrolling=True)
        else:
            st.warning("GCS 上找不到 HTML 檔案。")
    else:
        st.info("此版本沒有記錄 html_path。")

with col_md:
    st.markdown(f"#### Gemini 輸出 Markdown　`{selected_title}`")
    if md_uri:
        raw_md = read_text_by_uri(md_uri)
        if raw_md:
            md_as_html = md_lib.markdown(_replace_images_in_md(raw_md), extensions=["fenced_code", "tables", "nl2br"])
            components.html(_WHITE_FRAME.format(content=md_as_html), height=700, scrolling=True)
        else:
            st.warning("GCS 上找不到 MD 檔案。")
    else:
        attempted_err = st.session_state.enrich_attempted.get((page_id, dt))
        if attempted_err:
            st.error(f"此版本尚未生成 Markdown：{attempted_err}")
            if st.button("🔄 重試生成", key="vr_retry"):
                st.session_state.enrich_attempted.pop((page_id, dt), None)
                st.rerun()
        else:
            st.info("此版本尚無 md_path。")

st.divider()

# ─────────────────────────────────────────
# 審查操作按鈕（regenerate 走 Silver；approve/reject 走 Gold 端點）
# ─────────────────────────────────────────


def _call_gold(action: str) -> None:
    """POST Gold 端點執行 approve 歸檔 / reject 標記；成功清快取重載。"""
    if not GOLD_URL:
        st.error("GOLD_ENDPOINT_URL 未設定，無法呼叫 Gold 端點。")
        return
    with st.spinner("Gold 歸檔處理中…"):
        try:
            resp = requests.post(
                GOLD_URL,
                json={"page_id": page_id, "dt": dt, "role": st.session_state.role, "action": action},
                timeout=180,
            )
        except requests.exceptions.ReadTimeout:
            st.error("Gold 端點回應逾時（GCS 複製耗時，請稍後重新整理確認是否已歸檔）。")
            return
        except requests.exceptions.ConnectionError:
            st.error("無法連線至 Gold 端點，請確認服務是否啟動。")
            return
        except Exception as e:  # noqa: BLE001
            st.error(f"呼叫 Gold 端點時發生錯誤：{e}")
            return

    data = resp.json() if resp.content else {}
    if not resp.ok:
        st.error(data.get("error", f"端點回應錯誤：{resp.status_code}"))
        return
    _load_versions.clear()
    st.rerun()


st.markdown("#### 審查操作")
_btns_disabled = (not md_uri) or is_version_archived
b1, b2, b3, _ = st.columns([1, 1, 1, 3])

with b1:
    if st.button("🔁 Regenerate", use_container_width=True, disabled=_btns_disabled):
        _trigger("regenerate")

with b2:
    if st.button("✅ Approve", use_container_width=True, disabled=_btns_disabled):
        _call_gold("approved")

with b3:
    if st.button("❌ Reject", use_container_width=True, disabled=_btns_disabled):
        _call_gold("rejected")
