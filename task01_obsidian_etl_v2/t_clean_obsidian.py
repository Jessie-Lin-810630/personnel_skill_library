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
    """把 .md 內的 Obsidian 圖片嵌入檔名解析成 GCS blob 路徑。

    圖片放在「該 .md 所在目錄」底下的 _attachment/ 子資料夾，以 note 自己的目錄解析，
    天然避開不同資料夾 _attachment/ 內同名 .png 的衝突。
    """
    note_dir = Path(note_blob_name).parent
    base = Path(image_ref.split("|")[0].strip()).name  # 去掉 ![[name.png|492]] 的尺寸/別名後取檔名
    return f"{note_dir}/_attachment/{base}"


def _extract_attached_images(body: str, note_blob_name: str, image_md5_index: dict[str, str]) -> list[dict]:
    """從 .md body 抽出所有 ![[圖片]]，解析成 raw GCS 路徑並帶 md5，作為單表內嵌的 attachment 血緣。

    回傳 [{"raw_image_path": blob_path, "raw_image_md5": md5}, ...]（依出現順序、去重）。
    archived 端欄位待 Load 歸檔後回填；GCS 上找不到的圖片略過並記 warning。
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
    """優先用 frontmatter type，fallback 用 section 資料夾前兩碼判斷。"""
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
    """從 tags 比對 TOPIC_KEYWORDS，找不到再用檔名比對，完全不中回 'other'。"""
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
    """當 frontmatter 漏寫進正文時的補救解析：掃描正文「頂端」的 key: value 區塊。

    逐行掃描，碰到第一個真正的 markdown 標題行 (行首 '# '、'## '…) 才停，
    避免行內標籤 (#python) 被誤判成標題而截斷。
    用 str.partition 以控制回傳值只有三段，且在第一個冒號切開 key & value，
    以免 value 內有含冒號 (時間 10:30、URL) 而多切。

    Args:
        post (frontmatter.Post): frontmatter.loads() 解析後的物件。

    Returns:
        dict[str, list | str]: 最終，補救到的 tags / date / type / alias。
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
    """把 frontmatter 的 tags/alias 正規化為 list[str] (容忍逗號分隔字串或既有 list)。"""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [t.strip() for t in value.replace("[", "").replace("]", "").split(",") if t.strip()]
    return []


def _normalize_date(value) -> datetime | None:
    """把 frontmatter 的 date 正規化為 BSON 可編碼的 UTC datetime；無法解析回 None。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):  # datetime.date (非 datetime) → 補 UTC 午夜
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y_%m_%d"):
            try:
                return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _extract_frontmatter(post: frontmatter.Post, md_file_path: str) -> dict:
    """讀 md，組出內嵌 Object md_frontmatter (4 個 frontmatter 欄)。

    frontmatter 未寫進 metadata 區時以正文頂端補救解析，

    Args:
        post (frontmatter.Post): frontmatter.loads() 解析後的物件。
        md_file_path (str): 該 .md 的 blob.name，供 _infer_note_type fallback 判斷 section 前綴。

    Returns:
        dict: {tags, date, type, alias}，供作 Collection obsidian_note_metadata 的 md_frontmatter 值。
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
    """把單份 raw .md 的內文清洗成可插入 MongoDB 的 document (不含 archived_* 與狀態欄位)。

    blob 提供 name/md5_hash/updated；text 為已下載的內文；image_md5_index 供圖片血緣查 md5。
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
