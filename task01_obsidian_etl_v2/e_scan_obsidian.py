"""掃描 GCS Bronze 層 raw-notes、以 md5 做 CDC gate，只挑出新增/變更的 .md 供下載。

列出 raw-notes/ 下的 .md 與 _attachment 圖片並取 md5 → 從 MongoDB 撈既有 md5 map（CDC 輔助讀取）→
比對挑出新增/變更清單。get_existing_md5_map 雖讀 MongoDB，但回傳值只服務 GCS blob 的 ingestion 判斷、
不寫入任何 collection，故歸 Extract（e_）而非 Load（l_）。

Required .env keys:
    GOOGLE_APPLICATION_CREDENTIALS   GCS service account JSON path (list / download blobs).
    MONGO_ALTAS_URI                  MongoDB Atlas connection string (read existing md5 map).
    MONGO_DB_NAME                    Target database name (skill_dashboard).
"""

from pathlib import Path

from google.cloud import storage
from google.cloud.storage import Blob
from loguru import logger
from pymongo.database import Database

# Bronze layer GCS 前綴
RAW_PREFIX = "raw-notes/"

# Gold layer GCS 前綴
ARCHIVED_PREFIX = "archived-notes/"

# raw-notes/ 下方需要搜索以下 subfolders 來執行 Silver & Gold tasks
# key 為 subfolder 前綴關鍵字，value 為 subfolder 下的檔案歸類在哪個 note type
FOLDER_TYPE_MAP = {
    "01": "daily-log",
    "02": "knowledge-summary",
    "04": "project",
}

# 搜索 raw-notes/ 下方的 subfolders 的時候，鎖定以下檔案為合法圖檔。
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# CDC gate 做判斷前需要的參考點從以下 collection 取
NOTE_METADATA = "obsidian_note_metadata"


def parse_note_path(blob_name: str) -> dict[str, str]:
    """從 raw-notes/ blob.name 解析出 note_user_id / notebook / section / file_name。

    例：raw-notes/lucky460721/data-engineering/01-daily-logs/x.md
        → {note_user_id: lucky460721, notebook: data-engineering, section: 01-daily-logs, file_name: x.md}
    """
    rel = blob_name[len(RAW_PREFIX) :] if blob_name.startswith(RAW_PREFIX) else blob_name
    parts = Path(rel).parts
    return {
        "note_user_id": parts[0] if len(parts) > 0 else "",
        "notebook": parts[1] if len(parts) > 1 else "",
        "section": parts[-2] if len(parts) >= 2 else "",
        "file_name": parts[-1] if parts else "",
    }


def list_raw_blobs(bucket_name: str = "personal-vaults") -> tuple[list, dict[str, str]]:
    """對 raw-notes/ 下 FOLDER_TYPE_MAP 鎖定的資料夾，取出所有 .md blob 與 {圖片 blob.name: md5}。

    回傳 `(list of .md blob objects,
    dict of image_blob.name as key and image_blob.md5_hash as value)`.

    Args:
        bucket_name (str, optional): bucket name where raw-notes/ locates.
                                     Defaults to "personal-vaults".

    Returns:
        tuple[list, dict[str, str]]:
        - list: is the list of blob objects with `.md` suffix.
        - dict[str, stir] likes `{"raw-notes/nb/image01.png": "md5 hash of image file"}`

    """
    client = storage.Client()

    # 列出 bucket 內所有 blob (list_blobs 回傳的 blob 即帶 md5_hash 等 metadata，不需下載內容)
    all_blobs = client.list_blobs(bucket_name, prefix=RAW_PREFIX)

    # 一次掃描同時收集：
    # 1. md_blobs：目標 .md (特徵：它的上層資料夾名的最前面2個前綴字，落在 FOLDER_TYPE_MAP 內)
    # 2. image_md5_index：{圖片 blob 路徑: md5_hash}，供 attached_images 查圖片 md5 (資料血緣)
    md_blobs = []
    image_md5_index: dict[str, str] = {}
    for blob in all_blobs:
        if blob.name.endswith(".md"):
            folder_prefix = Path(blob.name).parent.name[:2]  # [:2]取出 "01"、"02"、"04"
            if folder_prefix in FOLDER_TYPE_MAP:
                md_blobs.append(blob)
        elif Path(blob.name).suffix.lower() in _IMAGE_EXTENSIONS:
            image_md5_index[blob.name] = blob.md5_hash

    logger.info(f"raw-notes 掃描出：{len(md_blobs)} 份 .md、{len(image_md5_index)} 張圖片")
    return md_blobs, image_md5_index


