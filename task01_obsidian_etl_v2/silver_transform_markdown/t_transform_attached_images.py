"""把單份 raw .md 內文裡的 ![[ ]] 圖片語法解析成 GCS 路徑並帶著 md5，作爲 attached_images 的內嵌欄位值。

1. 正則掃出所有 wiki-link 圖片嵌入部分。
2. 去掉 wiki-link，解析成該圖在 _attachment/ 下的 blob 路徑。
3. 去重、查 md5。
4. 組出 [{raw_image_path, raw_image_md5}, ...]這是 attached_images 的一部分內嵌欄位的值。

Required .env keys:
    (無；純資料轉換，圖片 md5 由呼叫端傳入的 image_md5_index 提供。)
"""

import re
from pathlib import Path

from loguru import logger

# markdown 中的 image 採用 wiki-link 語法
_IMAGE_EMBED_PATTERN = re.compile(r"!\[\[([^\]]+)\]\]")


def _resolve_image_blob_path(image_ref: str, note_blob_name: str) -> str:
    """把 .md 內文裡的 Obsidian 圖片嵌入檔名，解析成該圖片在 GCS 的 blob 路徑。

    1. 取這份 .md 所在的目錄。
    2. 從嵌入語法去掉尺寸與別名，只留下純檔名。
    3. 依 vault 慣例，圖片放在該 `<.md 目錄>/_attachment/` 下，把目錄與檔名拼成 blob 路徑。

    因為筆記的上層目錄與筆記圖片的上上層目錄是同一個資料夾，故不同資料夾之間若有同名圖片，
    解析出來的 blob 路徑仍不會互相衝突。

    Args:
        image_ref: ![[ ]] 內的圖片參照字串，可能帶尺寸或別名。
        note_blob_name: 這份 .md 的 blob 名稱，函式會萃取它的上層目錄作為 image_ref 的上上層目錄。

    Returns:
        該圖片在 GCS 的 blob 路徑字串。
        例如: `04-projects/_attachment/an_img_cited_by_md.png`
    """
    note_dir = Path(note_blob_name).parent
    base = Path(image_ref.split("|")[0].strip()).name  # 去掉 ![[name.png|492]] 的尺寸/別名後取檔名
    return f"{note_dir}/_attachment/{base}"


def extract_attached_images(body: str, note_blob_name: str, image_md5_index: dict[str, str]) -> list[dict]:
    """從 .md body 抽出所有 ![[圖片]]，解析成 raw GCS 路徑並帶上 md5，作為單表內嵌的 attachment 血緣。

    1. 逐一掃出內文中的圖片嵌入語法，解析成該圖的 GCS blob 路徑。
    2. 同一份筆記重複引用同一張圖時只記一次，並保留首次出現的順序。
    3. 到 image_md5_index 查該圖的 md5，查得到才收錄，查不到就記 warning 後略過。

    每筆只先填 raw 端的路徑與 md5，archived 端的欄位等 Load 歸檔後再回填。

    Args:
        body: 一份 .md 去除 frontmatter 後的內文。
        note_blob_name: 這份 .md 的 blob 名稱，供圖片路徑解析。
        image_md5_index: GCS 現況的圖片路徑對 md5 字典，來自 list_raw_blobs。

    Returns:
        list，每筆是含 raw_image_path 與 raw_image_md5 的字典，依出現順序且已去重。
    """
    images = []
    seen = set()
    for m in _IMAGE_EMBED_PATTERN.finditer(body):
        blob_path = _resolve_image_blob_path(m.group(1), note_blob_name)
        # 同一個 folder 下可能有多份筆記引用同張圖片，
        # 用 set 裝'解析過的圖片路徑'，能減少迴圈下輪的 Time complexity
        if blob_path in seen:
            continue
        seen.add(blob_path)
        md5 = image_md5_index.get(blob_path)
        if md5 is None:
            logger.warning(f"找不到圖片 blob，略過血緣記錄：{blob_path}")
            continue
        images.append({"raw_image_path": blob_path, "raw_image_md5": md5})
    return images
