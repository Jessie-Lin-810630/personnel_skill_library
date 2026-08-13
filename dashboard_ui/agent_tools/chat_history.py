"""與 MongoDB Atlas 互動，負責 Router、RAG、Planning 三個 agent 的對話紀錄存取。

1. 函式 load_chat_history 讀取某 session 最近 N 輪對話，回傳格式直接對齊 google-genai SDK 的 contents 格式，
   讀完即可送進 Agent Platform API，不需二次轉換。
2. 函式 save_chat_history 寫入一筆對話紀錄到 chat_history collection，並帶三層安全防護：
   單筆 content 超過 2000 字元就截斷、單一 session 超過 100 筆就刪最舊。
"""

from datetime import datetime, timezone

from agent_tools.types_and_constants import CHAT_HISTORY_COLLECTION, AgentType, Role
from dotenv import load_dotenv
from loguru import logger
from pymongo import DESCENDING
from utils.interact_with_mongodb import get_db_atlas

# ── 資料庫連線函式與環境變數呼叫 ──────────────────────────────────────────────────────────
_get_db = get_db_atlas
load_dotenv()

# ── load ──────────────────────────────────────────────────────────


def load_chat_history(
    session_id: str,
    agent_type: AgentType,
    role: Role | None = None,
    n: int = 3,
) -> list[dict]:
    """讀取指定 session 中，某個 agent 最近幾輪的對話紀錄。

    先依時間由新到舊取出所需筆數，再反轉成由舊到新，以符合模型 API 對訊息順序的要求。
    各個 agent 只讀自己的歷史，避免 RAG 的對話脈絡干擾 Planning 的推理。

    Note:
        該 session 與 agent 尚無任何紀錄時回傳空 list，例如對話的第一輪，
        因此呼叫方不需要另外做 None 檢查。資料庫查詢失敗時同樣回傳空 list，
        讓該輪 agent 在沒有歷史的情況下照常運作。

    Args:
        session_id: 目前對話的 uuid4。
        agent_type: 要讀取哪一個 agent 的歷史，可為 router、rag 或 planning。
        role: 只讀取特定角色的紀錄，可為 user 或 model；預設為 None，代表兩種角色都讀。
        n: 要回讀幾輪，一輪指一筆 user 訊息加一筆 model 訊息，預設 3 輪。
            兩種角色都讀時實際讀取筆數為輪數的兩倍。各 agent 的建議值定義在
            RouterAgent、RagAgent、PlanningAgent 三個常數類別的 CHAT_HISTORY_N。

    Returns:
        對齊 google-genai SDK contents 參數格式的訊息清單，每筆含 role 與 parts 兩個鍵，
        時間順序由舊到新，可直接接上本輪新訊息後送進模型 API；查無紀錄或查詢失敗時為空 list。
    """
    db = _get_db()
    collection = db[CHAT_HISTORY_COLLECTION]

    # 讀取條件: 同 session_id + 同 agent_type
    # 排序: timestamp 降冪排列（最近的排第一筆），取前 n*2 筆
    try:
        if role is None:
            docs = list(
                collection.find(
                    {"session_id": session_id, "agent_type": agent_type},
                    {"_id": 0, "role": 1, "content": 1},  # 只取需要的欄位
                )
                .sort("timestamp", DESCENDING)
                .limit(n * 2)
            )
            if not docs:
                logger.debug(f"load_chat_history: 無歷史紀錄 (session={session_id[:8]}..., agent={agent_type})")
                return []
        else:  # 留著備用，如果需要只看特定 user 或 model 的紀錄
            docs = list(
                collection.find(
                    {"session_id": session_id, "agent_type": agent_type, "role": role},
                    {"_id": 0, "role": 1, "content": 1},  # 只取需要的欄位
                )
                .sort("timestamp", DESCENDING)
                .limit(n)
            )
            if not docs:
                logger.debug(
                    f"load_chat_history: 無歷史紀錄 (session={session_id[:8]}..., agent={agent_type}, role={role})"
                )
                return []
    except Exception as e:
        logger.error(
            f"load_chat_history 失敗: (session={session_id[:8]}..., agent={agent_type}, role={role}), \nmsg= {e}"
        )
        return []  # DB 出錯回空歷史，避免 docs 未定義而 UnboundLocalError，讓該輪 agent 照常繼續

    # 再反轉成升冪，符合 google-genai contents 的時間順序
    docs.reverse()

    # 轉換為 google-genai SDK contents 格式
    # SDK 期望: [{"role": "user"|"model", "parts": [{"text": "..."}]}, ...]
    contents = [{"role": doc["role"], "parts": [{"text": doc["content"]}]} for doc in docs]

    logger.debug(f"load_chat_history: 讀取 {len(contents)} 筆 (session={session_id[:8]}…, agent={agent_type}, n={n})")

    return contents


