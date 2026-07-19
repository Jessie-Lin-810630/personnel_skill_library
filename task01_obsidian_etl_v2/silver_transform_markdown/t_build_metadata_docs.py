"""把 CDC 挑中、下載下來的 raw .md 內文，組裝歸檔前的此檔的 metadata，寫入 obsidian_note_metadata

1. 解析 frontmatter，組出 archived_md_frontmatter 所需的內嵌欄位。
2. 推論 topic 欄位值。
3. 拆出 note_user_id、notebook、section、file_name 欄位值。
4. 計算 raw_md_path、raw_md_md5_hash、raw_md_updated_at、字數等欄位值。
5. 解析 .md 附件圖片的路徑，組出 attached_images 欄位所需的內嵌物件之陣列。

其他欄位如： archived_* 欄位、status、embedded_status、embedded_at 等屬於歸檔後才執行的任務，
合理性由 Load 層歸檔後才補；未來若插入 LLM enrichment，掛載順序點見 build_note_document 內標註。

Required .env keys:
    (無；純資料轉換，圖片 md5 由呼叫端傳入的 image_md5_index 提供。)
"""

from pathlib import Path

import frontmatter
from google.cloud.storage import Blob
from loguru import logger

from .e_get_changed_files import RAW_PREFIX
from .t_transform_attached_images import extract_attached_images
from .t_transform_frontmatter import extract_frontmatter

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


def _parse_note_path(blob_name: str) -> dict[str, str]:
    """把 gs://<bucket>/raw-notes/ 的 blob 名稱拆解成 note_user_id、notebook、section、file_name 四段。

    1. 若名稱開頭是 raw-notes/ 前綴，先去掉前綴只留相對路徑。
    2. 以路徑分隔切成各段，第一段是使用者、第二段是筆記本、倒數第二段是章節、最後一段是檔名。
    3. 路徑段數不足時，對應欄位以空字串補上，不拋錯。

    以 raw-notes/lucky460721/data-engineering/01-daily-logs/x.md 為例，會得到 note_user_id 為
    lucky460721、notebook 為 data-engineering、section 為 01-daily-logs、file_name 為 x.md。

    Args:
        blob_name: GCS 上該 .md 的 blob 名稱，可含或不含 raw-notes/ 前綴。

    Returns:
        含 note_user_id、notebook、section、file_name 四個鍵的字典。
    """
    rel = blob_name[len(RAW_PREFIX) :] if blob_name.startswith(RAW_PREFIX) else blob_name
    parts = Path(rel).parts
    return {
        "note_user_id": parts[0] if len(parts) > 0 else "",
        "notebook": parts[1] if len(parts) > 1 else "",
        "section": parts[-2] if len(parts) >= 2 else "",
        "file_name": parts[-1] if parts else "",
    }


def _infer_topic(tags: list[str], md_file_path: str) -> str:
    """從 tags 與檔名比對 TOPIC_KEYWORDS，推斷這份筆記的 topic。

    1. 把 tags 全部轉小寫，並補上檔名一起當作比對目標。
    2. 依 TOPIC_KEYWORDS 的鍵順序逐一比對，任一關鍵字命中就回該 topic。
    3. 全部比不到就回 other。

    鍵的順序代表優先權，越前面的 topic 越優先命中。

    Args:
        tags: 這份筆記的標籤清單。
        md_file_path: 這份 .md 的路徑，取其檔名一併參與比對。

    Returns:
        命中的 topic 字串，全不中時回 other。
    """
    file_name = Path(md_file_path).stem
    search_targets = [t.lower() for t in tags] + [file_name.lower()]
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if any(kw in target for target in search_targets):
                return topic
    return "other-in-de"


def build_note_document(blob: Blob, text: str, bucket_name: str, image_md5_index: dict[str, str]) -> dict:
    """把單份 raw .md 的內文清洗成可插入 obsidian_note_metadata 的 document，不含 archived_* 與狀態欄位。

    1. 呼叫 function `extract_frontmatter` 解析 frontmatter，
       組出 archived_md_frontmatter 所需的內嵌欄位。
    2. 從 tags 與檔名推斷 topic。
    3. 從 blob 名稱拆出 note_user_id、notebook、section、file_name。
    4. 補上 raw_md_path、raw_md_md5_hash、raw_md_updated_at、字數。
    5. 呼叫 function `extract_attached_images`，解析 md 附件圖片的資料血緣，
       組出 attached_images 所需的內嵌物件之陣列。

    **Notes:**
        archived_* 欄位、status、embedded_status 與時間戳由 Load 歸檔後補；
        未來若要插入 LLM enrichment，掛載點見函式內註解。

    Args:
        blob: 這份 raw .md 的 GCS blob，提供名稱、md5 與更新時間。
        text: 已下載的 .md 內文。
        bucket_name: gs://<bucket>/raw-notes/ 所在的 GCS bucket 名稱。
        image_md5_index: GCS 現況的圖片路徑對 md5 字典，由 list_raw_blobs() 回傳值傳入，
        供寫入 attached_images 欄位時所需要的 md5_hash 值。

    Returns:
        一份 note document 字典，供 Load 歸檔並 upsert。
    """
    logger.info(f"下載 {Path(blob.name).name} 完成，開始清理...")
    post = frontmatter.loads(text)
    md_file_path = blob.name
    md_frontmatter = extract_frontmatter(post, md_file_path)
    topic = _infer_topic(md_frontmatter["tags"], md_file_path)

    # --- 未來 LLM document enrichment 掛載點 ---
    # 若日後要在此插入多模態 enrichment，於此處對 post.content 做生成，
    # 並斟酌把 extract_frontmatter、_infer_topic 等清洗步驟挪到生成之後。

    path_parts = _parse_note_path(md_file_path)

    return {
        **path_parts,  # note_user_id / notebook / section / file_name
        "raw_md_path": f"gs://{bucket_name}/{md_file_path}",
        "raw_md_md5_hash": blob.md5_hash,
        "raw_md_updated_at": blob.updated,
        "topic": topic,
        "word_count": len(post.content.split()),
        "archived_md_frontmatter": md_frontmatter,
        "attached_images": extract_attached_images(post.content, md_file_path, image_md5_index),
    }
