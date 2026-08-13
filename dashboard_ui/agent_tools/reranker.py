"""RAG agent 執行向量檢索後的 Rerank 重排序工作。

1. 對 vector_search 回傳的 candidate chunks 用 Cohere Rerank API 做 cross-encoder 精排，
   重新計算 query 與 document 的相關性分數。
2. 只保留 top_n 最相關的 chunks 給 RAG agent 的 LLM 使用。
3. 若 Cohere API 呼叫失敗，fallback 直接回傳原始的 vector search 結果，不做 rerank。

設計決策：
  - rerank 時用 rewritten_query 而非 expanded_query，
    因為 expanded_query 串接的 tag 關鍵字會干擾 cross-encoder 的語意判斷。
  - rerank score 取代原本的 vectorSearchScore，成為最終排序依據。

Required .env keys:
    COHERE_API_KEY   Cohere reranker API key.

參考：
  - Cohere Rerank 文件：https://docs.cohere.com/reference/rerank
  - Rerank 模型：rerank-v3.5，多語言、支援中英日文混合。
"""

import os

import cohere
from agent_tools.types_and_constants import Reranker
from loguru import logger

# ── 常數 ────────────────────────────────────────────────────────
COHERE_API_KEY = os.getenv("COHERE_API_KEY")


def _get_cohere_client() -> cohere.ClientV2:
    """以環境變數提供的 API key 建立 Cohere client。

    Returns:
        已完成認證的 cohere.ClientV2 物件。

    Raises:
        EnvironmentError: 環境變數 COHERE_API_KEY 未設定時拋出。
    """
    if not COHERE_API_KEY:
        raise EnvironmentError("找不到 COHERE_API_KEY，請確認已設定在 .env 或 Secret Manager 中。")
    return cohere.ClientV2(api_key=COHERE_API_KEY)


def rerank_chunks(
    query: str,
    chunks: list[dict],
    top_n: int = Reranker.TOP_N,  # rerank 後只保留幾筆
) -> list[dict]:
    """以 Cohere 的 cross-encoder 模型對向量檢索結果做精排，重新計算查詢與各 chunk 的相關度。

    送出前先把章節標題接在內容前組成待評分文件，讓模型也看得到章節脈絡。
    精排結果會濾掉相關度低於 0.1 的 chunk。候選只有一筆時直接跳過精排，相關度記為 1.0。
    呼叫 Cohere 失敗時退回原本的向量相似度排序，並把相似度分數同時填入相關度欄位，
    讓下游不必分辨這批結果有沒有經過精排。

    Note:
        呼叫方為 RAG agent。

    Args:
        query: 用來評分的查詢文字，可以是使用者原始問句，也可以是改寫後的獨立問句。
        chunks: 向量檢索回傳的候選 chunk 清單。
        top_n: 精排後最多保留幾筆，預設取自 Reranker.TOP_N。

    Returns:
        欄位與向量檢索結果相同的 chunk 清單，但依相關度由高到低重新排序、
        每筆多出 rerank_score 欄位、原本的向量相似度分數保留供對照，且筆數不超過 top_n。
    """
    if not chunks:
        return []

    # 只有一筆，不需要 rerank
    if len(chunks) <= 1:
        for c in chunks:
            c["rerank_score"] = 1.0
        return chunks

    # 組裝 documents：
    # Cohere rerank 需要 list[str]
    documents = []
    for c in chunks:
        section = c.get("section", "")
        content = c.get("content", "")
        doc_text = f"[{section}]\n{content}" if section else content
        documents.append(doc_text)

    try:
        client = _get_cohere_client()
        logger.debug(f"執行 rerank: query='{query[:50]}', \ndocs amount={len(documents)}....")

        response = client.rerank(
            model=Reranker.MODEL,
            query=query,
            documents=documents,
            top_n=min(top_n, len(documents)),
        )

        # 依 rerank score 重新排序 chunks
        reranked_chunks = []
        chunk = {}
        for result in response.results:
            if round(result.relevance_score, 4) < 0.1000:
                continue
            idx = result.index
            chunk = chunks[idx].copy()  # 不改動原始 dict
            chunk["rerank_score"] = round(result.relevance_score, 4)
            reranked_chunks.append(chunk)

        logger.debug(f"Cohere rerank 完成: \nTop 5 rerank_scores={[c['rerank_score'] for c in reranked_chunks]}")
        return reranked_chunks

    except Exception as e:
        logger.warning(f"Cohere rerank 失敗，fallback 用原始排序: {e}")
        # fallback：保留原始 vector search 排序，截斷到 top_n
        for c in chunks:
            c["rerank_score"] = c.get("score", 0.0000)
        return chunks[:top_n]
