"""從 onenote_note_metadata 查詢待向量化筆記作為 gating，然後從 GCS 的 archived-notes/ 取歸檔 md 內文。

1. 查 status=archived 且 embedded_status=false 的版本，回傳含 archived md 路徑、md5 與圖片血緣的清單。
2. 依 md_archive_path 從 onenote-vaults/archived-notes/ 下載 md 內文 (markdown body) 後做清洗。

gate 的程式邏輯由 task06_obsidian_embed_etl_v2 copy 過來。

Required .env keys:
    GCS_USER_CREDENTIALS             (On-premise only) path to GCS service account JSON (for download archived md).
    MONGO_ALTAS_URI                  MongoDB Atlas connection string.
    MONGO_DB_NAME                    Target database name (defaults to skill_dashboard).

Optional .env keys:
    ONENOTE_GCS_BUCKET               GCS data lake bucket (defaults to onenote-vaults).
"""

import frontmatter
from google.cloud import storage
from loguru import logger
from pymongo.database import Database

NOTE_METADATA = "onenote_note_metadata"


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
    """從 onenote_note_metadata 挑出 status=archived 且 embedded_status=false 的版本，作為 embedding gate。

    1. 以 status 與 embedded_status 過濾，只留下已歸檔但尚未向量化的版本。
    2. 每筆只取後續會用到的七個欄位，其餘不投影。

    Note:
        - 這支函式只依 MongoDB 的狀態判斷，不重新掃描 GCS，因此歸檔檔案若被繞過 task07 直接改動，
          這裡不會察覺。
        - 七個投影欄位各有用途：archived_md_path 既是內容來源，也會成為向量文件 md_path 的值，
          用於 data lineage，並在 CAS 時定位該版本；md_md5_hash 是 CAS 的守衛值；
          page_id 與 dt 是 metadata 的複合唯一鍵；md_frontmatter 與 page_title 寫進向量文件供篩選與組
          prompt 標題；attached_images 記錄該版本每張圖片歸檔後的位址，供 chunk 內的圖片語法對上實際檔案。

    Args:
        db: pymongo Database 物件。

    Returns:
        待向量化的版本清單，每筆含 page_id、dt、archived_md_path、md_md5_hash、md_frontmatter、
        page_title 與 attached_images；沒有待做版本時為空清單。
    """
    collection = db[NOTE_METADATA]
    projection = {
        "page_id": 1,
        "dt": 1,
        "archived_md_path": 1,
        "md_md5_hash": 1,
        "md_frontmatter": 1,
        "page_title": 1,
        "attached_images": 1,
    }
    gate_list = list(collection.find({"status": "archived", "embedded_status": False}, projection))
    logger.info(f"embedding gate：{len(gate_list)} 份 archived 且未向量化的 onenote 版本待處理")
    return gate_list


def fetch_archived_content(md_archive_path: str, bucket_name: str = "onenote-vaults") -> str:
    """從 GCS 拉取單一歸檔 .md 檔的 body 內文，不取 frontmatter。

    1. 依傳入的路徑從 GCS 下載這份檔案的完整內容。
    2. 以 UTF-8 解碼後拆掉 frontmatter。
    3. 只回傳正文字串。

    Note:
        - 向量化只需要正文，frontmatter 的標籤與類型等欄位已由 get_embedding_gate_list 另行帶入，
          在這裡重複解析沒有意義。

    Args:
        md_archive_path: 已歸檔且尚未向量化的 .md 路徑，可含或不含 gs 協定與 bucket 前綴。
        bucket_name: GCS bucket 名稱，預設 onenote-vaults。

    Returns:
        該 .md 去除 frontmatter 後的正文字串。

    Raises:
        Exception: 檔案不存在或下載失敗時的例外一律原樣往外拋，這裡不做攔截。
    """
    # 此處的例外將外拋由 t_chunk_and_embed_onenote() 函式攔截
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name_from_uri(md_archive_path, bucket_name))
    post = frontmatter.loads(blob.download_as_text(encoding="utf-8"))
    return post.content
