"""GCS data lake 讀寫工具：單一固定 bucket、以資料層＋user_id 組出三層 blob 路徑。

工具預設固定使用 bucket "onenote-vaults"，但可由環境變數 ONENOTE_GCS_BUCKET 覆寫。

預計透過工具可處理得到以下三層 blob 路徑:
    1. Bronze layer
        - raw-notes/<user_id>/<notebook>/<section>/dt=.../page.html
        - raw-notes/<user_id>/<notebook>/<section>/dt=.../_images/x.png
    2. Silver layer
        - processed-notes/<user_id>/<notebook>/<section>/dt=<bronze的dt>/page.md
    3. Gold layer
        - archived-notes/<user_id>/<notebook>/<section>/dt=<bronze的dt>/page.md
        - archived-notes/<user_id>/<notebook>/<section>/dt=<bronze的dt>/_images/x.png
"""

import os
from pathlib import PurePosixPath

from google.cloud import storage

_client: storage.Client | None = None

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
}


def _get_client() -> storage.Client:
    """取得 (並快取) GCS storage client；首次呼叫才建立。"""
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


def get_bucket_name() -> str:
    """回傳資料湖 bucket 名稱 (env ONENOTE_GCS_BUCKET，預設 onenote-vaults)。"""
    return os.getenv("ONENOTE_GCS_BUCKET", "onenote-vaults").strip()


def gs_uri(blob_path: str) -> str:
    """把 bucket 相對 key 包成完整 `'gs://'` 開頭的 URI (metadata 一律存完整 URI)。"""
    return f"gs://{get_bucket_name()}/{blob_path}"


def _split_uri(uri: str) -> tuple[str, str]:
    """gs://bucket/key... → (bucket, key)。"""
    bucket, _, key = uri[len("gs://") :].partition("/")
    return bucket, key


def raw_note_prefix(user_id: str, notebook: str, section: str, dt: str) -> str:
    """Bronze 層用: html 檔與 _images/xxx.png 檔的 blob 路徑前綴 (不含 `gs://bucket`)。

    Args:
        user_id (str): OneNote User ID
        notebook (str): OneNote notebook name
        section (str): OneNote notebook section name
        dt (str): 筆記的分區字串，dt=代表bronze層任務於何時下載筆記

    Returns:
        str: 例如 raw-notes/iamuser/生技製劑筆記本/general-technical/dt=2026-07-01
    """
    return f"raw-notes/{user_id}/{notebook}/{section}/dt={dt}"


def processed_note_prefix(user_id: str, notebook: str, section: str, dt: str) -> str:
    """Silver 層用: md 的 blob 路徑前綴 (不含 `gs://bucket`)。

    Args:
        user_id (str): OneNote User ID
        notebook (str): OneNote notebook name
        section (str): OneNote notebook section name
        dt (str): 筆記的分區字串，dt=代表bronze層任務於何時下載筆記

    Returns:
        str: 例如 processed-notes/iamuser/生技筆記本/general-technical/dt=2026-07-01
    """
    return f"processed-notes/{user_id}/{notebook}/{section}/dt={dt}"


def archived_note_prefix(user_id: str, notebook: str, section: str, dt: str) -> str:
    """Gold 層用: 歸檔之 md 與 _images/xxx.png 檔的 blob 路徑前綴 (不含 `gs://bucket`)。

    Args:
        user_id (str): OneNote User ID
        notebook (str): OneNote notebook name
        section (str): OneNote notebook section name
        dt (str): 筆記的分區字串，dt=代表bronze層任務於何時下載筆記

    Returns:
        str: 例如 archived-notes/iamuser/生技筆記本/general-technical/dt=2026-07-01
    """
    return f"archived-notes/{user_id}/{notebook}/{section}/dt={dt}"


def _content_type(blob_path: str) -> str | None:
    """由 blob 副檔名對出上傳用的 Content-Type；未知副檔名回 None。"""
    ext = PurePosixPath(blob_path).suffix.lower()
    return _CONTENT_TYPES.get(ext)