def get_existing_md5_map(db: Database) -> dict[str, dict]:
    """從 obsidian_note_metadata 撈回每筆 note 的 CDC 比對狀態，供 select_changed_blobs 判斷。

    除了 .md 本身的 md5，還撈其內嵌 attached_images 的 {raw_image_path: raw_image_md5}，
    用來偵測「.md 內文未變、但 wiki-link 指向的圖片 md5 變了（或圖片消失）」的情境。
    此為 GCS blob ingestion 的輔助讀取：回傳值僅用於挑出待下載的 blob，不寫回任何 collection，故歸 e_。

    Args:
        db (Database): Database object from pymongo

    Returns:
        dict[str, dict]: {raw_md_path: {"md_md5": raw_md_md5_hash,
                                        "images": {raw_image_path: raw_image_md5}}}
    """
    collection = db[NOTE_METADATA]
    existing_map: dict[str, dict] = {}
    with collection.find({}, {"raw_md_path": 1, "raw_md_md5_hash": 1, "attached_images": 1}) as cursor:
        for doc in cursor:
            images = {img.get("raw_image_path"): img.get("raw_image_md5") for img in doc.get("attached_images", [])}
            existing_map[doc["raw_md_path"]] = {
                "md_md5": doc.get("raw_md_md5_hash"),
                "images": images,
            }

    return existing_map


def select_changed_blobs(
    md_blobs: list[Blob],
    existing_md5_map: dict[str, dict],
    image_md5_index: dict[str, str],
    bucket_name: str = "personal-vaults",
) -> list[Blob]:
    """Change data capture：對比 GCS 現況與 DB 既有狀態，挑出需重新下載清洗的 .md blob。

    納入 changed 的三種情境：
      1. 新增：DB 無此 raw_md_path。
      2. .md 內文變更：raw_md md5 不同。
      3. .md 未變，但其 wiki-link 指向的圖片 md5 變了（換圖、檔名不變）或圖片已消失
         → 仍需重跑，以刷新 attached_images 血緣與 archived 端圖片。

    以 f"gs://{bucket}/{blob.name}" 為鍵對齊 DB 的 raw_md_path。
    未命中的話，不進入評估上述三情境。

    Args:
        md_blobs (list): .md objects under `gs://<bucket>/raw-notes/`.
        existing_md5_map (dict[str, dict]): {raw_md_path: {"md_md5":..., "images": {img_path: img_md5}}}.
        image_md5_index (dict[str, str]): GCS 現況 {圖片 blob.name: md5}，來自 list_raw_blobs。
        bucket_name (str, optional): bucket name where raw-notes/ locates. Defaults to "personal-vaults".

    Returns:
        list: list contains changed `.md` blobs.
    """
    changed_blobs = []
    for blob in md_blobs:
        gcs_md_path = f"gs://{bucket_name}/{blob.name}"
        existing = existing_md5_map.get(gcs_md_path)
        # 情境 1（新增）與情境 2（.md 內文變更）
        if existing is None or existing["md_md5"] != blob.md5_hash:
            changed_blobs.append(blob)
            continue
        # 情境 3：.md 未變，但引用圖片 md5 變動或消失（None != 舊 md5）
        if any(image_md5_index.get(img_path) != img_md5 for img_path, img_md5 in existing["images"].items()):
            changed_blobs.append(blob)
    logger.info(f"CDC gate 完成：共 {len(changed_blobs)}/{len(md_blobs)} 份需下載清洗。")
    return changed_blobs
