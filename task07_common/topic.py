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
    "database": ["sql", "mysql", "mongodb", "redis", "mongodb atlas", "oltp"],
    "gcp": [
        "gcp",
        "google-cloud-platform",
        "gcs",
        "bigquery",
        "vm",
        "compute-engine",
        "cloud-run",
        "artifact-registry",
    ],
    "data-warehouse": ["data-warehouse", "hive", "bigquery", "olap"],
    "data-lake": ["s3", "gcs", "data-lake", "data-lakehouse"],
    "data-governance": ["data-governance", "data-modeling", "data-engineering"],
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

    1. 把 tags 全部轉小寫，並補上去掉副檔名的檔名一起當作比對目標。
    2. 依 TOPIC_KEYWORDS 的鍵順序逐一比對，任一關鍵字命中就回該 topic。
    3. 全部比不到就歸為 other-in-bioteach。

    Note:
        TOPIC_KEYWORDS 的鍵順序代表優先權，越前面的 topic 越先被命中，因此調整鍵順序會改變分類結果。
        Bronze 階段還沒有 tags，此時傳空清單、只以標題比對；
        歸檔與退件階段才拿 LLM 產出的 tags 一起比對，分類會更準確，因此同一份筆記在不同階段可能得到不同 topic。

    Args:
        tags: 這份筆記的標籤清單，Bronze 階段可傳空清單。
        file_name: 筆記檔名或頁面標題，取其主檔名一併參與比對。

    Returns:
        命中的 topic 字串；所有關鍵字都比不到時回 other-in-bioteach。
    """
    stem = Path(file_name).stem
    search_targets = [t.lower() for t in tags] + [stem.lower()]
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if any(kw in target for target in search_targets):
                return topic
    return "other-in-bioteach"
