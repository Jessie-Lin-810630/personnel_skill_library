"""變動判定與物件指紋工具：對 html 算 sha256、取 GCS blob md5 作為物件指紋。

- html_source_hash：對下載後的 html 原始碼算 sha256，作為「筆記是否變動」與
  Silver enrichment 的冪等鍵。選 hash 而非 Graph API 的 lastModifiedDateTime，
  是因為 page endpoint 的 lastModified 與 notebook/section 不同步、語意不清。
- gcs_object_md5：直接取 GCS blob 上傳後回傳的 md5_hash（base64），作為物件指紋。
"""

import hashlib

from google.cloud.storage import Blob


def html_source_hash(html: str) -> str:
    """對 html 原始碼字串算 sha256 hexdigest（變動判定 / enrichment 冪等鍵）。"""
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def gcs_object_md5(blob: Blob) -> str | None:
    """取 GCS blob 上傳後的 md5_hash（base64 字串）。未上傳則為 None。"""
    return blob.md5_hash
