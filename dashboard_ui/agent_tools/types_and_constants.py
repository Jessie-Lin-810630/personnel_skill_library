"""RAG agent 相關的共用常數與型別集中處。

集中「共用/config 類」常數：model 名、top-K、維度、collection/index 名、keyword、型別別名。
大型 prompt 字串刻意留在各自 script（多含 str.format() 佔位、需就近搭配上下文變數），不集中於此。
env variable（os.getenv()）驅動的常數亦不放這裡。
"""

from enum import Enum
from typing import Final, Literal


# ── MongoDB Atlas 集合 ──────────────────────────────────────────────
class NoteCollections(str, Enum):
    OBSIDIAN = "obsidian_note_metadata"
    ONENOTE = "onenote_note_metadata"
    VECTOR = "note_vectors_multimodal"


CHAT_HISTORY_COLLECTION = "chat_history"  # 對話紀錄表


# ── 型別別名 ──────────────────────────────────────────────
NoteCollectionBeforeEmbedding = Literal[NoteCollections.OBSIDIAN, NoteCollections.ONENOTE]
AgentType = Literal["router", "rag", "planning"]
Role = Literal["user", "model"]


# ── AI 模型相關常數（按業務目的分類的命名空間 class；屬性以 Final 標唯讀）──────────
class EmbeddingModel:
    """query 向量化與 Atlas 向量檢索的設定（與入庫側 ETL 1:1 對齊）。"""

    MODEL: Final = "gemini-embedding-2"
    DIM: Final = 1536
    VECTOR_INDEX: Final = "obsidian_vectors_index2"


class RouterAgent:
    """意圖分類 agent（R1 關鍵字快篩 + R2 LLM 分類）。"""

    MODEL: Final = "gemini-2.5-flash-lite"
    CHAT_HISTORY_N: Final = 3
    # R1 關鍵字集合：router 用來判斷使用者意圖偏 planning 或 rag（故歸 RouterAgent 而非各 agent）
    PLANNING_KEYWORDS: Final = [
        "學習路徑",
        "學習地圖",
        "學習計畫",
        "怎麼學",
        "如何學",
        "建議學",
        "規劃",
        "路線圖",
        "roadmap",
        "學習建議",
        "技能樹",
        "往哪個方向",
        "轉職",
        "接下來學什麼",
    ]
    RAG_KEYWORDS: Final = [
        "查詢",
        "查",
        "搜尋",
        "找",
        "有沒有",
        "筆記裡",
        "摘要",
        "幫我看",
        "有什麼",
        "整理",
        "列出",
        "summary",
        "search",
        "retrieve",
    ]


class RagAgent:
    """筆記語意查詢 agent（rewrite → search → rerank → generate）。"""

    MODEL: Final = "gemini-2.5-flash-lite"
    TOP_K: Final = 5
    CHAT_HISTORY_N: Final = 3


class PlanningAgent:
    """個人化學習路徑規劃 agent。"""

    MODEL: Final = "gemini-2.5-flash"  # 推理能力更強模型
    TOP_K: Final = 10
    CHAT_HISTORY_N: Final = 5


class Reranker:
    """Cohere cross-encoder 重排。"""

    MODEL: Final = "rerank-v3.5"
    TOP_N: Final = 5


class RewriterAgent:
    """query 改寫 + tag 推薦（RAG 檢索前置）。"""

    MODEL: Final = "gemini-2.5-flash-lite"
