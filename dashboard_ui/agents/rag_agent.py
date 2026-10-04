"""筆記語意查詢 RAG agent，流程為 rewrite → vector_search → rerank → LLM 生成。

1. 以 query_rewriter 把使用者問句改寫成 rewritten_query 與含 tag 的 expanded_query。
2. 以 expanded_query 對向量庫做 vector_search 粗篩，取 top_k 個 chunk。
3. 以 rewritten_query 對粗篩結果做 Cohere rerank，取 top_n 個 chunk。
4. 把精排後的 chunks 組成 context 交給 LLM 生成回答。

設計決策：
  - vector_search 不加 prefilter，改用含 tag 關鍵字的 expanded_query 做軟性語意增強。
  - rerank 用不含 tag 關鍵字的 rewritten_query，避免 tag 干擾 cross-encoder 判斷。
  - chat_history 只存使用者原始 query，不存 rewritten 或 expanded 版本。
  - metadata 記錄 search_optimize_method、rewritten_query、recommended_tags，方便 debug。
"""

from agent_tools.agent_helpers import build_context, build_source_list
from agent_tools.chat_history import load_chat_history, save_chat_history
from agent_tools.connect_to_google_genai import get_genai_client
from agent_tools.query_rewriter import rewrite_query
from agent_tools.query_with_vector_search import vector_search
from agent_tools.reranker import rerank_chunks
from agent_tools.types_and_constants import RagAgent, Reranker
from google.genai import types
from loguru import logger

SYSTEM_PROMPT = (
    "你是一位筆記查詢助理。\n"
    "你只根據以下提供的筆記片段來回答問題，不使用筆記片段以外的知識，不可自行捏造。\n"
    "- 回答時請使用繁體中文，語氣簡潔清楚，回答開頭直接描述找到的知識，稱呼使用者為**您**。"
    "不用「根據你提供的筆記、根據資料庫」等這種客套用語作為開頭。\n"
    "- 回答中不要列出「來源」清單，也不要標註檔案名稱或章節；系統會在回答下方另外顯示來源筆記。\n"
    "- 若筆記片段中有資訊但不足，請明確告知使用者「目前的筆記裡直接關聯的內容」，不要自行推測或捏造答案，\n"
    "- 然後提供使用者你找到的片段資訊，詢問「片段資訊中是否有切中您真正想詢問的部分」。\n"
    "- 如果完全沒有收到筆記片段，請直接回覆「沒有找到相關內容，請換方式查詢」。"
)


