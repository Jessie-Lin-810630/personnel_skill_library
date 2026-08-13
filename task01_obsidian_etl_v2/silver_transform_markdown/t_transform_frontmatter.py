"""把單份 raw .md 的 frontmatter 清洗成 tags/date/type/alias 四欄，供 upsert to metadata 時內嵌。

1. 讀 frontmatter metadata
2. 若讀取結果是空的，確認是否錯位到正文，並改從正文補救回來
3. tags/alias 正規化成 list[str]、date 正規化成 UTC datetime、
type 依 frontmatter 或 section 前綴推導
4. 組出 md_frontmatter dict。

Required .env keys:
    (無；純資料轉換，不直接讀寫外部資源。)
"""

from datetime import date, datetime, time, timezone
from pathlib import Path

import frontmatter

from .e_get_changed_files import FOLDER_TYPE_MAP


def _infer_note_type(md_file_path: Path, fm_data: dict) -> str:
    """判斷筆記的 note_type，優先看 frontmatter 的 type，其次用 section 資料夾前綴 fallback。

    1. 若 frontmatter 有寫 type，依關鍵字歸類成 daily-log、project 或 knowledge-summary。
    2. frontmatter 沒寫或無法歸類時，改看該 .md 上層資料夾名稱的前兩碼。
    3. 前兩碼以 FOLDER_TYPE_MAP 查表，查不到就歸為 unknown。

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


def _infer_misposition_metadata(post: frontmatter.Post) -> dict[str, list | str]:
    """當 frontmatter 誤植到正文時的補救解析，掃正文頂端的 key: value 區塊把欄位撿回來。

    1. 逐行往下掃，一路把殘留的分隔線與前後空白清掉。
    2. 碰到第一個真正的 Markdown 標題行就停止。
    3. 只在第一個冒號處切開欄位名與值，全形與半形冒號都接受。
    4. 依欄位名把值收進 tags、date、type、alias 四個欄位。

    Note:
        判定標題行時要求 # 後面接空白或再一個 #，這樣行內標籤例如 #python 才不會被誤判成標題而提早截斷。
        只切第一個冒號則是為了讓值本身含冒號的內容保持完整，例如時間 10:30 或網址。

    Args:
        post: frontmatter.loads 解析後的物件。

    Returns:
        含 tags、date、type、alias 四個鍵的字典；正文頂端沒有可辨識的欄位時，各鍵維持空值。
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
    """把 frontmatter 的 tags 或 alias 正規化成字串清單，同時容忍逗號分隔字串與既有清單兩種寫法。

    1. 已是清單時，逐項轉成字串後做正規化，並濾掉空項。
    2. 是字串時，先去掉方括號再以逗號切開，同樣逐項正規化並濾掉空項。
    3. 其餘型別，例如 None，一律回空清單。

    每一項的正規化包含轉小寫、把底線換成連字號、去除前後空白三個動作。

    Note:
        正規化的目的是讓同一個標籤在不同筆記裡的大小寫或分隔符差異收斂成同一個值，
        否則 python 與 Python 會在下游被當成兩個不同的標籤。

    Args:
        value: frontmatter 的 tags 或 alias 原始值，型別不定。

    Returns:
        正規化後的字串清單；無法處理的型別回空清單。
    """
    if isinstance(value, list):
        return [str(v).lower().replace("_", "-").replace("__", "-").strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [
            t.lower().replace("_", "-").replace("__", "-").strip()
            for t in value.replace("[", "").replace("]", "").split(",")
            if t.strip()
        ]
    return []


def _normalize_date(value) -> datetime | None:
    """把 frontmatter 的 date 正規化成 BSON 可編碼的 UTC datetime，無法解析時回 None。

    1. 已是 datetime 就直接回傳。
    2. 是 date 時補上 UTC 午夜時間轉成 datetime。
    3. 是非空字串時，依序嘗試連字號、斜線、底線三種日期分隔寫法。
    4. 都不符合就回 None。

    Note:
        補時間與補時區都是為了讓值能被 BSON 編碼，純 date 型別無法直接寫進 MongoDB。

    Args:
        value: frontmatter 的 date 原始值，型別不定。

    Returns:
        帶 UTC 時區的 datetime；無法解析時回 None，由呼叫端決定該筆記是否留空日期。
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


def extract_frontmatter(post: frontmatter.Post, md_file_path: str) -> dict:
    """組出要內嵌進 obsidian_note_metadata 的 md_frontmatter，含 tags、date、type、alias 四欄。

    1. 先讀 frontmatter 的欄位區。
    2. 欄位區是空的時，改用 _infer_misposition_metadata 掃正文頂端補救。
    3. tags 與 alias 正規化成字串清單、date 正規化成 UTC datetime、type 交給 _infer_note_type 判斷。

    Args:
        post: frontmatter.loads 解析後的物件。
        md_file_path: 這份 .md 的 blob 名稱，供 type 判斷不出時改看上層資料夾前綴。

    Returns:
        含 tags、date、type、alias 四個鍵的字典，作為 archived_md_frontmatter 的值。
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
