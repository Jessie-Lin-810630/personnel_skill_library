from dotenv import load_dotenv
import os
from pathlib import Path
from typing import Optional
import frontmatter
from loguru import logger


"""
程式架構：
    使用scan_vault() 掃描 Obsidian vault，過程中，
    呼叫_infer_note_type() 與 _infer_topic() 解析每份 .md 的 frontmatter 與基本 metadata。
    最後scan_vault() 回傳 list[dict]。
"""

# vault 三個資料夾前綴，key 為資料夾名稱、value 為 obsidian frontmatter type 的值
FOLDER_TYPE_MAP = {"01": "daily-log",
                   "02": "knowledge-summary",
                   "04": "project",
                   }

# 設定想追蹤的主題關鍵字，key 為主題，value負責與 .md yaml內的tags清單做比對。
# 會當作之後 Streamlit 畫雷達圖的軸
# 注意，key的順序有意義，越前面優先匹配，所以可以根據想凸顯哪個分類的importance來放置key
TOPIC_KEYWORDS = {"python": ["python", "pandas", "numpy", "poetry", "flask", "streamlit"],
                  "database": ["sql", "mysql", "mongodb", "redis", "distribution-architecture"],
                  "gcp": ["google-cloud-platform", "gcs", "bigquery",
                          "vm", "compute-engine", "cloud-run"],
                  "data-warehouse": ["hive", "bigquery"],
                  "etl": ["etl", "elt", "pipeline", "airflow", "dbt"],
                  "ml": ["machine learning", "ml", "sklearn", "model"],
                  "dockerize": ["docker", "container", "image", "dockerfile", "docker-compose"],
                  "github": ["git", "github", "github-actions"],
                  "linux": ["os", "linux", "linux-command"],
                  "biotech": ["biotech", "bioreactor", "gmp", "technology-transfer",
                              "biopharma", "ALCOA+", "perfusion", "cell-culture", "upstream"],
                  }


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
    """
    從 tags 清單比對 TOPIC_KEYWORDS，找不到再用檔名比對。
    回傳第一個匹配的 topic key，完全比對不到回傳 'other'。
    """
    search_targets = [t.lower() for t in tags] + [file_name.lower()]

    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if any(kw in target for target in search_targets):
                return topic

    return "other"


def scan_vault(vault_path: str) -> list[dict]:
    """
    遞迴掃描 vault 底下所有 .md 檔。
    回傳每筆筆記的 metadata dict。
    """

    # 檢查路徑是否存在
    vault = Path(vault_path)
    if not vault.exists():
        raise FileNotFoundError(f"Vault 路徑不存在：{vault_path}")

    # 查詢該路徑下所有 .md 檔，但踢除不在 FOLDER_TYPE_MAP 搜索範圍內的.md檔
    all_md_files = vault.rglob("*.md")
    md_files = []
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
            topic = _infer_topic(tags, md_file.stem)  # .stem取得檔名(不含檔型 .md)的字串

            doc = {"file_name": md_file.name,  # .name取得檔名(含檔型 .md)的字串
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

    logger.success(f"解析完成，成功 {len(results)} 筆")
    return results


if __name__ == "__main__":
    load_dotenv()
    obsidian_vault_path = os.getenv("OBSIDIAN_VAULT_PATH")
    results = scan_vault(obsidian_vault_path)
