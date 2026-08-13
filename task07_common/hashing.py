"""變動判定與物件指紋工具：對 html 算 sha256、取 GCS blob md5 作為物件指紋。

- html_source_hash：對下載後的 html 原始碼算 sha256，作為「筆記是否變動」與
  Silver enrichment 快取命中的內容指紋。選 hash 而非 Graph API 的 lastModifiedDateTime，
  是因為 page endpoint 的 lastModified 與 notebook/section 不同步、語意不清。
- gcs_object_md5：直接取 GCS blob 上傳後回傳的 md5_hash（base64），作為物件指紋。
"""

import hashlib

from google.cloud.storage import Blob


def html_source_hash(html: str) -> str:
    """對 html 原始碼算 sha256，作為判斷筆記是否變動與快取是否命中的依據。

    Note:
        這裡刻意用內容雜湊而不是 Graph API 提供的 lastModifiedDateTime，
        因為頁面層的修改時間與筆記本、章節層不同步，語意不清而無法作為變動判定依據。

    Args:
        html: 下載回來未經解析的 html 原始碼。

    Returns:
        十六進位表示的 sha256 字串。
    """
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def gcs_object_md5(blob: Blob) -> str | None:
    """取出一個 GCS 物件的 md5，作為該物件的指紋。

    Args:
        blob: 已上傳的 GCS blob 物件。

    Returns:
        base64 表示的 md5 字串；該物件尚未實際上傳時為 None。
    """
    return blob.md5_hash
