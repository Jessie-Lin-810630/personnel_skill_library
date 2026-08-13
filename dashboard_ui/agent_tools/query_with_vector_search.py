"""query 向量化並對 Atlas 執行 $vectorSearch，回傳 top-K 相關 chunk。

職責: 接收使用者輸入的 query 文字，
      呼叫 Agent Platform gemini-embedding-2 將其向量化（與 ETL task06 同一向量空間），
      再對 MongoDB Atlas note_vectors_multimodal 執行 $vectorSearch，
      回傳 top-K 筆相關 chunk。

依賴:
  - google-genai SDK（Agent Platform，與 ETL task06 相同 embedding model，確保向量空間一致）
  - pymongo (MongoDB 連線)

Required .env keys:
    GCP_PROJECT_ID                    Agent Platform project id.
    AGENT_PLATFORM_USER_CREDENTIALS   (On-premise only) Agent Platform service account JSON path.

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

from agent_tools.types_and_constants import EmbeddingModel, NoteCollections
from dotenv import load_dotenv
from google import genai
from google.genai import types
from loguru import logger
from utils.interact_with_mongodb import get_db_atlas

# ── 資料庫連線函式與環境變數呼叫 ──────────────────────────────────────────────────────────
_get_db = get_db_atlas
load_dotenv()

# ── 常數（共用 config 見 agent_tools/types_and_constants.py）──────────────────────────
QUERY_PROMPT_TEMPLATE = "task: search result | query: {query}"  # 查詢側任務格式，與入庫側 document 格式配對
VECTOR_COLLECTION = NoteCollections.VECTOR


def _get_embed_client() -> genai.Client:
    """初始化指向 Agent Platform 的 google-genai client，供 embedding 模型呼叫。

    這個 client 綁定 us，與 connect_to_google_genai 內建立 chat client 的函式分開，
    因為 chat 模型部署在 us-central1，兩者所在 region 不同。
    雲端執行時憑證由 Cloud Run 的 runtime service account 以應用程式預設憑證供給，
    地端則需解除函式內的註解區塊，改以 service account 金鑰檔初始化。

    Returns:
        綁定 us 的 google-genai Client 物件。

    Raises:
        EnvironmentError: 環境變數 GCP_PROJECT_ID 未設定時拋出。
    """
    # # 地端測試跑下面區塊：
    # # 先驗環境變數再建 Credentials，否則 json_path 為 None 會讓 Credentials 先拋 TypeError/FileNotFoundError
    # from google.oauth2.service_account import Credentials
    # json_path = os.getenv("AGENT_PLATFORM_USER_CREDENTIALS")
    # project = os.getenv("GCP_PROJECT_ID")
    # if not json_path or not project:
    #     raise EnvironmentError(
    #         "找不到 GCP_PROJECT_ID / AGENT_PLATFORM_USER_CREDENTIALS，請確認已設定在 .env 或 secret manager。"
    #     )
    # scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    # credentials = Credentials.from_service_account_file(json_path, scopes=scopes)
    # return genai.Client(vertexai=True, project=project, location="us", credentials=credentials)

    # Cloud run 跑下面區塊：
    project = os.getenv("GCP_PROJECT_ID")
    if not project:
        raise EnvironmentError("找不到 GCP_PROJECT_ID，請確認已設定在 secret manager。")
    return genai.Client(vertexai=True, project=project, location="us")


def _normalize(vec: list[float]) -> list[float]:
    """對向量做 L2 normalize，轉成長度為 1 的單位向量。

    gemini-embedding 只有在使用預設的 3072 維時才會自動正規化，
    以 MRL 截斷到 1536 維時不會，因此計算 cosine 相似度前必須自行正規化，否則分數失真。

    Args:
        vec: embedding 模型輸出的原始向量。

    Returns:
        L2 正規化後的單位向量；傳入零向量時原樣回傳，避免除以零。
    """
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def _embed_query(query: str, embed_client: genai.Client) -> list[float]:
    """把單一查詢字串轉成向量。

    模型與維度都與 task06、task08 寫入向量時採用的設定相同，套用的則是查詢用的任務格式，
    確保產出的向量與 note_vectors_multimodal 內既有的向量落在同一個向量空間。

    Note:
        任務格式必須與寫入時採用的那一組配對，改動其中一邊就要同步改另一邊，
        否則查詢與內容會落在不同的語意位置，相似度分數失去意義。

    Args:
        query: 使用者輸入的自然語言查詢字串。
        embed_client: 由 _get_embed_client 建立的 google-genai Client 物件。

    Returns:
        長度 1536 且已完成 L2 正規化的查詢向量。
    """
    prompt_text = QUERY_PROMPT_TEMPLATE.format(query=query)
    response = embed_client.models.embed_content(
        model=EmbeddingModel.MODEL,
        contents=[types.Content(parts=[types.Part.from_text(text=prompt_text)])],
        config=types.EmbedContentConfig(output_dimensionality=EmbeddingModel.DIM),
    )
    return _normalize(response.embeddings[0].values)  # list[float]，長度 1536，已 L2 normalize


def vector_search(
    query: str,
    top_k: int = 5,
    filter_tags: list[str] | None = None,
    filter_file_path: str | None = None,
    filter_note_type: str | None = None,
) -> list[dict]:
    """對 MongoDB Atlas 的 note_vectors_multimodal 執行語意搜尋，取回最相關的 chunk。

    先把查詢字串向量化，再送進 $vectorSearch 比對。候選數依 Atlas 官方建議設為回傳筆數的十倍，
    上限為一萬筆。三個篩選條件都會轉成 Atlas 的前置篩選，其中限定筆記路徑與限定標籤兩者擇一生效，
    前者優先。

    Args:
        query: 使用者輸入的自然語言問題或主題描述。
        top_k: 回傳幾筆最相關的 chunk，預設 5 筆。各 agent 的建議值定義在 RagAgent 與
            PlanningAgent 兩個常數類別的 TOP_K。
        filter_tags: 限定只搜尋帶有這些標籤的筆記，預設不限制。
        filter_file_path: 限定只搜尋這些筆記路徑，比對向量文件的 md_path 欄位，預設不限制。
        filter_note_type: 限定只搜尋這個類型的筆記，例如 Knowledge_summary，預設不限制。

    Returns:
        每筆含八個欄位的 chunk 清單：file_name 為筆記檔名，md_path 為人工核可後歸檔的 Markdown 路徑
        並作為資料血緣的關聯鍵，chunk_index 為該 chunk 在筆記中的序號，section 為章節標題路徑，
        content 為 chunk 純文字，tags 為筆記標籤清單，note_type 為筆記類型，
        score 為 cosine 相似度分數，範圍 0 到 1，數值越高代表越相關。
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
            "index": EmbeddingModel.VECTOR_INDEX,
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
        # 作為 data lineage 依據的欄位在 v2/task08 向量 doc 已由 file_path 收斂為 md_path（值＝archived md 路徑）
        vector_search_filter["md_path"] = {"$in": filter_file_path}
    elif filter_tags:
        vector_search_filter["tags"] = {"$in": filter_tags}

    if filter_note_type:
        vector_search_filter["note_type"] = filter_note_type

    if vector_search_filter:
        vector_search_stage["$vectorSearch"]["filter"] = vector_search_filter

    # Step 3: $project，只取需要的欄位，embedding 不回傳
    project_stage = {
        "$project": {
            "_id": 0,
            "file_name": 1,
            "md_path": 1,
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
