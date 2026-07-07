"""把 CDC 挑中的 raw .md 內文清洗成 obsidian_note_metadata 的 note 文件（raw 部分）。

解析 frontmatter（缺則正文頂端補救）→ 推導 note_type/topic/date/word_count →
解析 ![[ ]] 圖片血緣 → 組出含 raw 欄位與內嵌 attached_images（raw 部分）的 dict。

清洗與圖片解析函式沿用 task01_obsidian_etl（copy 而非 import，讓 v1/v2 可獨立演化做對照）；
archived_* 欄位、status、embedded_status、時間戳由 Load 層歸檔後補；
未來若插入 LLM enrichment，掛載順序點見 build_note_document 內標註。
"""

import re
from datetime import date, datetime, time, timezone
from pathlib import Path

import frontmatter
from google.cloud.storage import Blob
from loguru import logger

from .e_scan_obsidian import FOLDER_TYPE_MAP, parse_note_path

# 追蹤的主題關鍵字，key 順序有意義（越前面越優先匹配），供 Streamlit 畫雷達圖
TOPIC_KEYWORDS = {
    "python": ["python", "pandas", "numpy", "poetry", "flask", "streamlit"],
    "database": ["sql", "mysql", "mongodb", "redis", "distribution-architecture"],
    "gcp": ["google-cloud-platform", "gcs", "bigquery", "vm", "compute-engine", "cloud-run"],
    "data-warehouse": ["hive", "bigquery"],
    "etl": ["etl", "elt", "pipeline", "airflow", "dbt"],
    "ml": ["machine learning", "ml", "sklearn", "model"],
    "dockerize": ["docker", "container", "image", "dockerfile", "docker-compose"],
    "github": ["git", "github", "github-actions"],
    "linux": ["os", "linux", "linux-command"],
    "biotech": [
        "biotech",
        "bioreactor",
        "gmp",
        "technology-transfer",
        "biopharma",
        "ALCOA+",
        "perfusion",
        "cell-culture",
        "upstream",
    ],
}

# markdown 中的 image 採用 wiki-link 語法
_IMAGE_EMBED_PATTERN = re.compile(r"!\[\[([^\]]+)\]\]")


def _resolve_image_blob_path(image_ref: str, note_blob_name: str) -> str:
    """把 .md 內文裡的 Obsidian 圖片嵌入檔名，解析成該圖片在 GCS 的 blob 路徑。

    1. 取這份 .md 所在的目錄。
    2. 從嵌入語法去掉尺寸與別名，只留下純檔名。
    3. 依 vault 慣例，圖片放在該 .md 目錄底下的 _attachment/，把目錄與檔名拼成 blob 路徑。

    因為以各筆記自己的目錄解析，不同資料夾底下的同名圖片不會互相衝突。

    Args:
        image_ref: ![[ ]] 內的圖片參照字串，可能帶尺寸或別名。
        note_blob_name: 這份 .md 的 blob 名稱，用來定位它的目錄。

    Returns:
        該圖片在 GCS 的 blob 路徑字串。
    """
    note_dir = Path(note_blob_name).parent
    base = Path(image_ref.split("|")[0].strip()).name  # 去掉 ![[name.png|492]] 的尺寸/別名後取檔名
    return f"{note_dir}/_attachment/{base}"


def _extract_attached_images(body: str, note_blob_name: str, image_md5_index: dict[str, str]) -> list[dict]:
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
        if blob_path in seen:
            continue
        seen.add(blob_path)
        md5 = image_md5_index.get(blob_path)
        if md5 is None:
            logger.warning(f"找不到圖片 blob，略過血緣記錄：{blob_path}")
            continue
        images.append({"raw_image_path": blob_path, "raw_image_md5": md5})
    return images


