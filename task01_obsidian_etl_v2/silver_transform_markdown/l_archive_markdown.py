"""把清洗後的 .md 與其引用圖片歸檔到 GCS Gold 層 archived-notes/，並回填 archived_* 欄位。

1. archive_note 依 raw_md_path 算 archived 名
2. 覆寫清洗後 frontmatter 上傳 .md、逐張 copy 圖片
3. 回填 archived_md_path/md5/archived_at；整段採覆蓋語意，重跑同版本結果一致。

Required .env keys:
    GOOGLE_APPLICATION_CREDENTIALS   (On-premise only) GCS service account JSON path (copy / upload blobs).
"""

from datetime import datetime, timezone
from pathlib import Path

import frontmatter
from google.cloud.storage import Bucket
from loguru import logger

from .e_get_changed_files import ARCHIVED_PREFIX, RAW_PREFIX


def _archived_name(raw_blob_name: str) -> str:
    """把 blob 名稱開頭的 raw-notes/ 前綴換成 archived-notes/，後段路徑保持不變。

    Args:
        raw_blob_name: gs://<bucket>/raw-notes/ 下的 blob 名稱。

    Returns:
        對應的 archived-notes/ blob 名稱。
    """
    return raw_blob_name.replace(RAW_PREFIX, ARCHIVED_PREFIX, 1)


def _copy_blob(bucket: Bucket, src_name: str, dest_name: str) -> str:
    """在同一個 bucket 內把來源 blob 複製到目的名稱，回傳 archived 端的 md5。

    採覆蓋語意，目的已存在就覆寫。複製後若回應沒帶 md5，就重新載入一次 metadata 再取。

    Args:
        bucket: 來源與目的所在的 GCS Bucket 物件。
        src_name: 來源 blob 名稱。
        dest_name: 目的 blob 名稱。

    Returns:
        目的 blob 的 md5 字串。
    """
    src_blob = bucket.blob(src_name)
    new_blob = bucket.copy_blob(src_blob, bucket, dest_name)
    if new_blob.md5_hash is None:
        new_blob.reload()
    return new_blob.md5_hash


def _delete_misposition_metadata(post: frontmatter.Post) -> None:
    """當 frontmatter 誤植到正文時的清掃，掃正文頂端的 key: value 區塊把欄位刪掉。

    1. 逐行往下掃直到碰到第一個真正的 Markdown 標題行就停；行首的 # 後面要接空白或再一個 #，
    這樣行內標籤 #python 才不會被誤判成標題而提早截斷。
    2. 將停下之前的所有行以空白字串 replace 掉。

    Args:
        post: frontmatter.loads() 解析後的物件。

    Returns:
        清掉 post.content 中錯位 frontmatter 後原位取代的 post 物件
    """
    lines_to_be_deleted = []
    for line in post.content.splitlines():
        # 真正的標題行 = '#' 後接空白或再一個 '#'；'#python' 這種行內標籤不算，不會誤停
        if line.startswith("#") and (len(line) == 1 or line[1] in " #"):
            break
        lines_to_be_deleted.append(line)

    text_to_be_deleted = "\n".join(lines_to_be_deleted)
    post.content = post.content.replace(text_to_be_deleted, "")

    return None


def _upload_clean_md(bucket: Bucket, src_name: str, dest_name: str, clean_frontmatter: dict) -> str:
    """下載 raw .md、把清洗後的 frontmatter 覆寫回內文，再上傳到 archived-notes/，回傳 archived 端 md5。

    不同於 _copy_blob 直接原樣複製，這裡把 Transform 階段算好的 clean_frontmatter 覆寫進 metadata，
    確保歸檔的 .md 不再帶著誤植或雜亂的原始 frontmatter。採覆蓋語意，目的已存在就覆寫；
    上傳後若回應沒帶 md5，就重新載入一次 metadata 再取。

    Args:
        bucket: 來源與目的所在的 GCS Bucket 物件。
        src_name: gs://<bucket>/raw-notes/ 下的來源 .md blob 名稱。
        dest_name: gs://<bucket>/archived-notes/ 下的目的 .md blob 名稱。
        clean_frontmatter: 要覆寫進 frontmatter 的清洗後欄位，即 note_doc 的 archived_md_frontmatter。

    Returns:
        目的 blob 的 md5 字串。
    """
    text = bucket.blob(src_name).download_as_text(encoding="utf-8")
    post = frontmatter.loads(text)
    post.metadata.update(clean_frontmatter)
    _delete_misposition_metadata(post)
    new_text = frontmatter.dumps(post)

    dest_blob = bucket.blob(dest_name)
    dest_blob.upload_from_string(new_text, content_type="text/markdown")
    if dest_blob.md5_hash is None:
        dest_blob.reload()
    return dest_blob.md5_hash


