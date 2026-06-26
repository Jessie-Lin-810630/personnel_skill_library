"""query 向量化並對 Atlas 執行 $vectorSearch，回傳 top-K 相關 chunk。

職責: 接收使用者輸入的 query 文字，
      呼叫 Vertex AI gemini-embedding-2 將其向量化（與 ETL task06 同一向量空間），
      再對 MongoDB Atlas obsidian_vectors_multimodal 執行 $vectorSearch，
      回傳 top-K 筆相關 chunk。

依賴:
  - google-genai SDK（Vertex AI，與 ETL task06 相同 embedding model，確保向量空間一致）
  - pymongo (MongoDB 連線)

注意:
  embedding model 與入庫側（task06_obsidian_embed_etl/t_chunk_embed.py）必須 1:1 對齊：
    - model = "gemini-embedding-2"
    - output_dimensionality = 1536（MRL 截斷，非預設 3072，故需自行 L2 normalize）
    - 不支援 task_type 參數，任務型式寫進 prompt：
        文件側（入庫）→ "title: {title} | text: {content}"
        查詢側（本檔）→ "task: search result | query: {query}"
    - embedding model 僅在 location="us" 提供。
"""

import math
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.oauth2.service_account import Credentials
from loguru import logger
from utils.interact_with_mongodb import get_db_atlas

# ── 資料庫連線函式與環境變數呼叫 ──────────────────────────────────────────────────────────
_get_db = get_db_atlas
load_dotenv()

# ── 常數 ──────────────────────────────────────────────────────────
EMBEDDING_MODEL = "gemini-embedding-2"
EMBED_DIM = 1536
QUERY_PROMPT_TEMPLATE = "task: search result | query: {query}"  # 查詢側任務格式，與入庫側 document 格式配對

VECTOR_COLLECTION = "obsidian_vectors_multimodal"
VECTOR_INDEX = "obsidian_vectors_index2"


def _get_embed_client() -> genai.Client:
    """初始化指向 Vertex AI 的 google-genai client (限定給 location=us 供 embedding 模型用)。

    與 connect_to_google_genai._get_genai_client 分開，因為該函式只調用在 us-central1 的模型。

    Returns:
        指向 Vertex AI (location=us) 的 google-genai Client 物件。

    Raises:
        EnvironmentError: 缺少 GCP_PROJECT_ID 或 AGENT_PLATFORM_USER_CREDENTIALS 時拋出。
    """
    json_path = os.getenv("AGENT_PLATFORM_USER_CREDENTIALS")
    project = os.getenv("GCP_PROJECT_ID")
    embed_location = "us"
    if not json_path or not project:
        raise EnvironmentError(
            "找不到 GCP_PROJECT_ID / AGENT_PLATFORM_USER_CREDENTIALS ，請確認已設定在 .env 或 secret managers 中。"
        )
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    credentials = Credentials.from_service_account_file(json_path, scopes=scopes)
    return genai.Client(vertexai=True, project=project, location=embed_location, credentials=credentials)


def _normalize(vec: list[float]) -> list[float]:
    """L2 normalize 成單位向量。

    gemini-embedding 只有預設維度 3072 會自動正規化；MRL 截斷到 1536 時不會，
    cosine 相似度前需自行正規化，否則分數失真。零向量原樣回傳。

    Args:
        vec: 待正規化的向量 (embedding 原始輸出)。

    Returns:
        L2 正規化後的單位向量；若為零向量則原樣回傳。
    """
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def _embed_query(query: str, embed_client: genai.Client) -> list[float]:
    """將單一 query 字串向量化。

    使用與 ETL task06 相同的 embedding model 與查詢側任務格式，
    確保 query vector 與 obsidian_vectors_multimodal 的 embedding 在同一向量空間。

    Args:
        query:        使用者輸入的自然語言查詢字串。
        embed_client: _get_embed_client() 建立的 google-genai Client。

    Returns:
        長度 1536、已 L2 normalize 的 query embedding (list[float])。
    """
    prompt_text = QUERY_PROMPT_TEMPLATE.format(query=query)
    response = embed_client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=[types.Content(parts=[types.Part.from_text(text=prompt_text)])],
        config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
    )
    return _normalize(response.embeddings[0].values)  # list[float]，長度 1536，已 L2 normalize


def vector_search(
    query: str,
    top_k: int = 5,
    filter_tags: list[str] | None = None,
    filter_file_path: str | None = None,
    filter_note_type: str | None = None,
) -> list[dict]:
    """對 MongoDB Atlas obsidian_vectors_multimodal 執行語意搜尋。

    Args:
        query:            使用者輸入的自然語言問題或主題描述
        top_k:            回傳幾筆最相關的 chunk (Agent 1 預設 5，Agent 2 預設 10)
        filter_tags:      可選，限定搜尋範圍，例如 ["MySQL"] (對應 Atlas pre-filter: tags)
        filter_file_path: 可選，限定筆記路徑，例如 "MySQL Window Function.md"
        filter_note_type: 可選，限定筆記種類，例如 "Knowledge_summary"

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
    embed_client = _get_embed_client()
    db = _get_db()
    collection = db[VECTOR_COLLECTION]

    # Step 1: 將 query 向量化
    logger.debug(f"向量化 query: '{query[:50]}...' " if len(query) > 50 else f"向量化 query: '{query}'")
    query_vector = _embed_query(query, embed_client)

    # Step 2: 組裝 $vectorSearch pipeline
    # numCandidates 依 Atlas 官方建議設為 top_k 的 10 倍（最大 10000）
    num_candidates = min(top_k * 10, 10_000)

    vector_search_stage = {
        "$vectorSearch": {
            "index": VECTOR_INDEX,
            "path": "embedding",
            "queryVector": query_vector,
            "numCandidates": num_candidates,
            "limit": top_k,
        }
    }

    # 若有 pre-filter 條件，加入 filter 欄位（Atlas Vector Search 支援的 pre-filter）
    # 對應 task06 建立 index 時定義的 filter: tags、filter: note_type
    vector_search_filter = {}
    if filter_file_path:
        vector_search_filter["file_path"] = {"$in": filter_file_path}
    elif filter_tags:
        vector_search_filter["tags"] = {"$in": filter_tags}

    if filter_note_type:
        vector_search_filter["note_type"] = filter_note_type

    if vector_search_filter:
        vector_search_stage["$vectorSearch"]["filter"] = vector_search_filter

    # Step 3: $project，只取需要的欄位，embedding 不回傳（省傳輸量）
    project_stage = {
        "$project": {
            "_id": 0,
            "file_name": 1,
            "file_path": 1,
            "chunk_index": 1,
            "section": 1,
            "content": 1,
            "tags": 1,
            "note_type": 1,
            "score": {"$meta": "vectorSearchScore"},  # 相似度分數，範圍 0–1，越高越相似
        }
    }

    pipeline = [vector_search_stage, project_stage]

    # Step 4: 執行查詢
    results = list(collection.aggregate(pipeline))
    logger.debug(
        f"執行 $vectorSearch，top_k={top_k}, filter={vector_search_filter or 'none'}"
        f"$vectorSearch 回傳 {len(results)} 筆 chunk"
    )

    return results