def upload_text(blob_path: str, text: str, bucket_name: str | None = None) -> str | None:
    """上傳字串，回傳 GCS 物件之 md5_hash。

    Args:
        blob_path (str): blob 路徑 (不含 `gs://bucket`)
        text (str): 欲上傳的字串
        bucket_name (str): bucket 名稱，若不傳入則從環境變數 ONENOTE_GCS_BUCKET 讀取

    Returns:
        str | None: blob 之 md5 hash 雜湊值
    """
    if bucket_name is None:
        bucket_name = get_bucket_name()
    blob = _get_client().bucket(bucket_name).blob(blob_path)
    blob.upload_from_string(text, content_type=_content_type(blob_path))
    return blob.md5_hash


def upload_bytes(blob_path: str, data: bytes, bucket_name: str | None = None) -> str | None:
    """上傳 bytes (圖片)，回傳 GCS 物件 md5_hash。

    Args:
        blob_path (str): blob 路徑 (不含 `gs://bucket`)
        data (bytes): 欲上傳的圖片
        bucket_name (str): bucket 名稱，若不傳入則從環境變數 ONENOTE_GCS_BUCKET 讀取

    Returns:
        str | None: blob 之 md5 hash 雜湊值
    """
    if bucket_name is None:
        bucket_name = get_bucket_name()
    blob = _get_client().bucket(bucket_name).blob(blob_path)
    blob.upload_from_string(data, content_type=_content_type(blob_path))
    return blob.md5_hash


def download_text(path: str) -> str:
    """讀 GCS 文字物件 (path 可為完整 gs:// URI 或 bucket 相對 key)。

    傳入完整 gs:// URI 時取其 bucket；傳入相對 key 時 bucket name 從環境變數 ONENOTE_GCS_BUCKET 讀取。

    Args:
        path (str): 例如 `gs://bucket/path/to/blob.md`, `path/to/blob.md`

    Returns:
        str: 下載後以 utf-8 decode 的字串
    """
    if path.startswith("gs://"):
        bucket_name, key = _split_uri(path)
    else:
        bucket_name, key = get_bucket_name(), path
    blob = _get_client().bucket(bucket_name).blob(key)
    return blob.download_as_text(encoding="utf-8")


def download_bytes(path: str) -> bytes:
    """讀 GCS 二進位物件 (圖片；path 可為完整 gs:// URI 或 bucket 相對 key)。

    傳入完整 gs:// URI 時取其 bucket；傳入相對 key 時 bucket name 從環境變數 ONENOTE_GCS_BUCKET 讀取。

    Args:
        path (str): 例如 `gs://bucket/path/to/blob.png`, `path/to/blob.png`

    Returns:
        bytes: bytes 物件。
    """
    if path.startswith("gs://"):
        bucket_name, key = _split_uri(path)
    else:
        bucket_name, key = get_bucket_name(), path
    blob = _get_client().bucket(bucket_name).blob(key)
    return blob.download_as_bytes()


def copy_blob(src_uri: str, dst_blob: str) -> str | None:
    """把來源物件 server-side 複製到預設 bucket 的 dst_blob，回傳目的物件 md5_hash。

    同 bucket 走 GCS server-side copy (不經本機流量) ；跨 bucket 亦由 copy_blob 處理。

    Args:
        src_uri (str): 來源端之 URI，可為完整 gs:// URI 或 bucket 相對 key
        dst_blob (str): 目的地之 blob 路徑，bucket name 從環境變數 ONENOTE_GCS_BUCKET 讀取。

    Returns:
        str | None: 複製完成後目的地物件之 md5 雜湊值。
    """
    if src_uri.startswith("gs://"):
        src_bucket_name, src_key = _split_uri(src_uri)
    else:
        src_bucket_name, src_key = get_bucket_name(), src_uri
    client = _get_client()
    src_bucket = client.bucket(src_bucket_name)
    src = src_bucket.blob(src_key)
    dst_bucket = client.bucket(get_bucket_name())
    copied = src_bucket.copy_blob(src, dst_bucket, dst_blob)
    return copied.md5_hash
