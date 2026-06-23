"""
職責:
  rag_query(): 筆記語意查詢，回答使用者問題並附上來源清單

依賴:
  - google-genai SDK (Vertex AI)
"""

from google.oauth2.service_account import Credentials
import os
from google import genai
from google.genai import types
from loguru import logger

from agent_tools.connect_to_google_genai import _get_genai_client
from agent_tools.query_with_vector_search import vector_search
from agent_tools.chat_history import load_chat_history, save_chat_history


# ── 常數 ──────────────────────────────────────────────────────────
RAG_AGENT1_MODEL = "gemini-2.5-flash-lite"

SYSTEM_PROMPT = """你是一位筆記查詢助理。
你只根據以下提供的筆記片段來回答問題，不使用筆記片段以外的知識。
若筆記片段中找不到足夠資訊，請提供使用者你找到的片段資訊，跟
對方確認你找到的關鍵字中是否有切中使用者真正想詢問的。
如果完全沒有足夠資訊，請明確告知使用者「目前的筆記裡沒有相關內容」，不要自行推測或捏造答案。
回答時請使用繁體中文，語氣簡潔清楚。"""


def _build_context(chunks: list[dict]) -> str:
    """
    將 vector_search() 回傳的 top-K chunks 組裝成純文字 context block，
    每個 chunk 標注來源，讓模型知道每段文字出自哪份筆記。

    格式範例:
        [來源 1] 檔案: SQL筆記.md｜章節: SQL > DQL > SELECT
        SELECT 用來從資料表中選取欄位...

        [來源 2] 檔案: MongoDB筆記.md｜章節: MongoDB > Aggregation
        $match 用來過濾文件...
    """
    blocks = []
    for i, chunk in enumerate(chunks, start=1):
        header = f"[來源 {i}] 檔案: {chunk['file_name']}｜章節: {chunk['section']}"
        blocks.append(f"{header}\n{chunk['content']}")
    return "\n\n".join(blocks)


def _build_source_list(chunks: list[dict]) -> list[dict]:
    """
    組裝準備回傳給呼叫方 (Streamlit UI) 的來源清單，
    包含去重後的 "file_name + section 組合"。

    Returns:
        {
         "file_name":  "某份筆記檔案名稱.md",  
         "section":  "一個筆記資料塊所屬的文章標題",  
         "score":  "與查詢語意的相似度評分，小數點後四位"
         }
    """
    seen = set()
    sources = []
    for chunk in chunks:
        key = (chunk["file_name"], chunk["section"])
        if key not in seen:
            seen.add(key)
            sources.append({"file_name": chunk["file_name"],
                            "section":   chunk["section"],
                            "score":     round(chunk["score"], 4),
                            })
    return sources


def rag_query(query: str,
              session_id: str,
              filter_tags: list[str] | None = None,
              filter_file_path: str | None = None,
              filter_note_type: str | None = None,
              search_query: str | None = None,
              search_optimize_method: str | None = None,
              chat_history_n: int = 3,
              rag_top_k: int = 5,
              ) -> dict:
    """
    筆記語意查詢主函式。

    Args:
        query:            使用者的問題或查詢文字
        session_id:       目前對話的 uuid4（用於讀寫 chat_history）
        filter_tags:      可選，限定搜尋範圍的 tag，例如 ["MySQL"]
        filter_note_type: 可選，限定筆記類型，例如 "knowledge_summary"
        search_query:     從 query 修飾過來、真正拿來做向量化查詢的問題，修飾程度由 route() 函式回傳而定。
        search_optimize_method: router agent 預先使用什麼策略增加查詢精準度，例如：筆記關鍵字(structure search)或是重寫使用者查詢語句(rewrite)，由 route() 函式回傳值而定。
        chat_history_n:   RAG agent 要回讀前面多少輪的對話作為回應參考
        rag_top_k:        TOP K
    Returns:
        {
            "answer":  "模型生成的回答文字",
            "sources": [
                {"file_name": "xxx.md", "section": "...", "score": 0.91},
                ...
            ]
        }
    """
    client = _get_genai_client()

    # ── Step 1: 儲存使用者訊息 ─────────────────────────────────
    save_chat_history(session_id=session_id,
                      agent_type="rag",
                      role="user",
                      message_text=query,
                      )

    # ── Step 2: 向量搜尋，取得相關 chunks ──────────────────────
    logger.info(f"rag_query: 執行 vector_search, search_query='{search_query[:40]}…'")
    chunks = vector_search(query=search_query,  # 注意不是用 query
                           top_k=rag_top_k,
                           filter_tags=filter_tags,
                           filter_file_path=filter_file_path,
                           filter_note_type=filter_note_type,
                           )
    if not chunks:
        answer = "目前的筆記裡沒有找到與這個問題相關的內容，請換個關鍵字試試。"
        save_chat_history(session_id=session_id,
                          agent_type="rag",
                          role="model",
                          message_text=answer,
                          metadata={
                              "search_optimize_method": search_optimize_method,
                          },
                          )
        return {"answer": answer, "sources": []}

    # ── Step 3: 將chunks 組裝回 context ───────────────────────────────────
    context_from_chks = _build_context(chunks)

    # ── Step 4: 讀取對話歷史（最近 3 輪，包含 user 與 model 講的話，所以有 6 筆）─────────────────────
    history_user_model_msg = load_chat_history(session_id=session_id,
                                               agent_type="rag",
                                               n=chat_history_n,
                                               )

    # ── Step 5: 組裝本輪 user message，包含 history + context，包成 contents 餵給 LLM 摘要。
    # 為了避免每輪 prompt 膨脹過頭，也確保每輪都用最新的 vector search 結果，contents 不存入 chat_history
    current_user_msg = {"role": "user",   # 因為是餵給 LLM，所以 role 為 user
                        "parts": [{"text": f"以下是相關筆記片段：\n\n{context_from_chks}\n\n---\n\n問題：{query}"}],
                        }
    contents = history_user_model_msg + [current_user_msg]
    # ── Step 6: 呼叫 Vertex AI (Gemini Enterprise Agent Platform)，等待其回應 ────────────────────────────
    logger.info(f"呼叫模型 {RAG_AGENT1_MODEL}，挾帶 {len(history_user_model_msg)} recent history messages.")
    response = client.models.generate_content(model=RAG_AGENT1_MODEL,
                                              contents=contents,
                                              config=types.GenerateContentConfig(
                                                  system_instruction=SYSTEM_PROMPT,
                                                  temperature=0.2,   # 查詢任務必須穩定，選低 temperature
                                              ),
                                              )
    answer = response.text

    # ── Step 7: 儲存模型回應 ───────────────────────────────────
    source_list = _build_source_list(chunks)  # 順便整理這次查到的來源筆記檔有幾個

    save_chat_history(session_id=session_id,
                      agent_type="rag",
                      role="model",
                      message_text=answer,
                      metadata={
                          "model": RAG_AGENT1_MODEL,
                          "retrieved_chunks": [
                              {
                                  "file_path":   c.get("file_path", ""),
                                  "chunk_index": c.get("chunk_index"),
                                  "score": c.get("score", 0),
                              } for c in chunks
                          ],
                          "note_files": list(set(c["file_name"] for c in chunks)),
                          "search_optimize_method": search_optimize_method,
                      },
                      )

    logger.info(f"rag_query: 回應生成完成，來源 {len(source_list)} 筆")
    return {"answer": answer, "sources": source_list}
