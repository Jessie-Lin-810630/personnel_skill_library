import re
from pathlib import Path

import frontmatter  # 原本就有
from google.cloud import storage
from loguru import logger

"""
程式架構：
    使用scan_vault() 掃描 Obsidian vault，過程中，
    呼叫_infer_note_type() 與 _infer_topic() 解析每份 .md 的 frontmatter 與基本 metadata。
    最後scan_vault() 回傳 list[dict]。
"""

# vault 三個資料夾前綴，key 為資料夾名稱、value 為 obsidian frontmatter type 的值
FOLDER_TYPE_MAP = {
    "01": "daily-log",
    "02": "knowledge-summary",
    "04": "project",
}

# 設定想追蹤的主題關鍵字，key 為主題，value負責與 .md yaml內的tags清單做比對。
# 會當作之後 Streamlit 畫雷達圖的軸
# 注意，key的順序有意義，越前面優先匹配，所以可以根據想凸顯哪個分類的importance來放置key
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

# 圖片副檔名與 Obsidian 圖片嵌入語法 ![[xxx.png]]
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
_IMAGE_EMBED_PATTERN = re.compile(r"!\[\[([^\]]+)\]\]")


def resolve_image_blob_path(image_ref: str, note_blob_name: str) -> str:
    """把 .md 內的 Obsidian 圖片嵌入檔名解析成 GCS blob 路徑 (跨 task 共用的「權威」解析規則)。

    依 vault 在 GCS 的儲存結構：圖片放在「該 .md 所在目錄」底下的 _attachment/ 子資料夾。
      例：note = lucky460721/from-obsidian/01-daily-logs/x.md，圖片 ref = img.png
          → lucky460721/from-obsidian/01-daily-logs/_attachment/img.png
    以 note 自己的目錄解析，天然避開不同資料夾 _attachment/ 內同名 .png 的衝突。

    註：task06 包圖片向量化時 copy 同一套規則 (決策：copy 而非 import，改規則時兩邊要同步)。
    """
    note_dir = Path(note_blob_name).parent
    base = Path(image_ref.split("|")[0].strip()).name  # 去掉 ![[name.png|492]] 的尺寸/別名後取檔名
    return f"{note_dir}/_attachment/{base}"


def extract_attached_images(body: str, note_blob_name: str, image_md5_index: dict[str, str]) -> list[dict]:
    """從 .md body 抽出所有 ![[圖片]]，解析成 GCS blob 路徑並帶上該圖的 md5，供 obsidian_notes 做資料血緣。

    回傳 [{"image_path": blob_path, "image_md5_hash": md5}, ...] (依出現順序、去重)。
    GCS 上找不到的圖片略過並記 warning (例如圖已刪、或路徑非 _attachment/ 結構)。
    """
    images = []
    seen = set()
    for m in _IMAGE_EMBED_PATTERN.finditer(body):
        blob_path = resolve_image_blob_path(m.group(1), note_blob_name)
        if blob_path in seen:
            continue
        seen.add(blob_path)
        md5 = image_md5_index.get(blob_path)
        if md5 is None:
            logger.warning(f"找不到圖片 blob，略過血緣記錄：{blob_path}")
            continue
        images.append({"image_path": blob_path, "image_md5_hash": md5})
    return images


def _infer_note_type(md_file_path: Path, fm_data: dict) -> str:
    """優先用 frontmatter types，fallback 用資料夾前綴判斷"""
    fm_type = fm_data.get("type", "")
    if fm_type:
        # 統一成我們定義的三種 type 字串
        fm_type_lower = str(fm_type).lower()
        if "daily" in fm_type_lower or "log" in fm_type_lower:
            return "daily-log"
        elif "project" in fm_type_lower:
            return "project"
        elif "knowledge" in fm_type_lower or "summary" in fm_type_lower or "base" in fm_type_lower:
            return "knowledge-summary"

    # fallback: 看上層資料夾名稱的前兩碼字
    folder_prefix = md_file_path.parent.name[:2]
    return FOLDER_TYPE_MAP.get(folder_prefix, "unknown")


def _infer_topic(tags: list[str], file_name: str) -> str:
    """從 tags 清單比對 TOPIC_KEYWORDS，找不到再用檔名比對。

    回傳第一個匹配的 topic key，完全比對不到回傳 'other'。
    """
    search_targets = [t.lower() for t in tags] + [file_name.lower()]

    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if any(kw in target for target in search_targets):
                return topic

    return "other"


