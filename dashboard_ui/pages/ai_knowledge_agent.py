"""AI Knowledge Agent — Page 3。

串接 intent_router_agent → rag_agent / planning_agent，
提供筆記語意查詢、摘要、個人化學習路徑規劃。
"""

# ── Standard imports ─────────────────────────────────────────────────────────
import os
import uuid

import streamlit as st
from agent_tools.query_rewriter import _load_alias_to_tags_map, _load_known_tags
from agents import planning_agent, rag_agent
from agents.intent_router_agent import route
from utils.interact_with_mongodb import get_db_atlas
from utils.ui_elements import _render_side_bar, color_map

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

# ── Page config（必須是第一個 Streamlit 指令）───────────────────────────────
st.set_page_config(
    page_title="AI Knowledge Agent",
    page_icon="🤖",
    layout="wide",
)
_render_side_bar()

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

# rag_agent 的 rewriter 需要 alias-tag 對照表與合法 tag 字典，
# 每個 session 只查一次 MongoDB，快取進 session_state 避免每輪重查。
if "alias_tag_pairs" not in st.session_state:
    _db = get_db_atlas()
    st.session_state["alias_tag_pairs"] = _load_alias_to_tags_map(_db, "obsidian_notes")
    st.session_state["known_tags"] = _load_known_tags(_db, "obsidian_vectors_multimodal")

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
        筆記語意查詢 · 摘要 · 個人化學習路徑規劃
    </p>
</div>
""",
    unsafe_allow_html=True,
)


# ── Helper：來源清單渲染 ──────────────────────────────────────────────────────
def _render_sources(sources: list[dict]) -> None:
    if not sources:
        return
    with st.expander("📎 來源筆記"):
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
query = st.chat_input("輸入問題....可以詢問（筆記查詢 / 摘要 / 學習路徑）")

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
                alias_tag_pairs=st.session_state["alias_tag_pairs"],
                known_tags=st.session_state["known_tags"],
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
                alias_tag_pairs=st.session_state["alias_tag_pairs"],
                known_tags=st.session_state["known_tags"],
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
        st.error(f"Agent 呼叫失敗，請稍後再試。錯誤：{e}")
