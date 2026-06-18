import os
import re
from functools import lru_cache
from dotenv import load_dotenv
from google.cloud import storage
from loguru import logger
from pathlib import Path

load_dotenv()

SRC_BUCKET = os.getenv("SOURCE_BUCKET")     # staging-vaults，存放 OneNote 筆記
DEST_BUCKET = os.getenv("DESTINATION_BUCKET")  # final-vaults，存放、歸檔審核過的筆記


@lru_cache(maxsize=1)
def _get_client() -> storage.Client:
    # 將路徑轉為絕對路徑，確保不論在哪個目錄執行都不會出錯
    json_path = os.getenv("ARCHIVE_TO_GCS_CREDENTIAL")
    if json_path:
        absolute_path = Path(json_path).resolve()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(absolute_path)
    return storage.Client()


def _local_to_src_bucket_blob(local_path: str) -> str:
    """將本地存放筆記的絕對路徑，轉為GCS的 src_bucket (staging vaults) 的 blob 路徑。"""
    base = os.getenv("ONENOTE_OUTPUT_DIR", "").rstrip("/") + "/"
    if base != "/" and local_path.startswith(base):
        return local_path[len(base):]
    return local_path


def _parse_src_bucket_blob(blob_path: str) -> dict:
    """從 src_bucket (staging vaults) 的 blob 路徑拆解出 account、notebook、section、page_stem。

    範例：iamaccountname1234/Data Engineering/yt_GCP/document01.html
    -> {account: iamaccountname1234, notebook: Data Engineering, section: yt_GCP, page_stem: document01}
    """
    parts = blob_path.split("/")
    return {"account": parts[0] if len(parts) > 0 else "",
            "notebook": parts[1] if len(parts) > 1 else "",
            "section": parts[2] if len(parts) > 2 else "",
            "page_stem": parts[3].rsplit(".", 1)[0] if len(parts) > 3 else "",
            }


def copy_images(page_record: dict) -> list[str]:
    """複製圖片從 src_bucket (staging vaults) 到 dest_bucket (personal vaults)，回傳已複製的 blob 路徑列表。

    複製後，src_bucket (staging vaults) 物件不自動刪除。
    """
    html_path = page_record.get("html_path", "")
    if not html_path:
        raise ValueError("page_record 缺少 html_path")

    # 從 img_path 欄位取出本頁圖片路徑列表，轉成 {檔名} set 做比對用
    img_path_raw: list = page_record.get("img_path") or []
    if not img_path_raw:
        logger.info(f"page_id={page_record.get('page_id')} 無 img_path，跳過圖片歸檔")
        return []
    target_filenames = {Path(p).name for p in img_path_raw}

    html_blob = _local_to_src_bucket_blob(html_path)
    parsed = _parse_src_bucket_blob(html_blob)
    account, notebook, section = parsed["account"], parsed["notebook"], parsed["section"]
    note_type = page_record.get("note_type") or "uncategorized"

    client = _get_client()
    src_bucket = client.bucket(SRC_BUCKET)
    dest_bucket = client.bucket(DEST_BUCKET)

    image_prefix = f"{account}/{notebook}/{section}/_images/"
    blobs = list(src_bucket.list_blobs(prefix=image_prefix))

    archived_paths: list[str] = []
    for blob in blobs:
        filename = blob.name[len(image_prefix):]
        if not filename:
            continue
        if filename not in target_filenames:
            continue
        dest_blob_path = (
            f"{account}/from-onenote/{note_type}/{notebook}/{section}/_attachment/{filename}"
        )
        src_bucket.copy_blob(blob, dest_bucket, new_name=dest_blob_path)
        archived_paths.append(dest_blob_path)
        logger.info(f"Copied image: {blob.name} ➡️ {DEST_BUCKET}/{dest_blob_path}")

    return archived_paths


def archive_md(page_record: dict, img_archive_paths: list[str]) -> str:
    """讀 src_bucket (staging vaults) 的 MD，改寫圖片路徑，寫入 dest_bucket (personal vaults)，回傳新 blob 路徑。

    圖片路徑從 `_images/foo.png` 改寫為 `./_attachment/foo.png`。
    src_bucket (staging vaults) 的 md 檔不自動刪除。
    """
    # 接收從 MongoDB Altas Metadata 元數據文檔集裡面的其中一筆文檔(其中一份筆記的元數據)，取 md_path
    md_path = page_record.get("md_path", "")
    if not md_path:
        raise ValueError("page_record 缺少 md_path")

    # GCS staging vault (src bucket) 內的 blob 係透過 rsync 將地端 md 檔同步/上傳過來的，
    # 所以即便 md_path 欄位值存的是地端 md 路徑， md_path 跟 src_bucket 下的 blob 路徑仍有高度相似度，
    # 可將 md_path 做 parsing 取出關鍵路徑片段:
    # 1. 拼湊出對應的 src_bucket blob 路徑，再讀取 blob 轉成文字；
    # 2. 也能拼湊出 new_md_path，用這個指定路徑寫入 new blob 到 dest_bucket 下。
    md_blob_path = _local_to_src_bucket_blob(md_path)
    parsed = _parse_src_bucket_blob(md_blob_path)
    account, notebook, section, page_stem = parsed["account"], parsed["notebook"], parsed["section"], parsed["page_stem"]

    note_type = page_record.get("note_type") or "uncategorized"

    # 連線 src_bucket (staging vaults) 與 dest_bucket (personal vaults)
    client = _get_client()
    src_bucket = client.bucket(SRC_BUCKET)
    dest_bucket = client.bucket(DEST_BUCKET)

    # 將 md_blob_path 指派成 src_bucket 下的一個 blob 物件後，透過 download_as_text() request.get HTTP 且 decode 成純文字檔
    raw_md = src_bucket.blob(md_blob_path).download_as_text(encoding="utf-8")

    # 改寫文字中關於圖片連結的路徑描述
    rewritten_md = re.sub(r'!\[([^\]]*)\]\(_images/([^)]+)\)',
                          lambda m: f"![{m.group(1)}](./_attachment/{m.group(2)})",
                          raw_md,
                          )

    # 拼湊出要把文字寫成什麼路徑的 blob
    dest_blob_path = (f"{account}/from-onenote/{note_type}/{notebook}/{section}/{page_stem}.md"
                      )

    # 上傳文字到指定路徑，並且標記這個檔案的 MIME type 是 markdown
    dest_bucket.blob(dest_blob_path).upload_from_string(rewritten_md,
                                                        content_type="text/markdown"
                                                        )
    logger.info(f"Archived MD: {DEST_BUCKET}/{dest_blob_path}")

    # 回傳寫入的路徑，以接續將路徑值更新在 MongoDB Altas 存放的元數據
    return dest_blob_path
