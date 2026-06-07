"""
職責:
  route(): 判斷使用者輸入應交給哪個 Agent 處理。
  
  R1 keyword 快篩 → 命中則直接回傳
  R2 LLM 補判    → R1 無法判斷時，帶入最近 N 輪 history 讓 LLM 判斷

依賴:
  - google-genai SDK (R2 用)
  - tools/chat_history.py (R2 帶入 history)
  - 不需要 vector_search
"""
from google.oauth2.service_account import Credentials
import os
from google import genai
from google.genai import types
from loguru import logger

from ..agent_tools.chat_history import load_chat_history, save_chat_history


# ── 常數 ──────────────────────────────────────────────────────────
ROUTER_AGENT_MODEL = "gemini-2.5-flash-lite"
AgentTarget = str   # "rag_agent" | "planning_agent"
CHAT_HISTORY_N = 3   # planning_agent (R2) 帶入最近幾輪 history

# Routing 方案 R1：Keyword-based
R1_PLANNING_KEYWORDS = [
    # 中文
    "學習路徑", "學習地圖", "學習計畫", "怎麼學", "如何學", "我想學",
    "建議學", "規劃", "制定", "路線圖", "學習建議",
    "技能樹", "往哪個方向", "轉職", "接下來學什麼",
    "成長路線", "職涯規劃", "學習方向", "學習順序",
    "先學什麼", "後續學習", "入門路線",

    # 英文
    "roadmap", "learning roadmap", "learning path",
    "study plan", "learning plan", "career path",
    "how to learn", "what should i learn",
    "what to learn next", "where should i start",
    "learning direction", "skill tree",
    "upskill", "reskill", "career switch",
    "transition", "study guide",
    "beginner path", "step by step",
    "curriculum", "growth path",
    "plan for learning",
]

R1_RAG_KEYWORDS = [
    # 中文
    "查詢", "搜尋", "找", "有沒有",  "筆記裡",
    "摘要", "幫我看", "有什麼", "整理", "列出",
    "內容是什麼", "提到", "在哪", "存在", "關於",
    "文件裡", "資料裡", "紀錄裡",
    "總結", "重點", "相關內容",

    # 英文
    "summary", "summarize", "search", "retrieve",
    "lookup", "find", "query",
    "what is in", "anything about",
    "mentioned", "list", "show me",
    "notes", "documents", "knowledge base",
    "kb", "context", "reference",
    "rag", "vector search",
    "search for", "look up",
    "extract", "key points",
]

# Routing 方案 R2：LLM Classifier
# system prompt - 要求模型只輸出固定字串，方便 parse
R2_SYSTEM_PROMPT = """你是一個熱心的意圖分類器。
根據使用者最新的輸入與對話歷史，判斷使用者想要:
  - 查詢或摘要筆記內容，此時輸出: rag_agent
  - 生成個人化學習路徑或學習地圖，此時輸出: planning_agent

**輸出以下規定的格式，冒號後面是你的判斷信心分數 (0.00–1.00)
*格式為
rag_agent:0.85
或
planning_agent:0.92*
除非你認為不是二者之一，輸出你的判斷脈絡、以及無法分類的原因。**

**執行範例：**
1. 適合判斷成 planning_agent 的情境
- asks for guidance, roadmap, future learning direction
- asks what to learn next
- 詢問技能規劃。
- 可以怎麼學。
- 諮詢職涯發展時的學習方法。

2. 適合判斷成 rag_agent 的情境:
- asks to retrieve/summarize/search existing knowledge
- asks what is inside notes/documents
- 詢問現有筆記摘要。
- 筆記裡有什麼。
"""


def _get_genai_client() -> genai.Client:
    """
        初始化 google-genai client。
    """
    json_path = os.getenv("AGENT_PLATFORM_USER_CREDENTIALS")
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    credentials = Credentials.from_service_account_file(json_path, scopes=scopes)

    project = os.getenv("GCP_PROJECT_ID")
    location = "us-central1"
    if not project or not credentials:
        raise EnvironmentError(
            "找不到 GCP_PROJECT_ID / AGENT_PLATFORM_USER_CREDENTIALS ，請確認已設定在 .env 或 secret managers 中。"
        )
    return genai.Client(vertexai=True,
                        project=project,
                        location=location,
                        credentials=credentials)