def scan_vault(vault_path: str) -> list[dict]:
    """遞迴掃描 vault 底下所有 .md 檔。

    回傳每筆筆記的 metadata dict。
    """
    # 檢查路徑是否存在
    vault = Path(vault_path)
    if not vault.exists():
        raise FileNotFoundError(f"Vault 路徑不存在：{vault_path}")

    # 查詢該路徑下所有 .md 檔，但踢除不在 FOLDER_TYPE_MAP 搜索範圍內的.md檔
    all_md_files = vault.rglob("*.md")
    md_files: list[Path] = []
    for f in all_md_files:
        if f.parent.name[0:2] not in FOLDER_TYPE_MAP.keys():
            continue
        md_files.append(f)

    logger.info(f"共發現{len(md_files)}份 .md 檔，開始解析...")

    results = []
    for md_file in md_files:  # md_file is a Path object.
        try:
            post = frontmatter.load(str(md_file))  # open .md file & parsing the filename
            fm = post.metadata  # frontmatter dict

            tags_raw = fm.get("tags", [])
            # tags 可能是 list 或逗號分隔字串，統一轉成 list
            # 通常我自己是用list表示tags，這裡只是寫個預防偶發意外搞錯 yaml 寫法。
            if isinstance(tags_raw, str):
                tags = [t.strip() for t in tags_raw.split(",")]
            else:
                tags = [str(t).strip() for t in tags_raw]

            note_type = _infer_note_type(md_file, fm)
            topic = _infer_topic(tags, md_file.stem)  # .stem取得檔名 (不含檔型 .md) 的字串

            doc = {
                "file_name": md_file.name,  # .name取得檔名 (含檔型 .md) 的字串
                "file_path": str(md_file),
                "note_type": note_type,
                "tags": tags,
                "alias": fm.get("alias", fm.get("aliases", "")),
                "date": str(fm.get("date", "")),
                "topic": topic,
                "word_count": len(post.content.split()),  # 不一定會切成單詞，可能是仍然是句子
            }
            results.append(doc)

        except Exception as e:
            # 單一檔案解析失敗不中斷整體流程
            logger.warning(f"解析失敗：{md_file.name} | 原因：{e}")

    logger.info(f"解析完成，成功 {len(results)} 筆")
    return results


def scan_vault_gs(bucket_name: str = "personal-vaults") -> list[dict]:
    """從 GCS bucket 掃描所有 .md 檔。

    回傳每筆筆記的 metadata dict。
    """
    client = storage.Client()

    # 列出 bucket 內所有 blob (list_blobs 回傳的 blob 即帶 md5_hash 等 metadata，不需下載內容)
    all_blobs = client.list_blobs(bucket_name)

    # 一次掃描同時收集：
    #   1. md_blobs：目標 .md (上層資料夾前綴在 FOLDER_TYPE_MAP 內)
    #   2. image_md5_index：{圖片 blob 路徑: md5_hash}，供 attached_images 查圖片 md5 (資料血緣)
    md_blobs = []
    image_md5_index = {}
    for blob in all_blobs:
        if blob.name.endswith(".md"):
            folder_prefix = Path(blob.name).parent.name[:2]  # 取 "01"、"02"、"04"
            if folder_prefix in FOLDER_TYPE_MAP.keys():
                md_blobs.append(blob)
        elif Path(blob.name).suffix.lower() in _IMAGE_EXTENSIONS:
            image_md5_index[blob.name] = blob.md5_hash

    logger.info(f"共發現 {len(md_blobs)} 份 .md 檔、{len(image_md5_index)} 張圖片，開始解析...")

    results = []
    for blob in md_blobs:
        try:
            # 原本寫法：從 GCS 下載成 bytes，用 io.BytesIO 餵給 frontmatter
            # content_bytes = blob.download_as_bytes() # 回傳 bytes 格式
            # post = frontmatter.load(io.BytesIO(content_bytes)) # load() 接受 file-like object
            # 上2行：bytes格式轉BaseIO物件，餵給load()，從 load() 原始碼可知它會判斷BaseIO物件有method .read()
            # 因而跳過decoding，直接執行BaseIO物件.read()，此路線造成傳遞到下個loads() 程序的是 bytes ，
            # 但loads() 只能吃string，無法處理bytes
            # 所以報錯：'cannot use a string pattern on a bytes-like object'
            # 修正方式之一是，轉成BaseIO物件後，'先decoding'，才傳給load():
            # content_str = blob.download_as_bytes().decode("utf-8")  # bytes轉str
            # post = frontmatter.load(io.BytesIO(content_str))

            # 修正方式之二，直接改用 download_as_text() 就可以直接接 loads()
            content_str = blob.download_as_text(encoding="utf-8")  # 回傳字串而不是bytes
            post = frontmatter.loads(content_str)  # loads() 接受字串
            fm = post.metadata

            # 以下邏輯與 scan_vault() 完全相同
            # tags 可能是 list 或逗號分隔字串，統一轉成 list
            # 通常我自己是用list表示tags，這裡只是寫個預防偶發意外搞錯 yaml 寫法。
            tags_raw = fm.get("tags", [])
            if isinstance(tags_raw, str):
                tags = [t.strip() for t in tags_raw.split(",")]
            else:
                tags = [str(t).strip() for t in tags_raw]

            # _infer_note_type 需要 Path，用 blob.name 模擬
            md_file_path = Path(blob.name)
            note_type = _infer_note_type(md_file_path, fm)
            topic = _infer_topic(tags, md_file_path.stem)

            doc = {
                "file_name": md_file_path.name,
                "file_path": blob.name,  # GCS 路徑取代本地路徑
                "note_type": note_type,
                "tags": tags,
                "alias": fm.get("alias", fm.get("aliases", "")),
                "date": str(fm.get("date", "")),
                "topic": topic,
                "word_count": len(post.content.split()),
                # CDC 增量 embedding 用：該 .md 的內容 md5，與其引用圖片的血緣＋md5
                "file_md5_hash": blob.md5_hash,
                "attached_images": extract_attached_images(post.content, blob.name, image_md5_index),
            }
            results.append(doc)

        except Exception as e:
            # 單一檔案解析失敗不中斷整體流程
            logger.warning(f"解析失敗：{blob.name} | 原因：{e}")

    logger.info(f"解析完成，成功 {len(results)} 筆")
    return results