# ── 主函式 ────────────────────────────────────────────────────────
def rag_query(
    query: str,
    session_id: str,
    alias_tag_pairs: list[dict],
    known_tags: set[str],
) -> dict:
    """筆記語意查詢的主流程，依序執行問句改寫、向量檢索、重排與回答生成。

    改寫器產出兩種問句，各有分工：擴展問句帶有標籤關鍵字，用於向量檢索粗篩以提高召回；
    改寫後的獨立問句不帶標籤，用於重排，避免關鍵字干擾 cross-encoder 對語意的判斷。
    向量檢索刻意不加前置篩選，改以擴展問句做軟性的語意增強。
    對話紀錄只存使用者的原始提問，不存改寫或擴展後的版本；
    改寫結果與推薦標籤則寫進模型回應的 metadata，供事後追查檢索品質。
    檢索不到任何 chunk 時不呼叫模型，直接回覆請使用者換個關鍵字。

    Args:
        query: 使用者的原始提問文字。
        session_id: 目前對話的 uuid4，用於讀寫對話紀錄。
        alias_tag_pairs: 筆記別名與標籤的對照清單，供改寫器推薦標籤時參考。
        known_tags: 向量庫裡實際存在的標籤集合，用來校驗模型推薦的標籤。

    Returns:
        含 answer、sources、debug 三個鍵的 dict。answer 為模型生成的回答文字，
        sources 為去重後的來源筆記清單，debug 收錄流程各步驟的中間結果，
        涵蓋原始問句、改寫後問句、擴展問句、推薦標籤、粗篩與重排後的筆數，以及各筆的重排分數；
        檢索不到 chunk 時 sources 為空 list、debug 為空 dict。
    """
    client = get_genai_client()

    # ── Step 1: 儲存使用者訊息 ─────────────────────────────────
    save_chat_history(
        session_id=session_id,
        agent_type="rag",
        role="user",
        message_text=query,
    )

    # ── Step 2: 讀取對話歷史 ──────────────────────────────────
    history_user_model_msg = load_chat_history(
        session_id=session_id, agent_type="rag", n=RagAgent.CHAT_HISTORY_N
    )  # 最近 3 輪 (user + model 各一筆 = 6 筆)

    # ── Step 3: Query Rewrite ─────────────────────────────────
    #   - rewritten_query: 獨立問句（給 reranker）
    #   - expanded_query:  rewritten + tag 關鍵字（給 vector_search）
    logger.info(f"調用 query rewritter, \nquery='{query[:40]}...'")
    rewrite_result = rewrite_query(
        query=query,
        alias_tag_pairs=alias_tag_pairs,
        chat_history_msgs=history_user_model_msg,
        known_tags=known_tags,
        client=client,
    )
    rewritten_query = rewrite_result["rewritten_query"]
    expanded_query = rewrite_result["expanded_query"]
    recommended_tags = rewrite_result["recommended_tags"]

    logger.success(
        f"query rewritting 完成: \nrewritten='{rewritten_query[:50]}…', "
        f"\nexpanded_query='{expanded_query[:60]}..., "
        f"\nrecommended_tags={recommended_tags}"
    )

    # ── Step 4: 向量搜尋，取得相關 chunks ─────────────────────────────────
    logger.info(f"執行 vector_search, top_k={RagAgent.TOP_K}...")
    chunks = vector_search(
        query=expanded_query,
        top_k=RagAgent.TOP_K,
        filter_tags=None,  # 關鍵：已不做 prefilter
        filter_file_path=None,
    )
    logger.success(f"vector_search 完成: chunk_amount={len(chunks)}")

    if not chunks:
        answer = "目前的筆記裡沒有找到與這個問題相關的內容，請換個關鍵字試試。"
        save_chat_history(
            session_id=session_id,
            agent_type="rag",
            role="model",
            message_text=answer,
        )
        return {"answer": answer, "sources": [], "debug": {}}

    # ── Step 5: Rerank Chunks ─────────────────────────────────
    # reranker 需要看的是「使用者真正想問什麼」跟「這個 chunk 有多相關」，
    # tag 關鍵字反而會干擾 cross-encoder 的判斷，故用 rewritten_query 而不是 expanded
    logger.info(f"調用 Cohere reranker, {len(chunks)} candidates → top_n={Reranker.TOP_N}")
    reranked_chunks = rerank_chunks(
        query=rewritten_query,
        chunks=chunks,
        top_n=Reranker.TOP_N,
    )
    logger.success(f"Cohere rerank 完成: chunk_amount={len(reranked_chunks)}")

    # ── Step 6: 將 chunks 組裝回 context ───────────────────────────────────
    context_from_chks = build_context(reranked_chunks)

    # ── Step 7: 組裝要給 LLM 的 content，包含 history + context_from_chunks
    # 隨著多輪對話增長的 history，若存入 chat_history 可能讓下一輪 prompt 膨脹過頭，
    # 故 contents 不存入 chat_history
    current_user_msg = {
        "role": "user",  # 因為是餵給 LLM，所以 role 為 user
        "parts": [{"text": f"以下是相關筆記片段：\n\n{context_from_chks}\n\n---\n\n問題：{query}"}],
    }
    contents = history_user_model_msg + [current_user_msg]

    # ── Step 8: 呼叫 LLM，等待其回應 ────────────────────────────
    logger.info(
        f"呼叫模型 {RagAgent.MODEL}, 挾帶 {len(history_user_model_msg)} 歷史對話紀錄 {len(reranked_chunks)} 筆文件"
    )
    response = client.models.generate_content(
        model=RagAgent.MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
        ),
    )
    answer = response.text

    # ── Step 9: 儲存模型回應 ───────────────────────────────────
    source_list = build_source_list(reranked_chunks)

    save_chat_history(
        session_id=session_id,
        agent_type="rag",
        role="model",
        message_text=answer,
        metadata={
            "model": RagAgent.MODEL,
            "retrieved_chunks": [
                {
                    "file_path": c.get("md_path", ""),
                    "chunk_index": c.get("chunk_index"),
                    "score": round(c.get("score", 0), 4),
                    "rerank_score": round(c.get("rerank_score", 0), 4),
                }
                for c in reranked_chunks
            ],
            "note_files": list({c["file_name"] for c in reranked_chunks}),
            "search_optimize_method": "rewrite_expand_rerank",
            "rewritten_query": rewritten_query,
            "recommended_tags": recommended_tags,
        },
    )

    logger.success(f"RAG Agent 回應生成完成，來源 {len(source_list)} 筆")
    return {
        "answer": answer,
        "sources": source_list,
        "debug": {
            "original_query": query,
            "rewritten_query": rewritten_query,
            "expanded_query": expanded_query,
            "recommended_tags": recommended_tags,
            "vector_search_count": len(chunks),
            "reranked_count": len(reranked_chunks),
            "rerank_scores": [c.get("rerank_score") for c in reranked_chunks],
        },
    }
