"""agents 共用的格式化輔助函式，集中 rag_agent / planning_agent / intent_router

職責：
    1. build_context():
        把 vector_search 的 chunks 組成純文字 context block
    2. build_source_list():
        把 chunks 去重成回傳給 UI 的來源清單
    3. build_history_context_message():
        把某 agent 的歷史對話包成獨立 user/model 對組

依賴:
 1. agent_tools/chat_history.py
"""

from agent_tools.chat_history import load_chat_history

# 帶歷史脈絡時，model 端統一的確認回應，避免 LLM 把歷史誤判為自己當下要接續輸出的內容。
_HISTORY_ACK = "好的，我已了解先前的討論脈絡，請告訴我這一輪的需求。"


def build_context(chunks: list[dict]) -> str:
    """將 vector_search() 回傳的 top-K chunks 組裝成純文字 context block。

    每個 chunk 標注來源，讓模型知道每段文字出自哪份筆記。

    **Note:**
        使用的 agent: RAG agent / Planning agent
        若 chunk 帶有 rerank_score (經過 reranker 精排) 會一併標注相關度。

    **格式範例:**
        [來源 1] 檔案: SQL筆記.md | 章節: SQL > DQL > SELECT | 相關度: 0.9
        SELECT 用來從資料表中選取欄位...

        [來源 2] 檔案: MongoDB筆記.md | 章節: MongoDB > Aggregation
        $match 用來過濾文件...

    Args:
        chunks: vector_search()（或經 reranker 精排後）回傳的 chunk list，
            每筆至少需含 file_name 與 content，選用 section、rerank_score。

    Returns:
        以連續兩個換行分隔各來源區塊的純文字 context block 字串。
    """
    blocks = []
    for i, chunk in enumerate(chunks, start=1):
        header = f"[來源 {i}] 檔案: {chunk['file_name']} | 章節: {chunk.get('section', '')}"
        rerank_score = chunk.get("rerank_score")
        if rerank_score is not None:
            header += f" | 相關度: {rerank_score}"
        blocks.append(f"{header}\n{chunk['content']}")
    return "\n\n".join(blocks)


def build_source_list(chunks: list[dict]) -> list[dict]:
    """組裝準備回傳給呼叫方 (Streamlit UI) 的來源清單。

    包含去重後的 "file_name + section 組合"。

    **Note:**
        使用的 agent: RAG agent / Planning agent
        planning 的 chunks 未經 reranker，rerank_score 會是 0。

    Args:
        chunks: vector_search()（或經 reranker 精排後）回傳的 chunk list。

    Returns:
        [{
         "file_name":  "某份筆記檔案名稱.md",
         "section":  "一個筆記資料塊所屬的文章標題",
         "vector_score":  "提問與筆記資料塊在向量空間上的相似度評分，小數點後四位",
         "rerank_score":  "提問與筆記資料塊在語意上的相關性評分，小數點後四位"
         }, {}]
    """
    seen = set()
    sources = []
    for chunk in chunks:
        key = (chunk["file_name"], chunk.get("section", ""))
        if key not in seen:
            seen.add(key)
            sources.append(
                {
                    "file_name": chunk["file_name"],
                    "section": chunk.get("section", ""),
                    "vector_score": round(chunk.get("score", 0), 4),
                    "rerank_score": round(chunk.get("rerank_score", 0), 4),
                }
            )
    return sources


def build_history_context_message(session_id: str, agent_type: str, intro: str, chat_history_n: int = 5) -> list[dict]:
    """讀取本 session 過去某 agent 的對話歷史。

    以背景資訊的形式包成獨立的 user/model 對組帶入，
    避免 LLM 把過去的回應誤判為自己當下要接續輸出的內容。

    **Note:**
        使用的 agent: Planning agent

    Args:
        session_id:     目前對話的 uuid4
        agent_type:     讀取哪個 agent 的歷史，例如 "rag" | "planning"
        intro:          引言文字（不含歷史內容本身），用以說明這段背景的用途
        chat_history_n: 回讀幾輪歷史

    Returns:
        若無歷史回傳 []，否則回傳 [user 引言+歷史, model 確認] 兩筆。
    """
    # [ {"role": "user", "parts": [{"text": "..."}]},
    #   {"role": "model", "parts": [{"text": "..."}]},
    #   ...
    # ]
    history_msg = load_chat_history(session_id=session_id, agent_type=agent_type, n=chat_history_n)
    if not history_msg:
        return []
    # lines = [user] find the notes...
    lines = "\n".join(f"  [{m['role']}] {m['parts'][0]['text']}" for m in history_msg)

    # [{"role": "user", "parts": ["text": "以下是跟 xx agent 的歷史對話紀錄
    #                                      [user] find the notes...
    #                               ]
    #
    #   },
    #  {"role": "model", "parts": ["text": "好的，我已了解...，請告訴我這一輪的需求" ]
    #  }]
    return [
        {
            "role": "user",
            "parts": [{"text": f"{intro}\n\n{lines}"}],
        },
        {
            "role": "model",
            "parts": [{"text": _HISTORY_ACK}],
        },
    ]
