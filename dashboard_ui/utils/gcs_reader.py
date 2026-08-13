"""GCS 讀取工具：從資料湖 bucket 讀出文字與圖片，供 Streamlit 頁面唯讀取用。

1. 函式 read_text 從指定 bucket 讀取 HTML 或 md 文字內容，找不到時回傳空字串。
2. 函式 read_bytes_as_base64 讀取圖片 blob 並轉成 base64 字串，供頁面內嵌顯示。
"""

import base64
from functools import lru_cache

from google.cloud import storage
from loguru import logger


@lru_cache(maxsize=1)
def _get_client() -> storage.Client:
    """建立 GCS client 並快取，讓同一個行程內的所有讀取共用一份連線。

    Returns:
        以應用程式預設憑證初始化的 google-cloud-storage Client 物件。
    """
    return storage.Client()


def read_text(src_bucket: str, blob_path: str) -> str:
    """從指定 bucket 讀取一個文字物件，適用於 HTML 與 Markdown。

    讀取失敗時不中斷頁面渲染，改為記錄一筆 warning 並回傳空字串，由呼叫端自行決定替代顯示。

    Args:
        src_bucket: 來源 bucket 名稱，例如 onenote-vaults。
        blob_path: bucket 內的物件路徑，不含 bucket 名稱前綴。

    Returns:
        以 UTF-8 解碼後的文字內容；物件不存在或讀取失敗時回傳空字串。
    """
    try:
        client = _get_client()
        blob = client.bucket(src_bucket).blob(blob_path)
        return blob.download_as_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"GCS read_text failed: {src_bucket}/{blob_path} — {e}")
        return ""


def read_bytes_as_base64(src_bucket: str, blob_path: str) -> str:
    """從指定 bucket 讀取一個圖片物件，並轉成可直接內嵌於 HTML 的 base64 data URI。

    附檔名決定 MIME type，png 以外的副檔名一律組成 image 加上該副檔名。
    讀取失敗時不中斷頁面渲染，改為記錄一筆 warning 並回傳空字串。

    Args:
        src_bucket: 來源 bucket 名稱，例如 onenote-vaults。
        blob_path: bucket 內的圖片物件路徑，不含 bucket 名稱前綴。

    Returns:
        data 開頭的 base64 data URI 字串；物件不存在或讀取失敗時回傳空字串。
    """
    try:
        client = _get_client()
        blob = client.bucket(src_bucket).blob(blob_path)
        # debug: 看一下 GET URI 的 URI 長怎樣
        # logger.debug(f"Attempting to read blob: repr={repr(blob)}")
        data = blob.download_as_bytes()
        ext = blob_path.rsplit(".", 1)[-1].lower()
        mime = "image/png" if ext == "png" else f"image/{ext}"
        encoded = base64.b64encode(data).decode("utf-8")
        return f"data:{mime};base64,{encoded}"
    except Exception as e:
        logger.warning(f"GCS read_bytes_as_base64 failed: {src_bucket}/{blob_path} — {e}")
        return ""


def _split_gs_uri(uri: str) -> tuple[str, str]:
    """把一個完整的 gs 協定 URI 拆成 bucket 名稱與物件路徑兩段。

    傳入的字串若不是 gs 協定開頭，代表資料來源記錄有誤，此時記錄一筆 warning 並回傳空的 bucket 名稱，
    讓呼叫端在後續讀取時自然失敗，不在這裡中斷流程。

    Args:
        uri: 完整物件位址，格式為 gs 加上 bucket 名稱與物件路徑。

    Returns:
        bucket 名稱與物件路徑組成的 tuple；格式不符時 bucket 名稱為空字串，物件路徑為原字串。
    """
    if not uri.startswith("gs://"):
        logger.warning(f"Not a gs:// URI: {uri}")
        return "", uri
    bucket, _, key = uri[len("gs://") :].partition("/")
    return bucket, key


def read_text_by_uri(uri: str) -> str:
    """以完整的 gs 協定 URI 讀取一個文字物件，適用於 HTML 與 Markdown。

    供 task07 lazy_loading 使用，因其 metadata 存放的是完整 gs 協定 URI 而非本機路徑。

    Args:
        uri: 完整物件位址，格式為 gs 加上 bucket 名稱與物件路徑。

    Returns:
        以 UTF-8 解碼後的文字內容；物件不存在或讀取失敗時回傳空字串。
    """
    bucket, key = _split_gs_uri(uri)
    return read_text(bucket, key)


def read_image_base64_by_uri(uri: str) -> str:
    """以完整的 gs 協定 URI 讀取一個圖片物件，並轉成可直接內嵌於 HTML 的 base64 data URI。

    Args:
        uri: 完整物件位址，格式為 gs 加上 bucket 名稱與物件路徑。

    Returns:
        data 開頭的 base64 data URI 字串；物件不存在或讀取失敗時回傳空字串。
    """
    bucket, key = _split_gs_uri(uri)
    return read_bytes_as_base64(bucket, key)
