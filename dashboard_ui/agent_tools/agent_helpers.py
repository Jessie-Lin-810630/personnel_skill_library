"""agents 共用的格式化輔助函式，負責 context 組裝、來源清單與歷史脈絡，供 rag_agent 與 planning_agent 使用。

1. 函式 build_context 把 vector_search 回傳的 chunks 組成一段純文字 context block。
2. 函式 build_source_list 把 chunks 去重成回傳給 UI 的來源清單。
3. 函式 build_history_context_message 把某個 agent 的歷史對話包成獨立的 user 與 model 對組。
"""

from agent_tools.chat_history import load_chat_history

# 帶歷史脈絡時，model 端統一的確認回應，避免 LLM 把歷史誤判為自己當下要接續輸出的內容。
_HISTORY_ACK = "好的，我已了解先前的討論脈絡，請告訴我這一輪的需求。"


def build_context(chunks: list[dict]) -> str:
    """把檢索到的 chunk 組裝成一段純文字脈絡，交給 LLM 生成回答時使用。

    每個 chunk 前面標注來源檔名與章節，讓模型知道每段文字出自哪份筆記。
    chunk 若帶有重排分數，代表已經過 reranker 精排，此時一併標注相關度。

    Note:
        呼叫方為 RAG agent 與 Planning agent。

    Example:
        [來源 1] 檔案: SQL筆記.md | 章節: SQL > DQL > SELECT | 相關度: 0.9
        SELECT 用來從資料表中選取欄位...

        [來源 2] 檔案: MongoDB筆記.md | 章節: MongoDB > Aggregation
        $match 用來過濾文件...

    Args:
        chunks: 向量檢索或重排後回傳的 chunk 清單，每筆至少需含 file_name 與 content，
            section 與 rerank_score 為選填。

    Returns:
        以連續兩個換行分隔各來源區塊的純文字脈絡字串。
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
    """把檢索到的 chunk 整理成回傳給 Streamlit 畫面顯示的來源清單。

    以檔名與章節兩欄的組合做去重，同一份筆記的同一個章節只列一次，並保留首次出現時的分數。

    Note:
        呼叫方為 RAG agent 與 Planning agent。Planning agent 的 chunk 未經 reranker，
        其重排分數一律為 0。

    Args:
        chunks: 向量檢索或重排後回傳的 chunk 清單。

    Returns:
        每筆含四個欄位的 dict 清單：file_name 為筆記檔名，section 為該 chunk 所屬的章節標題，
        vector_score 為提問與該 chunk 在向量空間上的相似度，rerank_score 為兩者的語意相關度，
        兩個分數都取到小數點後四位。
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
    """讀取本次 session 中某個 agent 的對話歷史，包裝成可直接帶入模型的背景訊息。

    歷史內容不直接還原成多輪對話，而是包成一組獨立的 user 與 model 對組：
    user 那筆放引言與歷史全文，model 那筆放固定的確認回應。
    這樣做是為了避免 LLM 把過去的回應誤判為自己當下要接續輸出的內容。

    Note:
        呼叫方為 Planning agent。

    Args:
        session_id: 目前對話的 uuid4。
        agent_type: 要讀取哪一個 agent 的歷史，可為 rag 或 planning。
        intro: 引言文字，說明這段背景的用途，不含歷史內容本身。
        chat_history_n: 回讀幾輪歷史，預設 5 輪。

    Returns:
        兩筆訊息組成的 list，第一筆為引言加歷史的 user 訊息，第二筆為 model 的確認回應；
        該 agent 尚無歷史時回傳空 list。
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
