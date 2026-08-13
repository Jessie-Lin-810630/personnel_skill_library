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
    2. 每筆只取後續會用到的五個欄位，其餘不投影。

    Note:
        這支函式只依 MongoDB 的狀態判斷，不重新掃描 GCS，因此 GCS 上的檔案若被繞過 task01 直接改動，
        這裡不會察覺。五個投影欄位各有用途：raw_md_path 是唯一鍵，後續 CAS 以它定位筆記；
        archived_md_path 既是內容來源，也會成為向量文件 md_path 的值，用於 data lineage；
        archived_md_md5_hash 是 CAS 的守衛值；archived_md_frontmatter 與 file_name 則寫進向量文件供篩選。

    Args:
        db: pymongo Database 物件。

    Returns:
        待向量化的筆記清單，每筆含 raw_md_path、archived_md_path、archived_md_md5_hash、
        archived_md_frontmatter 與 file_name；沒有待做筆記時為空清單。
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

    1. 依傳入的路徑從 GCS 下載這份檔案的完整內容。
    2. 以 UTF-8 解碼後拆掉 frontmatter。
    3. 只回傳正文字串。

    Note:
        向量化只需要正文，frontmatter 的標籤與類型等欄位已由 get_embedding_gate_list 另行帶入，
        在這裡重複解析沒有意義。

    Args:
        archived_md_path: 已歸檔且尚未向量化的 .md 路徑，可含或不含 gs 協定與 bucket 前綴。
        bucket_name: GCS bucket 名稱，預設 personal-vaults。

    Returns:
        該 .md 去除 frontmatter 後的正文字串。

    Raises:
        Exception: 檔案不存在或下載失敗時的例外一律原樣往外拋，這裡不做攔截。
    """
    # 此處的例外將外拋由 t_chunk_and_embed_v2() 函式攔截
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name_from_uri(archived_md_path, bucket_name))
    post = frontmatter.loads(blob.download_as_text(encoding="utf-8"))
    return post.content
