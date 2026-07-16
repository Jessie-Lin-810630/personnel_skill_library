"""意圖分類 router：判斷使用者輸入該交給 rag_agent 還是 planning_agent（v2 簡化版）。

改版重點：
  舊版: route() 負責 intent 分類 + tag 抽取 + alias 比對 + file_path 繼承 + HyDE rewrite
  新版: route() 只負責 intent 分類（rag_agent vs planning_agent），
        query rewrite / tag expansion / rerank 全部移到 rag_agent 內部處理

設計決策：
  - Router 職責單一化：只做 intent classification
  - 所有 retrieval 優化邏輯（rewrite、expansion、rerank）封裝在 rag_agent 內
  - 移除 _extract_filter_tags()、_extract_tags_via_alias()、
    _r_hyde_rewrite()、_looks_like_followup()、_get_last_filter_tags()
  - 呼叫端（Streamlit）只需判斷 agent_target 即可

依賴:
  - google-genai SDK (R2 用)
  - agent_tools/chat_history.py (R2 帶入 history)
  - 不需要 vector_search
"""

from agent_tools.chat_history import load_chat_history, save_chat_history
from agent_tools.connect_to_google_genai import _get_genai_client
from agent_tools.types_and_constants import RouterAgent
from google import genai
from google.genai import types
from loguru import logger

# ── 常數 ──────────────────────────────────────────────────────────
AgentTarget = str  # "rag_agent" | "planning_agent"

R2_SYSTEM_PROMPT = """你是一個意圖分類器。
根據使用者最新的輸入與對話歷史，判斷使用者想要:
  - 查詢或摘要筆記內容 → 輸出: rag_agent
  - 生成個人化學習路徑或學習地圖 → 輸出: planning_agent

只能輸出 rag_agent 或 planning_agent 其中一個字串，不可以輸出其他任何文字。"""


# ── R1：keyword 快篩 ──────────────────────────────────────────────


def _r1_keyword_match(query: str) -> tuple[AgentTarget | None, float]:
    """R1 關鍵字快篩：以 planning / rag 關鍵字比對 query，命中即回對應 agent 與信心分數。

    先比 planning 關鍵字、再比 rag 關鍵字；任一命中即回 (agent_target, score)，
    兩者皆未命中回 (None, 0.0)，交由 R2 LLM 補判。

    Args:
        query: 使用者原始輸入。

    Returns:
        (agent_target, score)：命中回 ("planning_agent" | "rag_agent", 分數)；未命中回 (None, 0.0)。
    """
    query_lower = query.lower()

    for kw in RouterAgent.PLANNING_KEYWORDS:
        if (kw.lower() in query_lower) or (query_lower in kw.lower()):
            score = round(len(kw) / len(query), 4) if query else 0
            logger.info(f"R1 命中 planning keyword: '{kw}' (score={score})")
            return "planning_agent", score

    for kw in RouterAgent.RAG_KEYWORDS:
        if (kw.lower() in query_lower) or (query_lower in kw.lower()):
            score = round(len(kw) / len(query), 4) if query else 0
            logger.info(f"R1 命中 rag keyword: '{kw}' (score={score})")
            return "rag_agent", score

    logger.info("R1 無法判斷，升級至 R2")
    return None, 0.0


# ── R2：LLM 補判 ──────────────────────────────────────────────────


def _r2_llm_classify(
    query: str,
    session_id: str,
    client: genai.Client,
) -> tuple[AgentTarget, float]:
    """R2 LLM 補判：R1 未命中時，帶入跨 agent 對話背景讓 LLM 分類意圖。

    分別讀 rag 與 planning 歷史包成背景脈絡，連同最新 query 送 LLM，回傳分類結果與固定信心分數。

    Args:
        query:      使用者原始輸入。
        session_id: 目前對話的 uuid4。
        client:     google-genai Client 物件。

    Returns:
        (agent_target, score)：("planning_agent" | "rag_agent", 0.95)。
    """
    # load_chat_history 以 agent_type 精確比對，不支援 None，
    # 故分別讀 rag 與 planning 歷史，再包成背景脈絡，讓 router 感知跨 agent 對話。
    history_rag_msg = load_chat_history(session_id, agent_type="rag", n=RouterAgent.CHAT_HISTORY_N)
    history_planning_msg = load_chat_history(session_id, agent_type="planning", n=RouterAgent.CHAT_HISTORY_N)

    context_parts = []
    if history_rag_msg:
        rag_lines = "\n".join(f"  [{m['role']}] {m['parts'][0]['text']}" for m in history_rag_msg)
        context_parts.append(f"[RAG Agent 最近對話]\n{rag_lines}")
    if history_planning_msg:
        planning_lines = "\n".join(f"  [{m['role']}] {m['parts'][0]['text']}" for m in history_planning_msg)
        context_parts.append(f"[Planning Agent 最近對話]\n{planning_lines}")

    contents = []
    if context_parts:
        # 用 role: user 包裝背景，避免 router 誤以為這些歷史是它自己（model）說過的話
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": "以下是這個 session 的對話背景，供你判斷使用者當前意圖時參考：\n\n"
                        + "\n\n".join(context_parts)
                    }
                ],
            }
        )
        contents.append(
            {
                "role": "model",
                "parts": [{"text": "好的，我已了解對話背景，請告訴我使用者的最新輸入。"}],
            }
        )

    contents.append({"role": "user", "parts": [{"text": query}]})

    response = client.models.generate_content(
        model=RouterAgent.MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=R2_SYSTEM_PROMPT,
            temperature=0.0,
            max_output_tokens=20,
        ),
    )

    result_text = response.text.strip().lower()
    if "planning" in result_text:
        return "planning_agent", 0.95
    return "rag_agent", 0.95


# ── 主函式 ────────────────────────────────────────────────────────


def route(query: str, session_id: str) -> dict:
    """判斷使用者輸入應交給哪個 Agent。

    Args:
        query:      使用者原始輸入
        session_id: 目前對話 uuid4

    Returns:
        {"agent_target": "rag_agent" | "planning_agent"}
    """
    # R1 keyword 快篩
    r1_result, intent_score = _r1_keyword_match(query)

    if r1_result is not None:
        save_chat_history(
            session_id=session_id,
            agent_type="router",
            role="model",
            message_text=r1_result,
            metadata={
                "method": "r1_keyword",
                "intent_score": intent_score,
                "user_query": query,
            },
        )
        return {"agent_target": r1_result}

    # R2 LLM 補判
    client = _get_genai_client()
    r2_result, intent_score = _r2_llm_classify(query, session_id, client)

    save_chat_history(
        session_id=session_id,
        agent_type="router",
        role="model",
        message_text=r2_result,
        metadata={
            "method": "r2_llm",
            "intent_score": intent_score,
            "model": RouterAgent.MODEL,
            "user_query": query,
        },
    )

    return {"agent_target": r2_result}