def blob_name_from_uri(uri: str, bucket_name: str) -> str:
    """從 gs://bucket/xxx 這樣的完整 URI 取回 blob 名稱 xxx，即拼 URI 的反向操作。

    有帶 gs://<bucket>/ 前綴時才去掉前綴，否則原樣回傳。

    Args:
        uri: GCS 的完整 gs:// URI，或已是 blob 名稱。
        bucket_name: 要剝除的 bucket 名稱。

    Returns:
        blob 名稱字串，供 copy_blob 等操作使用。
    """
    prefix = f"gs://{bucket_name}/"
    return uri[len(prefix) :] if uri.startswith(prefix) else uri


def archive_note(note_doc: dict, bucket: Bucket, bucket_name: str = "personal-vaults") -> dict:
    """把清洗後的 .md 與其引用圖片複製到 archived-notes/，並把 archived 端資訊回填進 note_doc。

    1. 依 raw_md_path 算出 archived 端的 .md 名稱，覆寫上清洗後的 frontmatter 再上傳並取回 archived md5。
    2. 逐一把 attached_images 的每張圖複製到對應的 archived _attachment/，回填該圖 archived 端的路徑與 md5。
    3. 補上 note_doc 的 archived_md_path、archived_md_md5_hash、archived_at，並把 error_msg 清空。

    整段採覆蓋語意，重跑同一版本結果一致。任一次複製失敗時，先把錯誤訊息寫進 note_doc["error_msg"]，
    再把例外往外拋，由呼叫端決定要略過還是落地記錄。

    Args:
        note_doc: 待歸檔的 note document，需含 raw_md_path 與 attached_images 的 raw 部分。
        bucket: 來源與目的所在的 GCS Bucket 物件。
        bucket_name: bucket 名稱，用來組 archived 端的 gs:// 路徑，預設 "personal-vaults"。

    Returns:
        補上 archived_* 欄位的同一個 note_doc。
    """
    now = datetime.now(timezone.utc)
    try:
        # archive .md 檔到 archived-notes/ 下，並帶上清洗後的 frontmatter
        raw_md_name = blob_name_from_uri(note_doc["raw_md_path"], bucket_name)
        archived_md_name = _archived_name(raw_md_name)
        archived_md5 = _upload_clean_md(bucket, raw_md_name, archived_md_name, note_doc["archived_md_frontmatter"])

        # archive images 到 archived-notes/ 下
        for img in note_doc.get("attached_images", []):
            raw_img_name = img["raw_image_path"]
            archived_img_name = _archived_name(raw_img_name)
            # 組裝最後需要的欄位
            img["archived_image_md5"] = _copy_blob(bucket, raw_img_name, archived_img_name)
            img["archived_image_path"] = f"gs://{bucket_name}/{archived_img_name}"

        note_doc["archived_md_path"] = f"gs://{bucket_name}/{archived_md_name}"
        note_doc["archived_md_md5_hash"] = archived_md5
        note_doc["archived_at"] = now
        note_doc["error_msg"] = ""
        logger.info(f"md與其附件均歸檔完成：{Path(archived_md_name).name}")
        return note_doc
    except Exception as e:
        note_doc["error_msg"] = f"{archived_md_name} 歸檔失敗：{e}"
        raise
