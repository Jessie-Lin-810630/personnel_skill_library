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
import json
from rapidfuzz import fuzz
from pymongo.database import Database
from collections import Counter
from google import genai
from google.genai import types
from loguru import logger

from agent_tools.connect_to_google_genai import _get_genai_client
from agent_tools.chat_history import load_chat_history, save_chat_history
from utils.interact_with_mongodb import get_db_altas

# ── 常數 ──────────────────────────────────────────────────────────
ROUTER_AGENT_MODEL = "gemini-2.5-flash-lite"
HYDE_MODEL = "gemini-2.5-flash-lite"
AgentTarget = str    # routing to "rag_agent" | "planning_agent" by intent routing agent

# Routing 方案 R1：Keyword-based
# when should route to planning agent
R1_PLANNING_KEYWORDS = ["學習路徑", "學習地圖", "學習計畫", "怎麼學", "如何學", "我想學",
                        "建議學", "規劃", "制定", "路線圖", "學習建議",
                        "技能樹", "往哪個方向", "轉職", "接下來學什麼",
                        "成長路線", "職涯規劃", "學習方向", "學習順序",
                        "先學什麼", "後續學習", "入門路線",
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

# when should not route to planning agent
R1_PLANNING_EXCLUSIONS = ["旅遊", "旅行", "行程", "景點", "機票", "訂房", "住宿",
                          "餐廳", "美食", "玩", "觀光", "自由行",
                          "婚禮", "活動", "派對", "購物",
                          ]

# when should route to rag agent
R1_RAG_KEYWORDS = ["查詢", "搜尋", "找", "查", "有沒有",  "筆記裡",
                   "摘要", "幫我看", "有什麼", "整理", "列出",
                   "內容是什麼", "提到", "在哪", "存在", "關於",
                   "文件裡", "資料裡", "紀錄裡",
                   "總結", "重點", "相關內容",

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

# # Rewrite in RAG: Query transformation
# HYDE_SYSTEM_PROMPT = """你是一個筆記檢索助手的查詢改寫器。
# 使用者會提出口語化、可能不夠精確的問題。

# **以下是這個筆記庫裡實際存在的標籤字典清單:**
# {pairs}

# 每一個用、隔開的元素，元素本身結構是字典，結構如下：
# alias:[known_tags]
# 這個字典由 alias 與 known_tags 組成，其中 alias 是筆記名稱，known_tags 是該筆記的標籤清單。

# **以下是目前的對話歷史（最近幾輪）：**
# {chat_history}

# **請完成兩件事：**
# 1. 從上面的每一組 alias:[known_tags] 這種標籤字典中，選出與使用者問題最相關的「一個」標籤與這個標籤對應的筆記名稱；如果都不相關，輸出 "NONE"。
# 2. 將使用者最新問題改寫成一個不依賴歷史就能獨立理解的完整查詢句，不要用這個查詢句來回答使用者，這只是用來幫助語意檢索找到更相似的真實筆記。

# **只能用以下格式輸出，不要有其他文字：**
# ALIAS: <標籤對應的筆記名稱或NONE>
# TAG: <標籤或NONE>
# HYPOTHETICAL: <改寫後的完整查詢>
# """
# Rewrite in RAG: Hyde
HYDE_SYSTEM_PROMPT = """你是一個筆記檢索助手的查詢改寫器。
使用者會提出口語化、可能不夠精確的問題。

**以下是這個筆記庫裡實際存在的標籤字典清單:**
{pairs}

每一個用、隔開的元素，元素本身結構是字典，結構如下：
alias:[known_tags]
這個字典由 alias 與 known_tags 組成，其中 alias 是筆記名稱，known_tags 是該筆記的標籤清單。

**以下是目前的對話歷史（最近幾輪）：**
{chat_history}

**請完成兩件事：**
1. 從上面的每一組 alias:[known_tags] 這種標籤字典中，選出與使用者問題最相關的「一個」標籤與這個標籤對應的筆記名稱；如果都不相關，輸出 "NONE"。
2. 假設你是這個筆記庫的作者，會怎麼寫一段筆記內容來回答這個問題？
   請生成一段 2 到 5 句語氣貼近技術筆記、也不違背對話歷史中想要詢問的主題之「假設性回答」，不要回答使用者，
   只是用來幫助語意檢索找到更相似的真實筆記。

**只能用以下格式輸出，不要有其他文字：**
ALIAS: <標籤對應的筆記名稱或NONE>
TAG: <標籤或NONE>
HYPOTHETICAL: <假設性筆記內容>
"""


# ── Supporting functions ───────────────────────────────────────────────
# R1 plan
def _r1_keyword_match(query: str) -> tuple[AgentTarget | None, float]:
    """
    對 query 用 keyword 快篩，回傳 "planning_agent"、"rag_agent"，或 None 無法判斷，改走 R2 方案判斷意圖。

    優先從 R1_PLANNING_KEYWORDS 做快篩，以免碰到「幫我查詢並規劃學習路徑」這類意圖有多層次的查詢時，
    因為被誤導分流到 rag_agent。
    """
    query_lower = query.lower()
    planning_hits = [kw for kw in R1_PLANNING_KEYWORDS if kw.lower() in query_lower]
    rag_hits = [kw for kw in R1_RAG_KEYWORDS if kw.lower() in query_lower]

    if planning_hits:
        exclusion_hits = [kw for kw in R1_PLANNING_EXCLUSIONS if kw.lower() in query_lower]
        if exclusion_hits:
            logger.info(f"R1 命中 planning keyword {planning_hits}，"
                        f"但同時命中排除詞 {exclusion_hits}，降級至 R2")
            return None, 0.0000

        score = round(len(planning_hits) / len(R1_PLANNING_KEYWORDS), 4)
        logger.info(f"使用 R1 方案，R1 命中 planning keyword: {planning_hits}, score={score}")
        return "planning_agent", score

    if rag_hits:
        score = round(len(rag_hits) / len(R1_RAG_KEYWORDS), 4)
        logger.info(f"使用 R1 方案，R1 命中 rag keyword: {rag_hits}, score={score}")
        return "rag_agent", score

    logger.info("R1 方案無法判斷，改用 R2 方案： LLM Classifier")
    return None, 0.0000


# R2 plan
def _r2_llm_classify(query: str,
                     session_id: str,
                     client: genai.Client,
                     chat_history_n: int = 3,
                     ) -> tuple[AgentTarget, float]:
    """
    帶入最近 N 輪對話歷史，呼叫 LLM 判斷 intent。
    對話歷史讀取時不指定 agent_type，因為 router 需要感知
    跨 agent 的對話脈絡（例如上一輪是 rag，這一輪想切換到 planning）。

    回傳的讀取歷史紀錄，按照 timestamp 降冪排列 (由新到舊)。
    """
    # ── Step 1: 讀取對話歷史（最近 3 輪）───────────────────────────────
    # router 自己的紀錄不帶入，避免迴圈。
    history_rag_msg = load_chat_history(session_id, agent_type="rag", n=chat_history_n)
    history_planning_msg = load_chat_history(session_id, agent_type="planning", n=chat_history_n)

    # 為了讓 LLM 理解這是背景脈絡，不是 router 它自己說過的話，解決它之前曾經拿前次對話紀錄當作回答的幻覺
    context_parts = []
    if history_rag_msg:
        rag_lines = "\n".join(f"  [{m['role']}] {m['parts'][0]['text']}" for m in history_rag_msg
                              )
        context_parts.append(f"[RAG Agent 最近對話]\n{rag_lines}")

    if history_planning_msg:
        planning_lines = "\n".join(f"  [{m['role']}] {m['parts'][0]['text']}" for m in history_planning_msg
                                   )
        context_parts.append(f"[Planning Agent 最近對話]\n{planning_lines}")

    contents = []
    if context_parts:
        # 不用 role: model，而是 user，避免 router agent 誤以為是 model 自己帶出了 "歷史訊息"
        contents.append({"role": "user",
                         "parts": [{"text": "以下是這個 session 的對話背景，供你判斷使用者當前意圖時參考：\n\n"
                                    + "\n\n".join(context_parts)}],
                         })
        contents.append({"role": "model",
                         "parts": [{"text": "好的，我已了解對話背景，請告訴我使用者的最新輸入。"}],
                         })

    # ── Step 2: 串接本輪真正的使用者輸入 ─────────────────────
    contents.append({"role": "user",
                     "parts": [{"text": query}],
                     })

    logger.info(f"呼叫模型 {ROUTER_AGENT_MODEL}，挾帶最近 {len(history_rag_msg)+len(history_planning_msg)} 筆歷史對話。")

    # ── Step 3: LLM 分類 ──────────────────────────────────────────
    response = client.models.generate_content(model=ROUTER_AGENT_MODEL,
                                              contents=contents,
                                              config=types.GenerateContentConfig(
                                                  system_instruction=R2_SYSTEM_PROMPT,
                                                  temperature=0.0,       # 分類任務，要最穩定的輸出
                                                  max_output_tokens=20,  # 只需要輸出一個字串，限制 token 避免廢話
                                              ),
                                              )

    raw_result = response.text.strip().lower()

    # ── Step 4: Parse 回應 ────────────────────────────────────────
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


def _load_known_tags(db: Database, collection: str = "obsidian_vectors") -> set[str]:
    """從 obsidian_vectors 撈出所有出現過的 tag，做為合法 tag 字典。"""
    coll = db[collection]
    return set(coll.distinct("tags"))


def _extract_filter_tags(query: str, known_tags: list[str], fuzzy_threshold: int = 50) -> str | None:
    """
    (deprecated)
    從使用者 query 裡比對出命中的 tag，回傳第一個命中者（或 None）。
    大小寫不敏感比對，依 tag 字串長度由長到短比對，避免短字串先誤判
    (例如 "SQL" 命中卻蓋掉了應該命中的 "MySQL")。
    """
    query_lower = query.lower()
    best_match, best_score = None, 0

    for tag in sorted(known_tags, key=len, reverse=True):
        score = fuzz.ratio(tag.lower(), query_lower)
        if score >= fuzzy_threshold and score > best_score:
            best_match, best_score = tag, score

    if best_match:
        logger.info(f"extract_filter_tags: 模糊命中 tag='{best_match}' (score={best_score})")
    return best_match


def _load_alias_to_tags_map(db: Database, collection: str = "obsidian_notes") -> list[dict]:
    """
    從 obsidian_notes 撈出 {alias: [tags]} 的對照表，
    若一篇筆記有多個 alias，回傳時會攤平成獨立 pair 方便後續比對，例如：
        [ {alias-1 of note-1: [tagA, B, C]}, 
          {alias-2 of note-1: [tagA, B, C]},
          {alias-3 of note-1: [tagA, B, C]},
          {alias-1 of note-2: [tagB, C, D, E]},
          {alias-2 of note-2: [tagB, C, D, E]},
        ]
    """
    coll = db[collection]
    cursor = coll.find({}, {"_id": 0, "alias": 1, "tags": 1, "file_name": 1, "file_path": 1})
    alias_tag_pairs = []
    for doc in cursor:
        file_path = doc.get("file_path", "")
        tag = doc.get("tags", [])
        # file name 也當作 alias 之一，且排在自己的 alias keys 前頭
        alias_tag_pairs.append({"alias": doc.get("file_name", "").replace(".md", "").strip(),
                                "tags": tag,
                                "file_path": file_path,
                                })

        for alias in doc.get("alias", []):
            alias_tag_pairs.append({"alias": alias,
                                    "tags": tag,
                                    "file_path": file_path,
                                    })

    return alias_tag_pairs


def _extract_tags_via_alias(query: str,
                            alias_tag_pairs: list[dict],
                            known_tags_in_vdb: list[str],
                            min_frequency: int = 1,
                            fuzzy_threshold: int = 60) -> list[str]:
    """
    用 alias (含 file name) 搭配 rapidfuzz.fuzz 套件，與 query 模糊比對，定位相關筆記，
    再萃取這些筆記的 tags，最後與 obsidian vector database 存有的 known_tags 比對，
    確定筆記的 tags 有確實出現在 vector database 裡，
    以防 obsidian vectors 與 obsidian notes 的更新頻率不同調而造成 tags 標記在原始筆記中但卻沒有夾帶進 embedding stage。

    回傳的 tags 需要符合以下條件：
    - 該 tag 至少重複出現在 min_frequency 篇筆記，可避免單篇筆記的冷門 tag 把 prefilter 範圍撐得太大，影響查詢速度。
    - 但若只命中一篇筆記，則該筆記的全部 tags 直接採用。
    - 相似度分數 >= fuzzy_threshold

    rapidfuzz.fuzz references: https://www.cnblogs.com/luohenyueji/p/17986834
    """

    query_lower = query.lower()
    scored_matches = []

    for pair in alias_tag_pairs:
        alias_lower = pair.get("alias", "").lower()
        # partial_ratio 用來查 query 中是否存在一段跟 alias 高度相似的子串
        score = fuzz.partial_ratio(query_lower, alias_lower)
        if score >= fuzzy_threshold:
            scored_matches.append({"alias": pair.get("alias", ""),
                                   "tags":  pair.get("tags", []),
                                   "score": score,
                                   })

    if not scored_matches:
        logger.debug(f"無任何命中 alias threshold={fuzzy_threshold})")
        return []

    logger.debug(f"總共命中 {len(scored_matches)} 份筆記， "
                 f"包含： {scored_matches}， "
                 f"相似度分數={[m['score'] for m in scored_matches]}")

    all_matched_tags = [tag for m in scored_matches for tag in m["tags"]]

    if len(scored_matches) <= 1:
        selected_tags = list(dict.fromkeys(all_matched_tags))

    # 多篇命中則統計 tag 出現頻率，只取有重複出現的
    tag_counter = Counter(all_matched_tags)
    selected_tags = [tag for tag, count in tag_counter.items() if count >= min_frequency]

    # 校驗 selected_tags：需要過濾掉向量資料庫裡不存在的 tag（防止 filter 條件無效）
    validated_tags = [t for t in selected_tags if t in known_tags_in_vdb]

    logger.debug(f"命中 {len(scored_matches)} 篇筆記，"
                 f"校驗前 {len(selected_tags)} tags，校驗後 {len(validated_tags)} tags")
    return validated_tags


def _extract_path_via_alias(query: str,
                            alias_tag_pairs: list[dict],
                            fuzzy_threshold: int = 60) -> list[str]:
    """
    模糊比對 alias，回傳命中筆記的 file_path list，而非 tags list。
    由呼叫端決定要用 file_path 還是 tags 做 prefilter。
    """
    query_lower = query.lower()
    matched_paths = []
    seen = set()

    for pair in alias_tag_pairs:
        score = fuzz.partial_ratio(query_lower, pair["alias"].lower())
        if score >= fuzzy_threshold:
            path = pair.get("file_path", "")
            if path and path not in seen:
                seen.add(path)
                matched_paths.append(path)
                logger.debug(f"alias 命中: '{pair['alias']}' → {path} (score={score})")

    return matched_paths


def _build_history_context_message(session_id: str, chat_history_n: int = 5) -> list[dict]:
    """
    讀取本 session 過去的 rag 對話歷史，
    以背景資訊的形式包成獨立的 user/model 對組帶入，
    避免 LLM 把過去的回應誤判為自己當下要接續輸出的內容。
    """
    history_rag_msg = load_chat_history(session_id=session_id,
                                        agent_type="rag",
                                        n=chat_history_n)

    if not history_rag_msg:
        return []

    rag_lines = "\n".join(f"  [{m['role']}] {m['parts'][0]['text']}" for m in history_rag_msg
                          )

    return [{"role": "user",
            "parts": [{"text": f"以下是這個 session 過去的筆記查詢紀錄，供你接續改寫查詢句時參考：\n\n{rag_lines}"}],
             },
            {"role": "model",
            "parts": [{"text": "好的，我已了解先前的討論脈絡，請告訴我這一輪的需求。"}],
             },
            ]


def _r_hyde_rewrite(query: str, history_msg: list[dict], alias_tag_pairs: list[dict], client: genai.Client) -> dict:
    """
    採 HyDE 技術，使用已知 tag 字典引導 LLM 生成假設性筆記內容，同時推薦一個 tag。
    回傳 { "tag": str | None, "hypothetical": new_search_str }
    失敗時 fallback 回傳 {"tag": str | None, "hypothetical": 原始 query str }
    """
    try:
        pair_list = [str(pair) for pair in alias_tag_pairs]
        msg_list = [str(msg_dict) for msg_dict in history_msg]
        prompt = HYDE_SYSTEM_PROMPT.format(pairs="、".join(pair_list), chat_history="、".join(msg_list))
        response = client.models.generate_content(model=HYDE_MODEL,
                                                  contents=[{"role": "user",
                                                             "parts": [{"text": query}]}],
                                                  config=types.GenerateContentConfig(
                                                      system_instruction=prompt,
                                                      temperature=0.3,
                                                      max_output_tokens=500,
                                                  ),
                                                  )
        text = response.text.strip()

        note_line = next((l for l in text.splitlines() if l.startswith("ALIAS:")), "ALIAS: NONE")
        tag_line = next((l for l in text.splitlines() if l.startswith("TAG:")), "TAG: NONE")
        hyde_line = next((l for l in text.splitlines() if l.startswith("HYPOTHETICAL:")), "")

        raw_note = note_line.replace("ALIAS:", "").strip()
        raw_tag = tag_line.replace("TAG:", "").strip()
        hypothetical = hyde_line.replace("HYPOTHETICAL:", "").strip() or query

        # 務必校驗，因為 LLM 可能瞎掰一些本來不存在於筆記庫的 tags
        validated_tag = None
        for pair in alias_tag_pairs:
            if raw_note in pair["alias"] and raw_tag in pair["tags"]:
                validated_tag = raw_tag
                break
        logger.info(f"HyDE: tag={validated_tag}, note={raw_note}, hypothetical='{hypothetical[:30]}...'")
        return {"tag": validated_tag, "hypothetical": hypothetical}

    except Exception as e:
        logger.warning(f"HyDE rewrite 失敗，fallback 用原始 query: {e}")
        return {"tag": None, "hypothetical": query}


def _looks_like_followup(query: str) -> bool:
    """
    判斷 query 是否屬於繼續追問，而非一個新的、岔題的獨立查詢。
    當字數少（<= 100 字）、包含追問訊號詞、不包含排他詞均滿足時，回傳 True 代表追問。
    透過判定是否為追問，來控制是否要在當前查詢中搜尋向量資料庫。

    這是輕量啟發式規則，不走 LLM，避免增加延遲。
    """

    FOLLOWUP_SIGNALS = ["再", "更多", "繼續", "詳細", "追問",
                        "能否", "可以", "那", "然後",
                        "剛才", "上面", "前面", "這個", "那個",
                        "它", "他", "她",
                        "more", "further", "continue",
                        "elaborate", "expand", "go on", "discuss"
                        ]
    EXCLUDE_SIGNALS = ["新", "改", "換", "岔題", "另外",
                       "new", "another", "change", "other"]
    query_stripped = query.strip()
    is_short = len(query_stripped) <= 100
    has_signal = any([s in query_stripped for s in FOLLOWUP_SIGNALS])
    no_exc_signal = all([es not in query_stripped for es in EXCLUDE_SIGNALS])
    return is_short and has_signal and no_exc_signal


def _get_last_filter_tags(db: Database, session_id: str) -> list[str] | None:
    """
    從 chat_history 讀取這個 session 最近一筆 router 紀錄的 filter_tags。
    回傳 list[str] (可能是空 list) 或 None (沒有歷史紀錄 / 上輪是 no_filter_fallback)。
    """
    doc = db["chat_history"].find_one({"session_id": session_id,
                                       "agent_type": "router",
                                       "role": "model",
                                       "content": {"$nin": ["rag_agent", "planning_agent"]},
                                       },
                                      sort=[("timestamp", -1)],  # 取最新一筆
                                      projection={"content": 1,
                                                  "_id": 0
                                                  },
                                      )
    if not doc:
        return None
    try:
        # 注意 find_one 回傳的是 dict，但是 doc 的值是 json-like string，值的部分需轉回 python object
        parsed = json.loads(doc["content"])
        return parsed if isinstance(parsed, list) else None
    except (json.JSONDecodeError, TypeError):
        logger.warning("_get_last_filter_tags: content 反序列化失敗")
        return None


def _get_last_context(db: Database, session_id: str) -> list[str] | None:
    doc = db["chat_history"].find_one({"session_id": session_id,
                                       "agent_type": "router",
                                       "role": "model",
                                       "content": {"$nin": ["rag_agent", "planning_agent"]},
                                       },
                                      sort=[("timestamp", -1)],  # 取最新一筆
                                      projection={"content": 1,
                                                  "_id": 0
                                                  },
                                      )
    if not doc:
        return None
    try:
        # 注意 find_one 回傳的是 dict，但是 doc 的值是 json-like string，值的部分需轉回 python object
        parsed = json.loads(doc["content"])
        if isinstance(parsed, dict):
            return parsed   # {"file_paths": [...], "tags": [...]}
        if isinstance(parsed, list):
            return {"file_paths": None, "tags": parsed}
        return None
    except (json.JSONDecodeError, TypeError):
        logger.warning("_get_last_filter_tags: content 反序列化失敗")
        return None


# ── 主函式 ────────────────────────────────────────────────────────
def route(query: str, session_id: str) -> dict:
    """
    判斷使用者輸入應交給哪個 Agent。

    Args:
        query:      使用者輸入的原始文字
        session_id: 目前對話的 uuid4

    Returns:
        {"agent_target": "rag_agent" | "planning_agent",
         "filter_tags": list[str] | None,
         "search_query": str}   # 真正拿去做 vector_search 的 query 文字
    """
    agent_target = None

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
        agent_target = r1_result
    else:
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
        agent_target = r2_result

    # ── Step 3: 如果導向 rag agent，則對使用者的查詢語句萃取出與現存筆記有關聯的標籤 (tag) ─────────────────
    filter_tags = None
    filter_file_paths = None
    search_query = query
    search_optimize_method = None

    if agent_target == "rag_agent":
        db = get_db_altas()
        known_tags = _load_known_tags(db, "obsidian_vectors")
        alias_tag_pairs = _load_alias_to_tags_map(db, "obsidian_notes")
        # Step 3A: 追問繼承——改繼承 file_paths 而非 tags
        if _looks_like_followup(query):
            inherited = _get_last_context(db, session_id)   # 見下方
            if inherited:
                filter_file_paths = inherited["file_paths"]
                search_optimize_method = "inherited_file_paths_from_last_turn"
                logger.info(f"追問繼承 file_paths: {filter_file_paths}")

        # Step 3B: alias 模糊比對 → 回傳 file_paths
        if not filter_file_paths and not filter_tags:
            matched_paths = _extract_path_via_alias(query, alias_tag_pairs)
            if matched_paths:
                filter_file_paths = matched_paths
                search_optimize_method = "extract_file_paths_via_alias"

        # Step 3C: HyDE → 仍回傳 tag（file_path 層找不到才退到 tag 層）
        if not filter_file_paths and not filter_tags:
            logger.info(f"模糊比對筆記本身 alias 查無結果，改使用 HyDE 重寫查詢")
            client = _get_genai_client()
            history_rag_msg = _build_history_context_message(session_id)
            hyde_result = _r_hyde_rewrite(query, history_rag_msg, alias_tag_pairs, client)
            if hyde_result["tag"]:
                filter_tags = [hyde_result["tag"]]
            search_query = hyde_result["hypothetical"]
            search_optimize_method = "HyDE_rewrite"

        # Step 3D: 全庫退化
        if not filter_file_paths and not filter_tags:
            search_optimize_method = "no_filter_fallback"
            logger.info(f"使用 HyDE 重寫查詢也無效，退回全庫搜索")

        # Step 3E: 存入 chat_history——改存 file_paths
        save_chat_history(
            session_id=session_id,
            agent_type="router",
            role="model",
            message_text=json.dumps({"file_paths": filter_file_paths,
                                    "tags": filter_tags}, ensure_ascii=False),
            metadata={"agent_target": agent_target,
                      "search_query": search_query,
                      "search_optimize_method": search_optimize_method},
        )
        return {"agent_target": agent_target,
                "filter_tags": filter_tags,
                "filter_file_paths": filter_file_paths,
                "search_query": search_query,
                "search_optimize_method": search_optimize_method}

        # # Step 3A: 先確認是否屬於使用者追問：短句且上輪有 filter_tags，直接沿用，不再重新找 tags ──────
        # if _looks_like_followup(query):
        #     inherited = _get_last_filter_tags(db, session_id)
        #     if inherited:
        #         filter_tags = inherited
        #         search_optimize_method = "inherited_tags_from_last_turn"
        #         logger.info(f"追問繼承 filter_tags: {filter_tags}，跳過重新抽取")
        #     else:
        #         logger.info(f"此波追問，無繼承 filter_tags，需重新抽取 tag")

        # # Step 3B: alias 模糊比對，用來反查 tags，專治 tags 沒有正確標示、但是筆記名稱本身有符合查詢語意的時候
        # if not filter_tags:
        #     logger.info(f"模糊比對筆記本身 alias...")
        #     tags_from_alias = _extract_tags_via_alias(query, alias_tag_pairs, known_tags)
        #     if tags_from_alias:
        #         filter_tags = tags_from_alias
        #         search_optimize_method = "extract_tags_via_alias"

        # # Step 3C: HyDE rewrite，根據筆記庫真實存在的 tags 來重寫使用者的查詢，讓下一關的 rag agent 更能理解使用者意圖
        # if not filter_tags:
        #     logger.info(f"模糊比對筆記本身 alias 查無結果，改使用 HyDE 重寫查詢")
        #     client = _get_genai_client()
        #     history_rag_msg = _build_history_context_message(session_id)
        #     hyde_result = _r_hyde_rewrite(query, history_rag_msg, alias_tag_pairs, client)
        #     if hyde_result["tag"]:
        #         filter_tags = [hyde_result["tag"]]
        #     search_query = hyde_result["hypothetical"]
        #     search_optimize_method = "HyDE_rewrite"

        # # Step 3D: 都沒找到 → filter_tags 保持 None，退階成全庫搜索
        # if not filter_tags:
        #     logger.info(f"使用 HyDE 重寫查詢也無效，退回全庫搜索")

        # Step 3E: 存入 chat_history
        # save_chat_history(session_id=session_id,
        #                   agent_type="router",
        #                   role="model",
        #                   message_text=json.dumps(filter_tags, ensure_ascii=False),
        #                   metadata={
        #                       "agent_target":           agent_target,
        #                       "search_query":           search_query,
        #                       "search_optimize_method": search_optimize_method,
        #                   },
        #                   )

    # return {"agent_target": agent_target,
    #         "filter_tags": filter_tags,
    #         "search_query": search_query,
    #         "search_optimize_method": search_optimize_method}
