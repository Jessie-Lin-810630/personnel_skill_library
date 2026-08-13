"""RAG agent 執行向量檢索前的 Query Transformation 前置工作。

1. 函式 load_known_tags 從 MongoDB 向量資料庫取出真實存在的資料 tags。
2. 函式 load_alias_to_tags_map 從 MongoDB 筆記元數據資料庫取出筆記名稱與其對應的 tags。
3. 函式 _format_history_for_prompt 把歷史問答脈絡拼成 model 看得懂的 user prompt 字串。
4. 函式 rewrite_query 把使用者最新的追問改寫成不依賴歷史也能獨立理解的完整問句，
   同時推薦 3 到 5 個 tags 做 query expansion，
   回傳給 reranker 用的 rewritten_query 與給 vector_search 用的 expanded_query。

設計決策：
  - expanded_query 用於 vector_search 粗篩，摻入 tag 關鍵字增強語意信號以提高 recall。
  - rewritten_query 用於 reranker 依語意關聯度排序，不摻 tag 雜訊，避免關鍵字干擾 cross-encoder 判斷。
"""

from agent_tools.types_and_constants import NoteCollectionBeforeEmbedding, NoteCollections, RewriterAgent
from google import genai
from google.genai import types
from loguru import logger
from pymongo.database import Database


# ── 參考資料載入（rewriter 的 tag 字典來源）──────────────────────
def load_known_tags(db: Database, collection: NoteCollections = NoteCollections.VECTOR) -> set[str]:
    """從向量庫撈出所有出現過的標籤，作為合法標籤字典。

    這份字典用來校驗 LLM 推薦的標籤，避免模型自行捏造出資料庫裡不存在的標籤。

    Args:
        db: pymongo Database 物件。
        collection: 向量 collection 名稱，預設為 NoteCollections.VECTOR。

    Returns:
        該 collection 的 tags 欄位所有出現過的標籤字串集合。
    """
    coll = db[collection]
    return set(coll.distinct("tags"))


def load_alias_to_tags_map(
    db: Database, collection: NoteCollectionBeforeEmbedding = NoteCollections.OBSIDIAN
) -> list[dict]:
    """從筆記 metadata 撈出別名與標籤的對照表，供改寫器推薦標籤時參考。

    只撈 status 為 archived 且 embedded_status 為 True 的筆記，也就是已歸檔且已完成向量化的部分。
    別名與標籤取自各來源自己的 frontmatter 欄位，Obsidian 取 archived_md_frontmatter，
    OneNote 取 md_frontmatter，檔案路徑一律回填歸檔後的 Markdown 路徑。
    一篇筆記的檔名本身也視為別名之一，並排在自訂別名前面；
    多個別名會攤平成多筆獨立的對照，方便後續逐筆比對。

    Args:
        db: pymongo Database 物件。
        collection: 筆記 metadata 所在的 collection，可傳入 NoteCollections.OBSIDIAN 或
            NoteCollections.ONENOTE，預設為前者。

    Returns:
        攤平後的別名對照清單，每筆含 alias、tags、file_path 三個鍵。
    """
    coll = db[collection]
    if collection == "obsidian_note_metadata":
        projection = {
            "_id": 0,
            "alias": "$archived_md_frontmatter.alias",
            "tags": "$archived_md_frontmatter.tags",
            "file_name": 1,
            "file_path": "$archived_md_path",
        }

    elif collection == "onenote_note_metadata":
        projection = {
            "_id": 0,
            "alias": "$md_frontmatter.alias",
            "tags": "$md_frontmatter.tags",
            "file_name": "$page_title",
            "file_path": "$archived_md_path",
        }

    else:
        projection = {"_id": 0, "alias": 1, "tags": 1, "file_name": 1, "file_path": 1}

    cursor = coll.find({"status": "archived", "embedded_status": True}, projection)
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
    """把對話歷史攤平成一段可讀文字，嵌進改寫用的 prompt。

    每則訊息依角色標上使用者或助手前綴，逐行排列。
    助手的回覆超過 300 字元時會截斷，避免歷史內容把 prompt 撐得過長。

    Note:
        呼叫方為 RAG agent。

    Args:
        history_msgs: load_chat_history 回傳的歷史訊息清單，每筆含 role 與 parts 兩個鍵。

    Returns:
        以換行分隔的可讀文字；沒有歷史時回傳表示無對話歷史的提示字串。
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
    """把使用者的追問改寫成獨立問句，並推薦標籤做查詢擴展。

    LLM 依對話歷史與別名對照表產出改寫後問句與推薦標籤，推薦標籤會再以合法標籤字典校驗一次，
    不在字典內的一律剔除。改寫後問句串上通過校驗的標籤即為擴展問句。
    擴展問句只是在向量檢索時加強語意信號，讓模型偏好帶有這些標籤的筆記，
    並不像前置篩選那樣硬性要求筆記必須帶有這些標籤。
    呼叫模型失敗時退回使用者原始問句，讓檢索流程照常進行。

    Note:
        呼叫方為 RAG agent。

    Args:
        query: 使用者原始輸入。
        alias_tag_pairs: 由 load_alias_to_tags_map 產出的別名與標籤對照清單，
            為控制 prompt 長度只取前 100 筆。
        chat_history_msgs: 最近幾輪的對話歷史，格式對齊 google-genai SDK。
        known_tags: 向量庫裡實際存在的標籤集合，用來校驗模型推薦的標籤。
        client: google-genai Client 物件。

    Returns:
        含三個鍵的 dict：rewritten_query 為改寫後的獨立問句，交給 reranker 評分；
        expanded_query 為改寫後問句串上推薦標籤，交給向量檢索增強語意信號；
        recommended_tags 為通過校驗的推薦標籤清單。
    """
    # 組裝 system prompt
    pairs_str = "\n".join(
        f"- alias: {p.get('alias', '')} → tags: {p.get('tags', [])}"
        for p in alias_tag_pairs[:100]  # ⚠️ 限制數量，避免 prompt 過長，但有優化空間
    )
    system_prompt = REWRITE_SYSTEM_PROMPT.format(pairs=pairs_str)

    # 組裝 content (user message) : 包含 history + 當前問題
    history_text = _format_history_for_prompt(chat_history_msgs)
    user_content = f"對話歷史：\n{history_text}\n\n---\n\n使用者最新問題：{query}"

    try:
        response = client.models.generate_content(
            model=RewriterAgent.MODEL,
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