def _infer_note_type(md_file_path: Path, fm_data: dict) -> str:
    """判斷筆記的 note_type，優先看 frontmatter 的 type，其次用 section 資料夾前綴 fallback。

    1. 若 frontmatter 有寫 type，依關鍵字歸類成 daily-log、project 或 knowledge-summary。
    2. frontmatter 沒寫或無法歸類時，改看該 .md 上層資料夾名稱的前兩碼。
    3. 前兩碼對照 FOLDER_TYPE_MAP，對不到就回 unknown。

    Args:
        md_file_path: 這份 .md 的路徑，用來取上層資料夾前綴。
        fm_data: frontmatter 解析出的欄位字典。

    Returns:
        note_type 字串，為 daily-log、project、knowledge-summary 或 unknown 之一。
    """
    fm_type = fm_data.get("type", "")
    if fm_type:
        fm_type_lower = str(fm_type).lower()
        if "daily" in fm_type_lower or "log" in fm_type_lower:
            return "daily-log"
        elif "project" in fm_type_lower:
            return "project"
        elif "knowledge" in fm_type_lower or "summary" in fm_type_lower or "base" in fm_type_lower:
            return "knowledge-summary"

    folder_prefix = md_file_path.parent.name[:2]
    return FOLDER_TYPE_MAP.get(folder_prefix, "unknown")


def _infer_topic(tags: list[str], md_file_path: str) -> str:
    """從 tags 與檔名比對 TOPIC_KEYWORDS，推斷這份筆記的 topic。

    1. 把 tags 全部轉小寫，並補上檔名一起當作比對目標。
    2. 依 TOPIC_KEYWORDS 的鍵順序逐一比對，任一關鍵字命中就回該 topic。
    3. 全部比不到就回 other。

    鍵的順序代表優先權，越前面的 topic 越優先命中。

    Args:
        tags: 這份筆記的標籤清單。
        md_file_path: 這份 .md 的路徑，取其檔名一併參與比對。

    Returns:
        命中的 topic 字串，全不中時回 other。
    """
    file_name = Path(md_file_path).stem
    search_targets = [t.lower() for t in tags] + [file_name.lower()]
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if any(kw in target for target in search_targets):
                return topic
    return "other"


# def _infer_date(date_str: str | None):
#     """把 %Y-%m-%d 字串轉 datetime，缺值或非此格式回 None。"""
#     if not date_str or date_str == "None":
#         return None
#     try:
#         return datetime.strptime(date_str, "%Y-%m-%d")
#     except Exception as e:
#         logger.warning(f"筆記元數據日期轉換失敗，標記為 None，原因：{e}")
#         return None


def _infer_misposition_metadata(post: frontmatter.Post) -> dict[str, list | str]:
    """當 frontmatter 誤植到正文時的補救解析，掃正文頂端的 key: value 區塊把欄位撿回來。

    1. 逐行往下掃，一路把殘留的 --- 分隔線與前後空白清掉。
    2. 碰到第一個真正的 Markdown 標題行就停；行首的 # 後面要接空白或再一個 #，
       這樣行內標籤 #python 才不會被誤判成標題而提早截斷。
    3. 用 str.partition 只在第一個冒號切開 key 與 value，值裡若含冒號，例如時間 10:30 或網址，也不會被多切。
    4. 依 key 把值收進 tags、date、type、alias。

    Args:
        post: frontmatter.loads() 解析後的物件。

    Returns:
        補救到的 tags、date、type、alias 四欄字典。
    """
    fm: dict[str, list | str] = {"tags": [], "date": "", "type": "", "alias": []}
    for raw_line in post.content.splitlines():
        line = raw_line.strip().strip("-").strip()  # 容忍殘留的 '---' frontmatter 分隔線
        if not line:
            continue
        # 真正的標題行 = '#' 後接空白或再一個 '#'；'#python' 這種行內標籤不算，不會誤停
        if line.startswith("#") and (len(line) == 1 or line[1] in " #"):
            break

        if ":" in line:
            feat_key, _, fea_value = line.partition(":")
        elif "：" in line:
            feat_key, _, fea_value = line.partition("：")
        else:
            continue

        fea_value = fea_value.strip()
        if feat_key in ("tag", "tags") and fea_value:
            fm["tags"] = fea_value
        elif feat_key in ("date", "type") and fea_value:
            fm[feat_key] = fea_value
        elif feat_key in ("alias", "aliases") and fea_value:
            fm["alias"] = fea_value
    return fm


def _normalize_str_list(value) -> list[str]:
    """把 frontmatter 的 tags 或 alias 正規化成 list[str]，容忍逗號分隔字串或既有 list。

    1. 已是 list 時，逐項轉字串去空白，並濾掉空項。
    2. 是字串時，去掉方括號後以逗號切開，同樣去空白並濾掉空項。
    3. 其餘型別，例如 None，一律回空 list。

    Args:
        value: frontmatter 的 tags 或 alias 原始值，型別不定。

    Returns:
        正規化後的字串清單。
    """
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [t.strip() for t in value.replace("[", "").replace("]", "").split(",") if t.strip()]
    return []


