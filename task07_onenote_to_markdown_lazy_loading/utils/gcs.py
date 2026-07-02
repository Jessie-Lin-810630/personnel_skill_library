"""GCS data lake 讀寫工具：單一固定 bucket、以資料層＋user_id 組出三層 blob 路徑。

單一固定 bucket（預設 onenote-vaults，可由 env ONENOTE_GCS_BUCKET 覆寫），
不以 user_id 命名 bucket（避免 bucket 過多）。

三層 blob 路徑（user_id 放在資料層之下）：
  raw-notes/<user_id>/<notebook>/<section>/dt=.../page.html        Bronze html
  raw-notes/<user_id>/<notebook>/<section>/dt=.../_images/x.png    Bronze 圖片
  processed-notes/<user_id>/<notebook>/<section>/dt=.../page.md    Silver enriched md
  （Gold archived 由 dashboard 分支的 Archive 端點負責，不在此模組）
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
    """取得（並快取）GCS storage client；首次呼叫才建立。"""
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


def get_bucket_name() -> str:
    """回傳資料湖 bucket 名稱（env ONENOTE_GCS_BUCKET，預設 onenote-vaults）。"""
    return os.getenv("ONENOTE_GCS_BUCKET", "onenote-vaults").strip()


def gs_uri(blob_path: str) -> str:
    """把 bucket 相對 key 包成完整 `'gs://'` 開頭的 URI (metadata 一律存完整 URI)。"""
    return f"gs://{get_bucket_name()}/{blob_path}"


def _split_uri(uri: str) -> tuple[str, str]:
    """gs://bucket/key... → (bucket, key)。"""
    bucket, _, key = uri[len("gs://") :].partition("/")
    return bucket, key


def raw_note_prefix(user_id: str, notebook: str, section: str, dt: str) -> str:
    """Bronze layer html 與 _images 檔的 blob 路徑前綴（不含 `gs://`）。"""
    return f"raw-notes/{user_id}/{notebook}/{section}/dt={dt}"


def processed_note_prefix(user_id: str, notebook: str, section: str, dt: str) -> str:
    """Silver md 的 blob 路徑前綴（dt= 對齊 bronze 執行日，不含 `gs://`）。"""
    return f"processed-notes/{user_id}/{notebook}/{section}/dt={dt}"


def _content_type(blob_path: str) -> str | None:
    """由 blob 副檔名對出上傳用的 Content-Type；未知副檔名回 None。"""
    ext = PurePosixPath(blob_path).suffix.lower()
    return _CONTENT_TYPES.get(ext)


def upload_text(blob_path: str, text: str) -> str | None:
    """上傳字串，回傳 GCS 物件 md5_hash。"""
    blob = _get_client().bucket(get_bucket_name()).blob(blob_path)
    blob.upload_from_string(text, content_type=_content_type(blob_path))
    return blob.md5_hash


def upload_bytes(blob_path: str, data: bytes) -> str | None:
    """上傳 bytes（圖片），回傳 GCS 物件 md5_hash。"""
    blob = _get_client().bucket(get_bucket_name()).blob(blob_path)
    blob.upload_from_string(data, content_type=_content_type(blob_path))
    return blob.md5_hash


def download_text(path: str) -> str:
    """讀 GCS 文字物件。path 可為完整 gs:// URI（取其 bucket）或 bucket 相對 key（用預設 bucket）。"""
    if path.startswith("gs://"):
        bucket_name, key = _split_uri(path)
    else:
        bucket_name, key = get_bucket_name(), path
    blob = _get_client().bucket(bucket_name).blob(key)
    return blob.download_as_text(encoding="utf-8")
