"""AI Knowledge Agent — Page 3。

串接 intent_router_agent → rag_agent / planning_agent，
提供筆記語意查詢、摘要、個人化學習路徑規劃。
"""

# ── Standard imports ─────────────────────────────────────────────────────────
import os
import uuid

import streamlit as st
from agent_tools.query_rewriter import load_alias_to_tags_map, load_known_tags
from agent_tools.types_and_constants import NoteCollections
from agents import planning_agent, rag_agent
from agents.intent_router_agent import route
from dotenv import load_dotenv
from loguru import logger
from utils.interact_with_mongodb import get_db_atlas
from utils.ui_elements import color_map, render_side_bar

# TODO: st.login() Google OAuth
# 當 GCP Console 上建立好 OAuth 2.0 Client ID 與 Client Secret 後：
# 1. 在 .streamlit/secrets.toml 設定 [auth] 區塊：
#    [auth]
#    redirect_uri = "http://localhost:8501/oauth2callback"
#    cookie_secret = "<random-secret>"
#    [auth.google]
#    client_id = "<CLIENT_ID>"
#    client_secret = "<CLIENT_SECRET>"
# 2. 在此處取消注解以下三行：
#    if not st.experimental_user.is_logged_in:
#        st.login("google")
#        st.stop()
# 官方文件: https://docs.streamlit.io/develop/api-reference/user/st.login

load_dotenv()

# ── Page config（必須是第一個 Streamlit 指令）───────────────────────────────
st.set_page_config(
    page_title="",
    page_icon="🤖",
    layout="wide",
)
render_side_bar()

# ─────────────────────────────────────────
# Demo 登入 gate（帳密決定角色；與 onenote_review 共用 session_state）
# 暫時方案：待上方 TODO（第 19-33 行）的 Google OAuth（st.login）設定完成後，
# 即可移除本區塊、改回 st.login("google") 流程。
# ─────────────────────────────────────────
CREDENTIALS = [
    (os.getenv("ROLE_ML_USERNAME", ""), os.getenv("ROLE_ML_PASSWORD", ""), "ML/DL Engineer"),
    (os.getenv("ROLE_OWNER_USERNAME", ""), os.getenv("ROLE_OWNER_PASSWORD", ""), "Note Owner"),
    (os.getenv("ROLE_SENIOR_USERNAME", ""), os.getenv("ROLE_SENIOR_PASSWORD", ""), "Dept. Senior Specialist"),
    (os.getenv("ROLE_GUEST_USERNAME", ""), os.getenv("ROLE_GUEST_PASSWORD", ""), "Guest"),
]

# Guest 角色只看得到來源清單，看不到 vector/rerank 分數（見 _render_sources）
GUEST_ROLE = "Guest"

if not st.session_state.get("authenticated"):
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
    <h1 style="color:{color_map["FONT_CLR"]}; font-size:2.2rem; margin:0 0 0.6rem 0; font-weight:800;">
        🤖 AI Knowledge Agent
    </h1>
    <p style="color:{color_map["TEAL"]}; font-size:1rem; margin:0; letter-spacing:1px;">
        筆記語意查詢 · 摘要 · 個人化學習路徑規劃
    </p>
</div>
""",
        unsafe_allow_html=True,
    )

    _, form_col, _ = st.columns([1, 2, 1])
    with form_col:
        st.markdown(
            f"""
<div style="
    background: rgba(200,100,0,0.03);
    border: 1px solid #2a3550;
    border-radius: 16px;
    padding: 2rem 2rem 1.5rem;
">
    <p style="color:{color_map["TEAL"]}; font-weight:700; font-size:1rem; margin:0 0 1.2rem 0; text-align:center;">
        🔐 授權人員登入
    </p>
""",
            unsafe_allow_html=True,
        )

        username = st.text_input("帳號", key="login_user", placeholder="輸入您的帳號")
        password = st.text_input("密碼", type="password", key="login_pwd", placeholder="輸入您的密碼")

        if st.button("登入", width="stretch", type="primary"):
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
    <p style="color:#e0e8f8; font-size:0.78rem; text-align:center; margin-top:1rem;">
        此平台僅供授權人員使用<br>登入即代表您同意以指定角色進行操作
    </p>
</div>
""",
            unsafe_allow_html=True,
        )

    st.stop()

# ── Rate limit（環境變數可覆蓋，fallback = 20）──────────────────────────────
RATE_LIMIT = int(os.getenv("AI_AGENT_RATE_LIMIT", "20"))

# ── Session state 初始化 ─────────────────────────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state["messages"] = []
if "api_call_count" not in st.session_state:
    st.session_state["api_call_count"] = 0
if "planning_map_generated" not in st.session_state:
    st.session_state["planning_map_generated"] = False


# rag_agent 的 rewriter 需要 alias-tag 對照表與合法 tag 字典。這兩份資料不隨使用者互動改變，
# 故以 st.cache_data 跨 session 共用快取（TTL 12 小時），而非 session_state；後者會讓多人同時使用時
# 每個 session 各存一份完全相同的資料、徒增記憶體。_db 前綴底線讓 cache_data 略過雜湊該連線物件。
@st.cache_data(ttl="12h")
def _load_alias_to_tags_map(_db, collection):
    return load_alias_to_tags_map(_db, collection)


@st.cache_data(ttl="12h")
def _load_known_tags(_db, collection):
    return load_known_tags(_db, collection)


