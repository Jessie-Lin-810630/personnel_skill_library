"""意圖分類 router，判斷使用者輸入該交給 rag_agent 還是 planning_agent。

1. 函式 route 只做 intent 分類，帶入歷史脈絡判定該把這輪輸入交給 rag_agent 還是 planning_agent。

設計決策：
  - Router 職責單一化，只做 intent classification；
    query rewrite、tag expansion、rerank 等檢索優化邏輯全部封裝在 rag_agent 內部。
  - 呼叫端只需依 route 回傳的 agent_target 分派，不需處理任何 retrieval 細節。
"""

from agent_tools.chat_history import load_chat_history, save_chat_history
from agent_tools.connect_to_google_genai import get_genai_client
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
    """第一關的關鍵字快篩，以預先定義的關鍵字清單比對使用者輸入，命中即決定要交給哪一個 agent。

    先比對規劃類關鍵字、再比對查詢類關鍵字，任一命中就立刻回傳，不再往下比。
    比對不分大小寫，且雙向包含都算命中，因此使用者只打關鍵字的一部分也接得住。
    信心分數以命中的關鍵字長度除以輸入長度計算，關鍵字佔輸入的比重越高分數越高。

    Args:
        query: 使用者原始輸入。

    Returns:
        目標 agent 名稱與信心分數組成的 tuple。命中時名稱為 planning_agent 或 rag_agent；
        兩類關鍵字都未命中時名稱為 None、分數為 0.0，交由第二關的 LLM 補判。
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
    """第二關的 LLM 補判，在關鍵字快篩失手時帶入跨 agent 的對話背景讓模型分類意圖。

    載入歷史的函式以 agent 類型精確比對、不接受空值，因此這裡分別讀取 RAG 與 Planning 兩份歷史，
    再一起包成背景脈絡，讓 router 也能感知另一個 agent 的對話進展。
    背景脈絡以 user 角色包裝，避免模型誤以為那些內容是自己說過的話。

    Args:
        query: 使用者原始輸入。
        session_id: 目前對話的 uuid4。
        client: google-genai Client 物件。

    Returns:
        目標 agent 名稱與信心分數組成的 tuple。名稱為 planning_agent 或 rag_agent，
        分數固定為 0.95，代表這是模型判定而非關鍵字命中。
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
    """判斷使用者這一輪的輸入該交給哪一個 agent 處理。

    先跑關鍵字快篩，命中就直接採用；未命中才呼叫模型補判。
    兩種路徑都會把分類結果寫進對話紀錄，並在 metadata 標明判定方式與信心分數，方便事後追查分流是否正確。

    Args:
        query: 使用者原始輸入。
        session_id: 目前對話的 uuid4。

    Returns:
        只含 agent_target 一個鍵的 dict，值為 rag_agent 或 planning_agent。
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
    client = get_genai_client()
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
