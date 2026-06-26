"""作為 RAG agent 執行向量檢索後的重排序工作: Rerank。

職責：
  對 vector_search 回傳的 candidate chunks 做 cross-encoder 精排，
  用 Cohere Rerank API 重新計算 query-document 的相關性分數，
  只保留 top_n 最相關的 chunks 給 RAG Agent LLM 使用。

設計決策：
  - rerank 時用 rewritten_query (不是 expanded_query)，
    因為 expanded_query 裡串接的 tag 關鍵字會干擾 cross-encoder 的語意判斷。
  - rerank score 取代原本的 vectorSearchScore，成為最終排序依據。
  - 如果 Cohere API 呼叫失敗，fallback 回傳原始的 vector search 結果 (不做 rerank)。

依賴：
  - cohere SDK (pip install cohere)
  - 環境變數 COHERE_API_KEY

參考：
  - Cohere Rerank docs: https://docs.cohere.com/reference/rerank
  - Rerank model: rerank-v3.5 (多語言、支援中英日文混合)
"""

import os

import cohere
from loguru import logger

# ── 常數 ────────────────────────────────────────────────────────
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
RERANK_MODEL = "rerank-v3.5"


def _get_cohere_client() -> cohere.ClientV2:
    """建立 Cohere ClientV2 (讀取環境變數 COHERE_API_KEY)。

    Returns:
        已認證的 cohere.ClientV2 物件。

    Raises:
        EnvironmentError: 缺少 COHERE_API_KEY 時拋出。
    """
    if not COHERE_API_KEY:
        raise EnvironmentError("找不到 COHERE_API_KEY，請確認已設定在 .env 或 Secret Manager 中。")
    return cohere.ClientV2(api_key=COHERE_API_KEY)


def rerank_chunks(
    query: str,
    chunks: list[dict],
    top_n: int = 5,  # rerank 後只保留幾筆
) -> list[dict]:
    """用 Cohere Rerank 對 vector_search 回傳的 chunks 做 cross-encoder 精排。

    **Note:**
        使用的 agent: RAG agent

    Args:
        query:   用來做 rerank 的查詢文字，可以是原始 query 或是 rewritten_query
        chunks:  vector_search() 回傳的 list[dict]
        top_n:   rerank 後保留幾筆，預設 5 筆

    Returns:
        list[dict]，格式同 vector_search() 回傳值，但：
        - 重新排序（依 rerank score 由高到低）
        - 每筆多一個 "rerank_score" 欄位
        - 原本的 "score" (vectorSearchScore) 保留做參考
        - 只保留 top_n 筆

    **Example of returns:**
        [{
        file_name:  "20260507 MySQL Query.md"
         file_path:  "...01-daily-logs/20260507 MySQL Query.md"
         chunk_index: 2
         section:    "SQL > DQL > SELECT"
         content:    "SELECT * FROM ... means ...."
         tags:       [DDL, MySQL, SQL]
         note_type:  daily_logs
         score:      0.5  向量相似度分數
         rerank_score: 0.9  語意相關度分數
        }, {}]
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
            model=RERANK_MODEL,
            query=query,
            documents=documents,
            top_n=min(top_n, len(documents)),
        )

        # 依 rerank score 重新排序 chunks
        reranked_chunks = []
        for result in response.results:
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