_db = get_db_atlas()
alias_tag_pairs = _load_alias_to_tags_map(_db, NoteCollections.OBSIDIAN)
known_tags = _load_known_tags(_db, NoteCollections.VECTOR)

# ── Sidebar 控制區 ───────────────────────────────────────────────────────────
with st.sidebar:
    st.divider()
    st.caption(f"LLM 呼叫：{st.session_state['api_call_count']} / {RATE_LIMIT}")
    if st.button("🔄 開新對話", width="stretch"):
        st.session_state["session_id"] = str(uuid.uuid4())
        st.session_state["messages"] = []
        st.session_state["api_call_count"] = 0
        st.session_state["planning_map_generated"] = False
        st.rerun()

# ── Page heading ─────────────────────────────────────────────────────────────
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
    <h1 style="color:{color_map["FONT_CLR"]}; font-size:2.2rem; margin:0 0 0.6rem 0; font-weight:800;">
        🤖 AI Knowledge Agent
    </h1>
    <p style="color:{color_map["TEAL"]}; font-size:1rem; margin:0; letter-spacing:1px;">
        筆記語意查詢 · 摘要
    </p>
</div>
""",
    unsafe_allow_html=True,
)

# 左側留白把「角色 + 登出」推到右上角並貼近，減少視覺跨度；vertical center 讓文字與按鈕同高
_spacer, role_col, logout_col = st.columns([7, 2, 1], vertical_alignment="center")
with role_col:
    st.markdown(
        f"<div style='text-align:right;'>目前角色：<b>{st.session_state.role}</b></div>",
        unsafe_allow_html=True,
    )
with logout_col:
    if st.button("登出", width="stretch"):
        st.session_state.pop("authenticated", None)
        st.session_state.pop("role", None)
        st.rerun()


# ── Helper：來源清單渲染 ──────────────────────────────────────────────────────
def _render_sources(sources: list[dict]) -> None:
    if not sources:
        return
    with st.expander("📎 來源筆記"):
        # Guest 只看得到有哪些來源，不揭露向量/rerank 分數；同名同章節去重後只列一次
        if st.session_state.get("role") == GUEST_ROLE:
            seen = set()
            idx = 1
            for src in sources:
                key = (src["file_name"], src["section"])
                if key in seen:
                    continue
                seen.add(key)
                st.markdown(f"{idx}.  **{src['file_name']}** ｜ {src['section']}")
                idx += 1
            return
        for i, src in enumerate(sources, 1):
            line = f"{i}.  **{src['file_name']}** ｜ {src['section']} ｜ 向量: `{src.get('vector_score', 0)}`"
            # rag 經過 reranker 才有意義；planning 的 rerank_score 為 0 不顯示
            if src.get("rerank_score"):
                line += f" ｜ rerank: `{src['rerank_score']}`"
            st.markdown(line)


# ── 重播歷史訊息 ─────────────────────────────────────────────────────────────
for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            _render_sources(msg["sources"])

# ── Rate limit 防護（chat_input 前）─────────────────────────────────────────
if st.session_state["api_call_count"] >= RATE_LIMIT:
    st.warning(f"已達本次對話 LLM 呼叫上限（{RATE_LIMIT} 次），請點側邊欄的「🔄 開新對話」繼續。")
    st.stop()

# ── Chat input ───────────────────────────────────────────────────────────────
query = st.chat_input("輸入問題....可以詢問（筆記查詢 / 筆記摘要）")

if query:
    # 1. 立即顯示使用者訊息
    st.session_state["messages"].append({"role": "user", "content": query, "sources": []})
    with st.chat_message("user"):
        st.markdown(query)

    # 2. Agent 工作鏈
    session_id = st.session_state["session_id"]
    try:
        route_result = route(query, session_id)
        agent_target = route_result["agent_target"]
        if agent_target == "rag_agent":
            # v2 pipeline：rewrite → search → rerank → generate，
            # router 不再傳 filter，retrieval 優化全在 rag_query 內部處理
            result = rag_agent.rag_query(
                query=query,
                session_id=session_id,
                alias_tag_pairs=alias_tag_pairs,
                known_tags=known_tags,
            )

        elif agent_target == "planning_agent":
            if not st.session_state["planning_map_generated"]:
                result = planning_agent.generate_learning_map(query, session_id)
                st.session_state["planning_map_generated"] = True
            else:
                result = planning_agent.refine_learning_map(query, session_id)

        else:
            # router 回傳未預期值時 fallback 至 rag
            result = rag_agent.rag_query(
                query=query,
                session_id=session_id,
                alias_tag_pairs=alias_tag_pairs,
                known_tags=known_tags,
            )
            agent_target = "rag_agent"

        # 3. 計數遞增（只有成功時才加）
        st.session_state["api_call_count"] += 1

        # 4. 顯示 agent 回應
        answer = result["answer"]
        sources = result.get("sources", [])

        st.session_state["messages"].append(
            {
                "role": "assistant",
                "content": answer,
                "sources": sources,
                "agent_type": agent_target,
            }
        )
        with st.chat_message("assistant"):
            st.markdown(answer)
            _render_sources(sources)

    except Exception as e:
        # 完整 traceback 進 stderr → Cloud Run logs 便於排查；前端只留友善訊息
        logger.exception("Agent 呼叫失敗")
        st.error(f"Agent 呼叫失敗，請稍後再試。錯誤：{e}")