# ── save ──────────────────────────────────────────────────────────


def save_chat_history(
    session_id: str,
    agent_type: AgentType,
    role: Role,
    message_text: str,
    metadata: dict | None = None,
) -> None:
    """寫入一筆對話紀錄到 chat_history，並套用兩道容量防護。

    第一道防護限制單筆訊息長度，超過 2000 字元即截斷並記錄一筆 warning。
    第二道防護限制單一 session 的紀錄筆數，已達 100 筆時先刪掉最舊的一筆再寫入，維持總量不成長。
    寫入過程若發生例外只記錄 error，不向上拋出，避免資料庫問題中斷正在進行的對話。

    Args:
        session_id: 目前對話的 uuid4。
        agent_type: 產生這筆紀錄的 agent，可為 router、rag 或 planning。
        role: 訊息角色，可為 user 或 model，對齊 google-genai SDK 的格式。
        message_text: 訊息純文字，超過長度上限時自動截斷。
        metadata: 隨紀錄一起存放的附加資訊，預設為 None。常見的鍵有 model 記錄使用的模型、
            intent_score 記錄 router 的意圖分數、retrieved_chunks 記錄 RAG 與 Planning 檢索到的
            chunk 明細、note_files 記錄去重後的來源筆記檔名。

    Returns:
        None: 只寫入資料庫，不回傳值。
    """
    CONTENT_MAX_CHARS = 2000  # 安全防護：單筆 content 上限
    SESSION_MAX_DOCS = 100  # 安全防護：單一 session 上限

    db = _get_db()
    collection = db[CHAT_HISTORY_COLLECTION]

    # ── 防護 1：message_text 長度截斷 ──────────────────────────────────
    if len(message_text) > CONTENT_MAX_CHARS:
        logger.warning(
            f"save_chat_history: message_text 超過 {CONTENT_MAX_CHARS} 字元，自動截斷 "
            f"(session={session_id[:8]}…, role={role})"
        )
        message_text = message_text[:CONTENT_MAX_CHARS]

    # ── 防護 2：session 筆數上限，超過則刪最舊 ───────────────────
    session_count = collection.count_documents({"session_id": session_id})
    try:
        if session_count >= SESSION_MAX_DOCS:
            # find_one 搭配降序只是為了定位；實際刪最舊要用升序找第一筆
            # 使用 find_one ，以確保回傳的是 dict，如果用 find() 則需要補上 iterate 或 list()
            oldest = collection.find_one(
                {"session_id": session_id},
                sort=[("timestamp", 1)],  # 升序：最舊的排第一
            )
            if oldest:
                collection.delete_one({"_id": oldest["_id"]})
                logger.warning(
                    f"save_chat_history: session 已達 {SESSION_MAX_DOCS} 筆上限，"
                    f"刪除最舊一筆 (session={session_id[:8]}…)"
                )

        # ── 寫入 ──────────────────────────────────────────────────────
        doc = {
            "session_id": session_id,
            "agent_type": agent_type,
            "role": role,
            "content": message_text,
            "timestamp": datetime.now(timezone.utc),
            "metadata": metadata or {},
        }

        collection.insert_one(doc)
        logger.debug(f"save_chat_history: 寫入成功 (session={session_id[:8]}…, agent={agent_type}, role={role})")
    except Exception as e:
        logger.error(
            f"save_chat_history 失敗: (session={session_id[:8]}..., agent={agent_type}, role={role}), msg= {e}"
        )
