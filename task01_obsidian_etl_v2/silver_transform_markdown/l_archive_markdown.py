"""把清洗後的 .md 與其引用圖片歸檔到 GCS Gold 層 archived-notes/，並回填 archived_* 欄位。

1. archive_note 依 raw_md_path 算 archived 名
2. 覆寫清洗後 frontmatter 上傳 .md、逐張 copy 圖片
3. 回填 archived_md_path/md5/archived_at；整段採覆蓋語意，重跑同版本結果一致。

Required .env keys:
    GCS_USER_CREDENTIALS   (On-premise only) GCS service account JSON path (copy / upload blobs).
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
    """在同一個 bucket 內把來源 blob 原樣複製到目的名稱。

    採覆寫語意，目的地已存在就直接蓋掉；複製後若回應沒帶 md5，就重新載入一次再取。

    Args:
        bucket: 來源與目的所在的 GCS Bucket 物件。
        src_name: 來源 blob 名稱。
        dest_name: 目的 blob 名稱。

    Returns:
        複製後那份副本的 md5 字串。
    """
    src_blob = bucket.blob(src_name)
    new_blob = bucket.copy_blob(src_blob, bucket, dest_name)
    if new_blob.md5_hash is None:
        new_blob.reload()
    return new_blob.md5_hash


def _delete_misposition_metadata(post: frontmatter.Post) -> None:
    """當 frontmatter 誤植到正文時的清掃，掃正文頂端的 key: value 區塊把欄位刪掉。

    1. 逐行往下掃，直到碰到第一個真正的 Markdown 標題行就停止。
    2. 把停止前的所有行接回一段文字，再從正文中以空字串取代掉。

    Note:
        判定標題行時要求 # 後面接空白或再一個 #，這樣行內標籤例如 #python 才不會被誤判成標題而提早截斷。
        取代採字串比對而非位置切除，因此那段文字若在正文後段原樣重複出現，也會一併被移除。

    Args:
        post: frontmatter.loads 解析後的物件，其 content 會被覆寫。

    Returns:
        None: 這是就地修改，清理結果直接寫回傳入的 post 物件，呼叫端取用 post.content 即可。
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
    """下載一份 .md、把清洗後的 frontmatter 覆寫回去，再上傳到 archived-notes/。

    不同於 _copy_blob 原樣複製，這裡會把 Transform 階段算好的 frontmatter 覆寫進去，
    因此歸檔後的 .md 不再帶著誤植或雜亂的原始 frontmatter。
    採覆寫語意，目的地已存在就直接蓋掉；上傳後若回應沒帶 md5，就重新載入一次再取。

    Args:
        bucket: 來源與目的所在的 GCS Bucket 物件。
        src_name: raw-notes/ 下的來源 .md blob 名稱。
        dest_name: archived-notes/ 下的目的 .md blob 名稱。
        clean_frontmatter: 要覆寫進去的清洗後欄位，即 note_doc 的 archived_md_frontmatter。

    Returns:
        歸檔副本的 md5 字串。
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
    """把清洗後的 .md 與其引用的圖片歸檔到 archived-notes/，並把歸檔結果寫回 note_doc。

    Markdown 與圖片的處理方式不同。Markdown 會先下載回來、覆寫上清洗過的 frontmatter 再上傳，
    所以歸檔後的內容與原始檔並不相同；圖片則是原樣複製，不做任何改寫。
    兩者都依 raw_md_path 推算出對應的歸檔路徑，目錄結構與原本一致。

    複製完成後，note_doc 會被補上歸檔路徑、歸檔副本的 md5 與歸檔時間，error_msg 則清成空字串，
    attached_images 的每張圖也會補齊各自歸檔後的路徑與 md5。
    整段採覆寫語意，目的地已存在就直接蓋掉，因此同一個版本重跑結果一致。

    Note:
        失敗時沒有交易性可言。GCS 上可能已寫入部分檔案，note_doc 也可能只補到一半，
        唯一能倚賴的是 error_msg 一定帶著失敗原因。因此呼叫端不該假設 note_doc 已完整，
        應改依 raw_md_path 整份重跑，或把這筆寫進資料庫存查。

    Args:
        note_doc: 待歸檔的 note document，需含 raw_md_path，以及 attached_images 內每張圖的
            raw_image_path 與 raw_image_md5。
        bucket: 來源與目的所在的 GCS Bucket 物件。
        bucket_name: bucket 名稱，用來組出歸檔後的完整路徑，預設 personal-vaults。

    Returns:
        補上歸檔欄位的 note_doc。這是就地修改，回傳的與傳入的是同一個物件。

    Raises:
        Exception: 上傳或複製過程中的任何例外，都會在寫入 error_msg 後原樣往外拋。
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