def _normalize_date(value) -> datetime | None:
    """把 frontmatter 的 date 正規化成 BSON 可編碼的 UTC datetime，無法解析時回 None。

    1. 已是 datetime 就直接回。
    2. 是 datetime.date 時補上 UTC 午夜時間轉成 datetime。
    3. 是非空字串時，依序試 %Y-%m-%d、%Y/%m/%d、%Y_%m_%d 幾種格式，成功即回帶 UTC 時區的 datetime。
    4. 都不符合就回 None。

    Args:
        value: frontmatter 的 date 原始值，型別不定。

    Returns:
        帶 UTC 時區的 datetime，或無法解析時的 None。
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):  # 純 date 沒有時間，補 UTC 午夜再轉 datetime
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y_%m_%d"):
            try:
                return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _extract_frontmatter(post: frontmatter.Post, md_file_path: str) -> dict:
    """組出要內嵌進 obsidian_note_metadata 的 md_frontmatter，含 tags、date、type、alias 四欄。

    1. 先讀 frontmatter 的 metadata 區。
    2. 若 metadata 區是空的，改用 _infer_misposition_metadata 掃正文頂端補救。
    3. 分別把 tags 與 alias 正規化成字串清單、date 正規化成 UTC datetime、type 交給 _infer_note_type 判斷。

    Args:
        post: frontmatter.loads() 解析後的物件。
        md_file_path: 這份 .md 的 blob 名稱，供 type fallback 判斷 section 前綴。

    Returns:
        含 tags、date、type、alias 四鍵的字典，作為 md_frontmatter 的值。
    """
    fm = post.metadata
    if not fm:
        fm = _infer_misposition_metadata(post)
    return {
        "tags": _normalize_str_list(fm.get("tags", [])),
        "date": _normalize_date(fm.get("date")),
        "type": _infer_note_type(Path(md_file_path), fm),
        "alias": _normalize_str_list(fm.get("alias", [])),
    }


def build_note_document(blob: Blob, text: str, bucket_name: str, image_md5_index: dict[str, str]) -> dict:
    """把單份 raw .md 的內文清洗成可插入 obsidian_note_metadata 的 document，不含 archived_* 與狀態欄位。

    1. 解析 frontmatter 並組出內嵌的 md_frontmatter。
    2. 從 tags 與檔名推斷 topic。
    3. 從 blob 名稱拆出 note_user_id、notebook、section、file_name。
    4. 補上 raw_md_path、raw 端 md5 與更新時間、字數，以及解析出的 attached_images 血緣。

    archived_* 欄位、status、embedded_status 與時間戳由 Load 歸檔後補；
    未來若要插入 LLM enrichment，掛載點見函式內註解。

    Args:
        blob: 這份 raw .md 的 GCS blob，提供名稱、md5 與更新時間。
        text: 已下載的 .md 內文。
        bucket_name: raw-notes/ 所在的 GCS bucket 名稱。
        image_md5_index: GCS 現況的圖片路徑對 md5 字典，供圖片血緣查 md5。

    Returns:
        一份 note document 字典，供 Load 歸檔並 upsert。
    """
    post = frontmatter.loads(text)
    md_file_path = blob.name
    md_frontmatter = _extract_frontmatter(post, md_file_path)
    topic = _infer_topic(md_frontmatter["tags"], md_file_path)

    # --- 未來 LLM document enrichment 掛載點 ---
    # 若日後要在此插入多模態 enrichment，於此處對 post.content 做生成，
    # 並斟酌把 _infer_* 、_extract_frontmatter 清洗步驟挪到生成之後。

    path_parts = parse_note_path(md_file_path)

    return {
        **path_parts,  # note_user_id / notebook / section / file_name
        "raw_md_path": f"gs://{bucket_name}/{md_file_path}",
        "raw_md_md5_hash": blob.md5_hash,
        "raw_md_updated_at": blob.updated,
        "topic": topic,
        "word_count": len(post.content.split()),
        "archived_md_frontmatter": md_frontmatter,
        "attached_images": _extract_attached_images(post.content, md_file_path, image_md5_index),
    }
