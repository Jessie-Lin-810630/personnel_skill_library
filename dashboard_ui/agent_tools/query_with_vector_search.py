# tools/vector_search.py

"""
職責: 接收使用者輸入的 query 文字，
      呼叫 OpenAI text-embedding-3-small 將其向量化，
      再對 MongoDB Atlas obsidian_vectors 執行 $vectorSearch，
      回傳 top-K 筆相關 chunk。

依賴:
  - OpenAI SDK (與 ETL task06 相同，確保向量空間一致)
  - pymongo (MongoDB 連線)
"""

import os
from dotenv import load_dotenv
from openai import OpenAI
from loguru import logger
from ..utils.interact_with_mongodb import get_db_altas

# ── 資料庫連線函式與環境變數呼叫 ──────────────────────────────────────────────────────────
_get_db = get_db_altas
load_dotenv()
# ── 常數 ──────────────────────────────────────────────────────────
EMBEDDING_MODEL = "text-embedding-3-small"


def _get_openai_client() -> OpenAI:
    """ 
        初始化 OpenAI client。
        OpenAI() 不傳 api_key 參數時，SDK 會自動讀取環境變數 OPENAI_API_KEY。
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("找不到 OPENAI_API_KEY 環境變數，請確認已設定在 .env 或 Secret Manager 中。")
        raise EnvironmentError("找不到 OPENAI_API_KEY 環境變數，請確認已設定在 .env 或 Secret Manager 中。"
                               )
    return OpenAI(api_key=api_key)


def _embed_query(query: str, openai_client: OpenAI) -> list[float]:
    """
    將單一 query 字串向量化。
    使用與 ETL task06 相同的 embedding model，
    確保 query vector 與 obsidian_vectors 的 embedding 在同一向量空間。
    """
    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[query],          # 傳入 list，與 ETL task06 介面一致
        encoding_format="float",
    )
    return response.data[0].embedding  # list[float]，長度 1536


def vector_search(query: str,
                  top_k: int = 5,
                  filter_tags: str | None = None,
                  filter_note_type: str | None = None,
                  ) -> list[dict]:
    """
    對 MongoDB Atlas obsidian_vectors 執行語意搜尋。

    Args:
        query:            使用者輸入的自然語言問題或主題描述
        top_k:            回傳幾筆最相關的 chunk（Agent 1 預設 5，Agent 2 預設 10）
        filter_tags:      可選，限定搜尋範圍，例如 "MySQL"（對應 Atlas pre-filter: tags）
        filter_note_type: 可選，限定筆記類型，例如 "knowledge_summary"

    Returns:
        list[dict]，每筆包含:
            - file_name:  筆記檔名
            - file_path:  GCS 路徑
            - chunk_index: 筆記檔中的第幾個資料塊
            - section:    標題路徑，例如 "SQL > DQL > SELECT"
            - content:    chunk 純文字
            - tags:       筆記標籤列表
            - note_type:  筆記類型
            - score:      向量相似度分數 (0–1，cosine similarity，越高越相關)
    """
    openai_client = _get_openai_client()
    db = _get_db()
    collection = db["obsidian_vectors"]

    # Step 1: 將 query 向量化
    logger.info(f"向量化 query: '{query[:50]}...' " if len(query) > 50 else f"向量化 query: '{query}'")
    query_vector = _embed_query(query, openai_client)

    # Step 2: 組裝 $vectorSearch pipeline
    # numCandidates 依 Atlas 官方建議設為 top_k 的 10 倍（最大 10000）
    num_candidates = min(top_k * 10, 10_000)

    vector_search_stage = {"$vectorSearch": {"index":         "obsidian_vectors_index",
                                             "path":          "embedding",
                                             "queryVector":   query_vector,
                                             "numCandidates": num_candidates,
                                             "limit":         top_k,
                                             }
                           }

    # 若有 pre-filter 條件，加入 filter 欄位（Atlas Vector Search 支援的 pre-filter）
    # 對應 task06 建立 index 時定義的 filter: tags、filter: note_type
    vector_search_filter = {}
    if filter_tags:
        vector_search_filter["tags"] = filter_tags
    if filter_note_type:
        vector_search_filter["note_type"] = filter_note_type
    if vector_search_filter:
        vector_search_stage["$vectorSearch"]["filter"] = vector_search_filter

    # Step 3: $project，只取需要的欄位，embedding 不回傳（省傳輸量）
    project_stage = {"$project": {"_id":       0,
                                  "file_name": 1,
                                  "file_path": 1,
                                  "chunk_index": 1,
                                  "section":   1,
                                  "content":   1,
                                  "tags":      1,
                                  "note_type": 1,
                                  "score":     {"$meta": "vectorSearchScore"},  # 相似度分數，範圍 0–1，越高越相似
                                  }
                     }

    pipeline = [vector_search_stage, project_stage]

    # Step 4: 執行查詢
    logger.info(f"執行 $vectorSearch，top_k={top_k}, filter={vector_search_filter or 'none'}")
    results = list(collection.aggregate(pipeline))
    logger.info(f"$vectorSearch 回傳 {len(results)} 筆 chunk")

    return results


if __name__ == "__main__":

    query = "找尋PLC相關知識"
    result = vector_search(query)
    # result = vector_search(query, filter_tags="OPC-UA")
    # result = vector_search(query, filter_tags="opc-ua")  # 會找不到
    print(result)
