import base64
import os
from functools import lru_cache

from dotenv import load_dotenv
from google.cloud import storage
from loguru import logger

load_dotenv()

SRC_BUCKET = os.getenv("SOURCE_BUCKET", "onenote-vaults")


@lru_cache(maxsize=1)
def _get_client() -> storage.Client:
    return storage.Client()


def read_text(src_bucket: str, blob_path: str) -> str:
    """從 src_bucket (staging vaults) 讀取文字內容（HTML 或 MD）。找不到回傳空字串。"""
    try:
        client = _get_client()
        blob = client.bucket(src_bucket).blob(blob_path)
        return blob.download_as_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"GCS read_text failed: {src_bucket}/{blob_path} — {e}")
        return ""


def read_bytes_as_base64(src_bucket: str, blob_path: str) -> str:
    """從 src_bucket (staging vaults) 讀取二進位內容（PNG）並回傳 base64 data URI。找不到回傳空字串。"""
    try:
        client = _get_client()
        blob = client.bucket(src_bucket).blob(blob_path)
        data = blob.download_as_bytes()
        ext = blob_path.rsplit(".", 1)[-1].lower()
        mime = "image/png" if ext == "png" else f"image/{ext}"
        encoded = base64.b64encode(data).decode("utf-8")
        return f"data:{mime};base64,{encoded}"
    except Exception as e:
        logger.warning(f"GCS read_bytes_as_base64 failed: {src_bucket}/{blob_path} — {e}")
        return ""


def local_path_to_gcs_blob(local_path: str) -> str:
    """將本地絕對路徑轉為 GCS blob 路徑（strip ONENOTE_OUTPUT_DIR prefix）。

    本地：/Users/foo/Desktop/OneNote-Export/lucky460721/NB/Sec/page.html
    GCS：  lucky460721/NB/Sec/page.html
    """
    base = os.getenv("ONENOTE_OUTPUT_DIR", "")
    if not base:
        logger.warning("ONENOTE_OUTPUT_DIR 未設定，無法轉換 GCS blob 路徑")
        return local_path
    base = base.rstrip("/") + "/"
    if local_path.startswith(base):
        return local_path[len(base) :]
    return local_path
