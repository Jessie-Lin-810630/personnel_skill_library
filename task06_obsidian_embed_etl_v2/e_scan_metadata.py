"""從 obsidian_note_metadata 挑待向量化筆記（gate）、並從 archived-notes 取清洗後 md 內文。

查 status=archived 且 embedded_status=false 的筆記 → 回傳含 archived 路徑/md5/圖片血緣的清單
→ 依 archived_md_path 從 archived-notes/ 下載 md body 清洗。此為 embedding 的 ingestion 端。

Required .env keys:
    GCS_USER_CREDENTIALS            (On-premise only) path to GCS service account JSON (for download md).
    MONGO_ALTAS_URI                  MongoDB Atlas connection string.
    MONGO_DB_NAME                    Target database name (skill_dashboard).
"""

import frontmatter
from google.cloud import storage
from loguru import logger
from pymongo.database import Database

NOTE_METADATA = "obsidian_note_metadata"


def blob_name_from_uri(uri: str, bucket_name_of_uri: str) -> str:
    """從 gs://bucket/xxx 這樣的完整 URI 取回 blob 名稱 xxx，供後續下載使用。

    有帶 gs://<bucket>/ 前綴時才去掉前綴，否則原樣回傳。

    Args:
        uri: GCS 的完整 gs:// URI，或已是 blob 名稱。
        bucket_name_of_uri: 要剝除的 bucket 名稱。

    Returns:
        blob 名稱字串。
    """
    prefix = f"gs://{bucket_name_of_uri}/"
    return uri[len(prefix) :] if uri.startswith(prefix) else uri


def get_embedding_gate_list(db: Database) -> list[dict]:
    """從 obsidian_note_metadata 挑出 status=archived 且 embedded_status=false 的筆記，作為 embedding gate。

    1. 以 status 與 embedded_status 過濾，只留下已歸檔但尚未向量化的筆記。
    2. 每筆只投影 embedding 需要的欄位：raw_md_path 為 metadata 主鍵（CAS 定位筆記用）、
       archived_md_path 既是內文來源、也是寫入向量表的血緣欄 md_path 值、archived_md_md5_hash 供 CAS 守衛，
       另外帶上 archived_md_frontmatter 與 file_name。

    只依 database 狀態判斷，不重掃 GCS。

    Args:
        db: pymongo Database 物件。

    Returns:
        待向量化的筆記清單，每筆是含上述欄位的字典。
    """
    collection = db[NOTE_METADATA]
    projection = {
        "raw_md_path": 1,
        "archived_md_path": 1,
        "archived_md_md5_hash": 1,
        "archived_md_frontmatter": 1,
        "file_name": 1,
    }
    gate_list = list(collection.find({"status": "archived", "embedded_status": False}, projection))
    logger.info(f"embedding gate：{len(gate_list)} 份 archived 且未向量化的筆記待處理")
    return gate_list


def fetch_archived_content(archived_md_path: str, bucket_name: str = "personal-vaults") -> str:
    """從 GCS 拉取單一 .md 檔的 body 內文，不取 frontmatter。

    1. 接收 get_embedding_gate_list() 回傳的 list[dict] 對 dict 的 archived_md_path key 取值。
    2. 根據傳入的 archived_md_path 從 GCS 重新拉取該檔案的原始 markdown 內文。
    3. 拿掉 frontmatter 後，以 UTF-8 decode 後回傳 body 的字串。

    Args:
        archived_md_path: 已歸檔且尚未向量化的 .md file path，
        可包含或不包含 `gs://<bucket>` 前綴字串。
        bucket_name: GCS bucket 名稱，預設 "personal-vaults"。

    Returns:
        該 .md 去除 frontmatter 後的 body 文字。
    """
    # 此處的例外將外拋由 t_chunk_and_embed_v2() 函式攔截
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name_from_uri(archived_md_path, bucket_name))
    post = frontmatter.loads(blob.download_as_text(encoding="utf-8"))
    return post.content
