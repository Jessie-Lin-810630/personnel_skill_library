"""與 MongoDB Atlas 互動存取與 Router/ RAG/ Planning Agent 的對話紀錄。

職責:
  load_chat_history(): 讀取某 session 最近 N 輪對話，
                       回傳格式直接對齊 google-genai SDK 的 contents 格式，
                       讀完即可送進 Vertex AI API，不需二次轉換。

  save_chat_history(): 寫入一筆對話紀錄到 chat_history collection，
                       含層 3 安全防護:
                         - 單筆 content 上限 2000 字元（截斷）
                         - 單一 session 上限 100 筆（超過刪最舊）

依賴:
  - pymongo
"""

from datetime import datetime, timezone
from typing import Literal

from dotenv import load_dotenv
from loguru import logger
from pymongo import DESCENDING
from utils.interact_with_mongodb import get_db_atlas

# ── 常數 ──────────────────────────────────────────────────────────
AgentType = Literal["router", "rag", "planning"]
Role = Literal["user", "model"]

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
    """讀取某 session、某 agent 最近 N 輪對話。

    Args:
        session_id (str):  目前對話的 uuid4
        agent_type (AgentType):  "router" | "rag" | "planning"
            各 Agent 只讀自己的歷史，避免 rag 脈絡污染 planning 推理
        role (Role | None): 可選，只讀特定 role ("user" | "model") 的紀錄；None 則 user/model 都讀
        n (int): 輪數 (1 輪 = 1 筆 user + 1 筆 model)，預設 3 輪，實際讀取筆數 = n*2

    Returns:
        list[dict]，格式對齊 google-genai SDK 的 contents 參數:
        [
            {"role": "user",  "parts": [{"text": "..."}]},
            {"role": "model", "parts": [{"text": "..."}]},
            ...
        ]
        時間順序為舊到新，故可直接 append 新訊息後送入 model API。

    注意:
        若該 session / agent_type 尚無紀錄（例如對話第一輪），回傳空 list []，
        呼叫方不需要做 None 檢查。
    """
    db = _get_db()
    collection = db["chat_history"]

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
    """寫入一筆對話紀錄，含層 3 安全防護。

    Args:
        session_id:  目前對話的 uuid4
        agent_type:  "router" | "rag" | "planning"
        role:        "user" | "model"，對齊 google-genai SDK 格式
        message_text:     訊息純文字，超過 2000 字元自動截斷
        metadata:    可選，dict，結構參考 Schema 設計:
                     {
                         "model":            "gemini-2.5-flash-lite",
                         "intent_score":     0.92,        # router 用
                         "retrieved_chunks": [{"file_path": "01_dir/xxx.md",
                                               "chunk_index": 1,
                                               "score": 0.88013,
                                            }],   # rag / planning 用
                         "note_files":       ["xxx.md"],  # rag / planning 用
                     }

    防護邏輯:
        1. content(即 message_text 引數) 超過 2000 字元 → 截斷並記 warning log
        2. 同一 session 已達 100 筆 → 刪除最舊一筆再寫入，維持上限
    """
    CONTENT_MAX_CHARS = 2000  # 安全防護：單筆 content 上限
    SESSION_MAX_DOCS = 100  # 安全防護：單一 session 上限

    db = _get_db()
    collection = db["chat_history"]

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