# ── R1：keyword 快篩 ───────────────────────────────────────────────
def _r1_keyword_match(query: str) -> tuple[AgentTarget | None, float]:
    """
    對 query 做 keyword 快篩。
    回傳 "planning_agent"、"rag_agent"，或 None 無法判斷，交給 R2）。

    優先從 R1_PLANNING_KEYWORDS 做快篩，以免碰到「幫我查詢並規劃學習路徑」這類意圖有多層次的查詢時，
    因為被誤導分流到 rag_agent (Agent 1)。
    """
    query_lower = query.lower()
    planning_hits = [kw for kw in R1_PLANNING_KEYWORDS if kw.lower() in query_lower]
    rag_hits = [kw for kw in R1_RAG_KEYWORDS if kw.lower() in query_lower]

    if planning_hits:  # 先做
        score = round(len(planning_hits) / len(R1_PLANNING_KEYWORDS), 4)
        logger.info(f"使用 R1 方案，R1 命中 planning keyword: {planning_hits}, score={score}")
        return "planning_agent", score

    if rag_hits:
        score = round(len(rag_hits) / len(R1_RAG_KEYWORDS), 4)
        logger.info(f"使用 R1 方案，R1 命中 rag keyword: {rag_hits}, score={score}")
        return "rag_agent", score

    logger.info("R1 方案無法判斷，改用 R2 方案： LLM Classifier")
    return None, 0.0000


# ── R2：LLM 補判 ───────────────────────────────────────────────────
def _r2_llm_classify(query: str,
                     session_id: str,
                     client: genai.Client,
                     ) -> tuple[AgentTarget, float]:
    """
    帶入最近 N 輪對話歷史，呼叫 LLM 判斷 intent。

    history 讀取不指定 agent_type，因為 router 需要感知
    跨 agent 的對話脈絡（例如上一輪是 rag，這一輪想切換到 planning）。
    為此，router 自己的判斷紀錄存在 agent_type="router"，
    而這裡讀取的是所有 agent_type 的混合 history 來感知全局脈絡。

    實作上分兩次讀取再合併，取最近 N 輪、按 timestamp 排序。
    """
    # ── Step 1: 讀取對話歷史（最近 3 輪）───────────────────────────────
    # 讀取 rag 與 planning 各自最近 3 輪，合併後模擬全局 history
    # router 自己的紀錄不帶入，避免迴圈。
    history_rag_msg = load_chat_history(session_id, agent_type="rag", n=CHAT_HISTORY_N)
    history_planning_msg = load_chat_history(session_id, agent_type="planning", n=CHAT_HISTORY_N)

    # 兩段 history 直接串接，舊的在前，讓模型感知脈絡轉換
    # 實際順序可能交錯，但對 intent 判斷已足夠
    combined_history_msg = history_rag_msg + history_planning_msg

    # ── Step 2: 組裝本輪 contents 餵給 LLM 分類 ─────────────────────
    current_user_msg = {"role":  "user",
                        "parts": [{"text": query}],
                        }
    contents = combined_history_msg + [current_user_msg]

    logger.info(f"呼叫模型 {ROUTER_AGENT_MODEL}，挾帶 {len(combined_history_msg)} recent history messages.")

    # ── Step 3: LLM 分類 ──────────────────────────────────────────
    response = client.models.generate_content(model=ROUTER_AGENT_MODEL,
                                              contents=contents,
                                              config=types.GenerateContentConfig(
                                                  system_instruction=R2_SYSTEM_PROMPT,
                                                  temperature=0.0,   # 分類任務，要最穩定的輸出
                                                  max_output_tokens=50,  # 只需要輸出一個字串，限制 token 避免廢話
                                              ),
                                              )

    raw_result = response.text.strip().lower()

    # parse
    try:
        target, score_str = raw_result.split(":")
        score = round(float(score_str), 4)
        if target not in ("rag_agent", "planning_agent"):
            raise ValueError
    except (ValueError, AttributeError):
        logger.warning(f"R2 輸出格式異常: '{raw_result}'，預設導向 rag_agent, score=0.5")
        target, score = "rag_agent", 0.5000

    logger.info(f"R2 方案判斷結果: {target}, score={score}")
    return target, score


# ── 主函式 ────────────────────────────────────────────────────────

def route(query: str, session_id: str) -> AgentTarget:
    """
    判斷使用者輸入應交給哪個 Agent。

    Args:
        query:      使用者輸入的原始文字
        session_id: 目前對話的 uuid4

    Returns:
        "rag_agent" 或 "planning_agent"
    """
    # ── Step 1: 用 R1 方案：keyword 快篩 ───────────────────────────────────────
    r1_result, intent_score = _r1_keyword_match(query)

    # 若 R1 有匹配成功，存入 router 紀錄後直接回傳
    if r1_result is not None:
        save_chat_history(session_id=session_id,
                          agent_type="router",
                          role="model",
                          message_text=r1_result,
                          metadata={"method": "r1_keyword",
                                    "intent_score": intent_score,
                                    "user_query": query},
                          )
        return r1_result

    # ── Step 2: 若 R1 無匹配結果，用 R2 方案：LLM 補判 ───────────────────────────────────────────
    client = _get_genai_client()
    r2_result, intent_score = _r2_llm_classify(query, session_id, client)

    save_chat_history(session_id=session_id,
                      agent_type="router",
                      role="model",
                      message_text=r2_result,
                      metadata={
                          "method": "r2_llm",
                          "intent_score": intent_score,
                          "model": ROUTER_AGENT_MODEL,
                          "user_query": query},
                      )
    return r2_result
