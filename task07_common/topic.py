"""主題分類工具：借用 task01 的 TOPIC_KEYWORDS 與推導邏輯，供 task07 三服務共用。

從 tags 與檔名/標題比對 TOPIC_KEYWORDS 推斷 topic：把 tags 轉小寫並補上檔名一起當比對目標 →
依鍵順序逐一比對，任一關鍵字命中就回該 topic → 全不中回 other。分類邏輯 copy 自
task01_obsidian_etl_v2/silver_transform_markdown/t_build_metadata_docs
（copy 而非 import，讓 task01/task07 各自獨立演化），
確保 onenote 與 obsidian 兩來源在同一份向量表下 topic 語意一致。
"""

from pathlib import Path

# 追蹤的主題關鍵字，key 順序有意義（越前面越優先匹配），供 Streamlit 畫雷達圖
TOPIC_KEYWORDS = {
    "python": ["python", "pandas", "numpy", "poetry", "pyenv", "pymongo", "sqlalchemy", "flask", "streamlit"],
    "database": ["sql", "mysql", "mongodb", "redis", "mongodb atlas"],
    "gcp": ["google-cloud-platform", "gcs", "bigquery", "vm", "compute-engine", "cloud-run", "artifact-registry"],
    "data-warehouse": ["hive", "bigquery"],
    "distribution-architecture": ["kafka", "producer", "consumer", "cap"],
    "orchestration": ["airflow", "cloud-run", "cloud-scheduler"],
    "etl": ["etl", "elt", "pipeline", "medallion-architecture", "dbt"],
    "ai": ["generative-ai", "gen-ai", "agent", "gemini", "claude", "openai", "dl", "deep-learning", "ai-evals"],
    "rag": ["embedding", "ragas", "chunk", "langchain"],
    "ml": ["machine-learning", "ml", "sklearn", "model"],
    "dockerize": ["docker", "container", "image", "dockerfile", "docker-compose"],
    "github": ["git", "github", "github-actions", "ci", "cd", "cicd"],
    "linux": ["os", "linux", "linux-command"],
    "biotech": [
        "biotech",
        "bioreactor",
        "gmp",
        "technology-transfer",
        "biopharma",
        "ALCOA+",
        "perfusion",
        "cell-culture",
        "upstream",
        "cell",
        "cell bank",
        "cell-culture",
        "filtration",
        "depth-filtration",
    ],
}


def infer_topic(tags: list[str], file_name: str) -> str:
    """從 tags 與檔名/標題比對 TOPIC_KEYWORDS，推斷這份筆記的 topic。

    1. 把 tags 全部轉小寫，並補上檔名（去副檔名）一起當作比對目標。
    2. 依 TOPIC_KEYWORDS 的鍵順序逐一比對，任一關鍵字命中就回該 topic。
    3. 全部比不到就回 other。

    鍵的順序代表優先權，越前面的 topic 越優先命中。Bronze 階段尚無 tags 時可傳 `[]`，
    僅以標題比對；Gold/reject 階段以 LLM 產出的 tags 一起比對取得最佳分類。

    Args:
        tags: 這份筆記的標籤清單（bronze 階段可為空 list）。
        file_name: 筆記檔名或頁面標題，取其 stem 一併參與比對。

    Returns:
        命中的 topic 字串，全不中時回 other。
    """
    stem = Path(file_name).stem
    search_targets = [t.lower() for t in tags] + [stem.lower()]
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if any(kw in target for target in search_targets):
                return topic
    return "other"
