"""作為 RAG agent 執行向量檢索的前置工作: Query Transformation。

職責：
    1. _load_known_tags():
        讀取 MongoDB 向量資料庫取出真實存在的資料 tags
    2. _load_alias_to_tags_map():
        讀取 MonogoDB 筆記元數據資料庫取出筆記名稱 (alias) 與對應的 tags
    3. _format_history_for_prompt():
        將 agent_tools.chat_history() 回傳的歷史問答脈絡，拼成 model 看得懂的 user prompt 字串
    4. rewrite_query():
        - 接收歷史對話紀錄資料到 user prompt，接收 alias-tag 對照表中，傳入 system prompt
        - 將使用者最新的追問改寫成一個「不依賴歷史就能獨立理解」的完整問句
        - 並推薦 3-5 個 tags，串接到 rewritten query 做 query expansion
        - 回傳 rewritten_query (給 reranker 用) 與 expanded_query (給 vector_search 用)

設計決策：
  - expanded_query 用於 vector_search 粗篩，需摻入 tag 關鍵字增強語意信號，提高 recall
  - rewritten_query 用於 reranker 根據語意關聯度做排序，但不摻 tag 雜訊避免關鍵字干擾 cross-encoder 判斷
"""

from google import genai
from google.genai import types
from loguru import logger
from pymongo.database import Database

# ── 常數 ────────────────────────────────────────────────────────
REWRITE_MODEL = "gemini-2.5-flash-lite"


# ── 參考資料載入（rewriter 的 tag 字典來源）──────────────────────
def _load_known_tags(db: Database, collection: str = "obsidian_vectors_multimodal") -> set[str]:
    """從向量庫撈出所有出現過的 tag，做為合法 tag 字典。

    用於校驗 LLM 推薦的 tags，避免 LLM 自發創意產出不存在的 tags。

    Args:
        db:         pymongo Database 物件。
        collection: 向量集合名稱，預設 "obsidian_vectors_multimodal"。

    Returns:
        該集合 tags 欄位所有出現過的 tag 字串集合。
    """
    coll = db[collection]
    return set(coll.distinct("tags"))


def _load_alias_to_tags_map(db: Database, collection: str = "obsidian_notes") -> list[dict]:
    """從 obsidian_notes 撈出 {alias: [tags]} 的對照表。

    若一篇筆記有多個 alias，回傳時會攤平成獨立 pair 方便後續比對，例如：
        [ {alias-1 of note-1: [tagA, B, C]},
          {alias-2 of note-1: [tagA, B, C]},
          {alias-1 of note-2: [tagB, C, D, E]},
        ]

    Args:
        db:         pymongo Database 物件。
        collection: 筆記集合名稱，預設 "obsidian_notes"。

    Returns:
        攤平後的 alias-tag pair list，每筆為
        {"alias": str, "tags": list[str], "file_path": str}。
    """
    coll = db[collection]
    cursor = coll.find({}, {"_id": 0, "alias": 1, "tags": 1, "file_name": 1, "file_path": 1})
    alias_tag_pairs = []
    for doc in cursor:
        file_path = doc.get("file_path", "")
        tag = doc.get("tags", [])
        # file name 也當作 alias 之一，且排在自己的 alias keys 前頭
        alias_tag_pairs.append(
            {
                "alias": doc.get("file_name", "").replace(".md", "").strip(),
                "tags": tag,
                "file_path": file_path,
            }
        )

        for alias in doc.get("alias", []):
            alias_tag_pairs.append(
                {
                    "alias": alias,
                    "tags": tag,
                    "file_path": file_path,
                }
            )

    return alias_tag_pairs


REWRITE_SYSTEM_PROMPT = """你是一個筆記檢索系統的查詢改寫器。

## 你的任務
使用者會在多輪對話中追問，後續問題常省略主詞、指代模糊或打錯字。
你需要根據「對話歷史」與「使用者最新問題」，完成以下兩件事：

### 任務 1：改寫查詢
將使用者最新問題改寫成一個**不依賴對話歷史就能獨立理解**的完整查詢句。
- 保留所有技術名詞的正確拼寫
- 補全省略的主詞與上下文
- 不要回答問題本身

### 任務 2：推薦標籤
以下是這個筆記庫裡實際存在的 alias 與 tags 對照表：
{pairs}

從上面的對照表中，選出與改寫後查詢「最相關」的 3 到 5 個 tags。
- 只能從對照表中已存在的 tags 裡選，不可自行創造
- 如果都不相關，輸出"None"

## 輸出格式（嚴格遵守，不要有其他文字）
REWRITTEN: <改寫後的完整查詢>
TAGS: <tag1, tag2, tag3>或<None>
"""


