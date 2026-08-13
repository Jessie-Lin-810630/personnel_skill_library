"""掃描 GCS Bronze 層 gs://<bucket>/raw-notes、以 md5 做 CDC gate，只挑出新增/變更的 .md 供下載。

1. 列出 gs://<bucket>/raw-notes/ 下的 .md 與 _attachment 圖片並取 md5。
2. 從 MongoDB 撈既有 md5 map。
3. 以既有 md5 map 為基準，比對挑出現在 GCS 上屬於新增/變更的 blob 有哪些，最後回傳清單。

db 由頂層 `main.py` 傳入，不是這層資料夾的 `main.py` 傳入。
本檔同時定義 silver/gold 共用的 GCS 前綴與 collection 常數，供同層其他 t_/l_ 模組 import。

Required .env keys:
    GCS_USER_CREDENTIALS             (On-premise only) GCS service account JSON path (list / download blobs).
    MONGO_ALTAS_URI                  MongoDB Atlas connection string (read existing md5 map).
    MONGO_DB_NAME                    Target database name.
"""

from pathlib import Path

from google.cloud import storage
from google.cloud.storage import Blob
from loguru import logger
from pymongo.database import Database

# Bronze layer GCS gs://<bucket>/ 的 blob 前綴
RAW_PREFIX = "raw-notes/"

# Gold layer GCS 前綴
ARCHIVED_PREFIX = "archived-notes/"

# gs://<bucket>/raw-notes/ 下方需要搜索以下 subfolders 來執行 Silver & Gold tasks
# key 為 subfolder 前綴關鍵字，value 為 subfolder 下的檔案歸類在哪個 note type
FOLDER_TYPE_MAP = {
    "01": "daily-log",
    "02": "knowledge-summary",
    "04": "project",
}

# 搜索 gs://<bucket>/raw-notes/ 下方的 subfolders 的時候，鎖定以下檔案為合法圖檔。
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# CDC gate 做判斷前需要的參考點從以下 collection 取
NOTE_METADATA = "obsidian_note_metadata"


def list_raw_blobs(bucket_name: str = "personal-vaults") -> tuple[list, dict[str, str]]:
    """掃描 raw-notes/ 下 FOLDER_TYPE_MAP 鎖定的資料夾，一次收齊待處理的 .md 與圖片 md5。

    1. 列出 raw-notes/ 前綴下的所有 blob。
    2. 副檔名為 .md，且上層資料夾名稱前兩碼落在 FOLDER_TYPE_MAP 內者，收進待處理清單。
    3. 副檔名屬於合法圖檔者，把 blob 名稱對應到它的 md5，收進圖片索引。

    Note:
        列出 blob 時回傳的物件已帶有 md5，不需再下載內容即可比對，因此整趟掃描不產生下載流量。

    Args:
        bucket_name: raw-notes/ 所在的 GCS bucket 名稱，預設 personal-vaults。

    Returns:
        待處理 .md 的 blob 物件清單，與圖片 blob 名稱對到其 md5 的字典，兩者組成 tuple。
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
    """從 obsidian_note_metadata 撈回每份筆記已記錄的 md5，供 select_changed_blobs 比對。

    1. 一次查回每份筆記的 raw_md_path、raw_md_md5_hash 與內嵌的 attached_images。
    2. 把 attached_images 收斂成圖片路徑對圖片 md5 的字典。
    3. 以 raw_md_path 為鍵，值放這份筆記本身的 md5 與上一步的圖片字典。

    Note:
        連圖片 md5 一起撈，是為了偵測 .md 內容沒變、但它引用的圖片被換掉或刪掉這種情況。
        這支函式只讀 MongoDB 供挑檔判斷、不寫入任何 collection，因此依資料本體的流向歸在 Extract。

    Args:
        db: pymongo Database 物件。

    Returns:
        以 raw_md_path 為鍵的字典，值含 md_md5 與 images 兩個欄位，
        後者是該筆記引用的圖片路徑對其 md5 的字典。
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
    """比對 GCS 現況與 MongoDB 已記錄的 md5，挑出需要重新下載清洗的 .md。

    逐一檢查每份 .md，命中以下任一情況就納入待處理清單：
    1. 新增：MongoDB 找不到這份筆記的 raw_md_path。
    2. 內容變更：這份 .md 的 md5 與 MongoDB 記錄的不同。
    3. 圖片變更：.md 內容沒變，但它引用的圖片 md5 被換掉，或該圖已從 GCS 消失。

    Note:
        第三種情況同樣要重跑，才能刷新 attached_images 與 archived-notes/ 下的圖片副本，
        否則歸檔的內容會停留在舊圖。
        另外 blob 名稱不帶 gs 協定前綴、raw_md_path 帶，因此比對前先補上前綴；
        補上後仍對不上就一律視為新增，寧可多跑一次也不漏檔。

    Args:
        md_blobs: raw-notes/ 下所有目標 .md 的 blob 物件清單。
        existing_md5_map: get_existing_md5_map 的回傳值，以 raw_md_path 為鍵、值含 md_md5 與 images。
        image_md5_index: GCS 現況的圖片路徑對 md5 字典，來自 list_raw_blobs。
        bucket_name: raw-notes/ 所在的 GCS bucket 名稱，預設 personal-vaults。

    Returns:
        本次需要下載清洗的 .md blob 物件清單。
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