def _format_history_for_prompt(history_msgs: list[dict]) -> str:
    """將 load_chat_history() 回傳的 history 格式化成可讀文字。

    供 rewrite prompt 使用。

    **Note:**
        - load_chat_history() 回傳的歷史訊息格式為: {"role": "user"/"model", "parts": [{"text": "..."}]}
        - 使用的 agent: RAG agent

    Args:
        history_msgs: load_chat_history() 回傳的歷史訊息 list。

    Returns:
        每行 "使用者: ..." / "助手: ..." 的可讀文字；無歷史時回傳 "(無對話歷史)"。
    """
    if not history_msgs:
        return "(無對話歷史)"

    lines = []
    for msg in history_msgs:
        role = msg.get("role", "unknown")
        parts = msg.get("parts", [])
        text = parts[0].get("text", "") if parts else ""

        # 截斷過長的 model 回覆，避免 prompt 膨脹
        if role == "model" and len(text) > 300:
            text = text[:300] + "....(省略)"
        prefix = "使用者" if role == "user" else "助手"
        lines.append(f"{prefix}: {text}")

    return "\n".join(lines)


def rewrite_query(
    query: str,
    alias_tag_pairs: list[dict],
    chat_history_msgs: list[dict],
    known_tags: set[str],
    client: genai.Client | None = None,
) -> dict:
    """改寫原始 query 並推薦 tags 做 query expansion。

    以加強 vector search 時能偏好這些 tags，找到與原始 query 相近的 data chunks，
    但不像關鍵字過濾策略硬性要求只能找含有這些 tags 的筆記。

    **Note:**
        使用的 agent: RAG agent

    Args:
        query:              使用者原始輸入
        alias_tag_pairs:    筆記 alias-tag 對照表，例如
            [{"alias": "noteA", "tags": [tag1, tag2, tag3]}, {"alias": "noteB", "tags": [tag1, tag3, tag7]}]
        chat_history_msgs:  最近 N 輪 history (genai SDK 格式)
        known_tags:         向量資料庫裡實際存在的 tag set (用來校驗 LLM 推薦的 tag)
        client:             genai.Client object

    Returns:
        {
            "rewritten_query": str,    # 改寫後的獨立問句（給 reranker 用）
            "expanded_query": str,     # rewritten + tags 串接（給 rag 做 vector_search 增強向量語意信號用）
            "recommended_tags": list[str],  # LLM 推薦且已校驗的 tags
        }

    """
    # 組裝 system prompt
    pairs_str = "\n".join(
        f"- alias: {p.get('alias', '')} → tags: {p.get('tags', [])}"
        for p in alias_tag_pairs[:100]  # 限制數量，避免 prompt 過長
    )
    system_prompt = REWRITE_SYSTEM_PROMPT.format(pairs=pairs_str)

    # 組裝 content (user message) : 包含 history + 當前問題
    history_text = _format_history_for_prompt(chat_history_msgs)
    user_content = f"對話歷史：\n{history_text}\n\n---\n\n使用者最新問題：{query}"

    try:
        response = client.models.generate_content(
            model=REWRITE_MODEL,
            contents=[{"role": "user", "parts": [{"text": user_content}]}],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
                max_output_tokens=300,
            ),
        )
        text = response.text.strip()
        logger.debug(f"query_rewriter: raw output=\n{text[:120]}")

        # 解析出第一行有 REWRITTEN 的段落
        rewritten_line = next((line for line in text.splitlines() if line.startswith("REWRITTEN:")), "")
        rewritten = rewritten_line.replace("REWRITTEN:", "").strip() or query

        # 解析出第一行有 TAGS 的段落
        tags_line = next((line for line in text.splitlines() if line.startswith("TAGS:")), "")
        raw_tags = [
            t.strip() for t in tags_line.replace("TAGS:", "").strip().split(",") if t.strip() and t.strip() != "None"
        ]

        # 校驗：只保留真實存在於向量資料庫的 tags
        known_tags_lower = set(kn.lower() for kn in known_tags)  # 不計大小寫
        validated_tags = [t for t in raw_tags if t.lower() in known_tags_lower]
        logger.debug(
            f"query_rewriter: \nrewritten='{rewritten[:50]}...',"
            f"\nvalidated tag amount={len(validated_tags)} / {len(raw_tags)}', "
            f"\nraw_tags={raw_tags}, validated_tags={validated_tags}"
        )

        # 組裝 expanded_query：rewritten query + tag 關鍵字
        tag_suffix = " ".join(validated_tags) if validated_tags else ""
        expanded_query = f"{rewritten} {tag_suffix}".strip()

        return {
            "rewritten_query": rewritten,
            "expanded_query": expanded_query,
            "recommended_tags": validated_tags,
        }

    except Exception as e:
        logger.warning(f"query_rewriter: 失敗，fallback 用原始 query: {e}")
        return {
            "rewritten_query": query,
            "expanded_query": query,
            "recommended_tags": [],
        }
