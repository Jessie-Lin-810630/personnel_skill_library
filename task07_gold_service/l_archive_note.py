"""Gold 層 Load：approve 歸檔 / reject 退件，兩者都把 md frontmatter 寫回 onenote_note_metadata 供好壞 md 分析。

本層不做向量化 (解耦至另一條 pipeline Task06)。

執行流程：
    1. approve (archive_note)：取 Collection onenote_note_metadata 取得筆記 metadata 資料
    → 把關是否早有同名已歸檔筆記。
    → 複製 md (processed-notes) 與 png (raw-notes) 到 archived-notes/。
    → upsert Collection onenote_note_metadata (status=archived、歸檔路徑、審核欄位)。
    → 退役同頁其他 pending_review 版本 (status=review_closed、同 hash 標 overwritten 否則 rejected)。
    → 讀回歸檔 md ，萃取 frontmatter 並統計 valid_img。
    → 以內嵌 Object md_frontmatter upsert Collection onenote_note_metadata。
    2. reject (reject_note): 取 Collection onenote_note_metadata 取得筆記 metadata 資料
    → upsert Collection onenote_note_metadata (status=review_closed、審核欄位)
    → 讀 md (processed-notes) 萃取 frontmatter 並統計 valid_img。
    → 以內嵌 Object md_frontmatter upsert Collection onenote_note_metadata。

Usage:
    由 gold_service 的 /archive 端點在 approve/reject 時呼叫。

Required .env keys:
    MONGO_ALTAS_URI     MongoDB Atlas connection URI.
    MONGO_DB_NAME       MongoDB database name.

Optional .env keys:
    ONENOTE_GCS_BUCKET  GCS data lake bucket (defaults to onenote-vaults).
"""

import re
from datetime import date, datetime, time, timezone
from pathlib import PurePosixPath

import frontmatter
from loguru import logger

from task07_common import gcs
from task07_common.audit_log import (
    get_latest_archived_version,
    get_sibling_pending_versions,
    get_version_meta,
    now_utc,
    upsert_version_meta,
)
from task07_common.topic import infer_topic


def _dt_to_date(dt_str: str) -> date | None:
    """把 dt 分區字串 (YYYY-MM-DD 等) 轉為 date；無法解析回傳 None。"""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y_%m_%d"):
        try:
            return datetime.strptime(dt_str, fmt).date()
        except ValueError:  # 格式不符：試下一個格式
            continue
        except TypeError:  # dt_str 為 None：試下一個格式（拆兩行避開 tuple 寫法被反覆還原成 Py2 語法）
            continue
    logger.warning(f"dt 分區字串 '{dt_str}' 轉換失敗，請在資料庫檢查該字串是否特別不同")
    return None


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


# md 圖片語法 ![alt](path)：取 () 內路徑，供統計連結總數與比對是否命中圖片
_IMG_LINK_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _count_img_links(content: str) -> int:
    """統計 md 正文 ![]() 圖片連結的總數（含改壞、指向不存在圖片者）。"""
    return len(_IMG_LINK_RE.findall(content))


def _count_valid_images(content: str, img_paths: list[str]) -> int:
    """統計 md 正文 ![]() 連結中，檔名有落入 img_paths (basename 比對) 的張數。

    模型有隨機性，可能把圖片檔名改壞導致連結指向不存在的圖；命中對應圖者才算 validated，
    此計數供事後追蹤模型輸出的圖片連結正確率。

    Args:
        content (str): md 的正文 (不含 frontmatter 區)。
        img_paths (list[str]): 對應的 png gs:// 路徑集合 (approve 傳 archived、reject 傳 raw，basename 一致)。

    Returns:
        int: md 圖片連結命中對應圖片的次數。
    """
    valid_names = {PurePosixPath(p).name for p in (img_paths or [])}
    if not valid_names:
        return 0
    return sum(1 for link in _IMG_LINK_RE.findall(content) if PurePosixPath(link.strip()).name in valid_names)


def _build_md_quality_meta(md_str: str, img_paths: list[str] | None, page_title: str) -> dict:
    """讀 md，組出要 upsert 進 metadata 的品質欄位：md_frontmatter、md_body、dismatched 統計與 topic。

    frontmatter 未寫進 metadata 區時以正文頂端補救解析；valid_img 由正文 ![]() 連結 basename
    比對 img_paths 得出 (approve 傳 archived_image_path、reject 傳 raw_image_path，basename 一致)；
    dismatched = 連結總數 - valid_img；topic 以 frontmatter tags＋頁面標題重算 (對齊 task01 分類)。

    Args:
        md_str (str): md 全文 (approve 為歸檔 md、reject 為 silver md)。
        img_paths (list[str] | None): 該版對應的 png 路徑集合，供 valid_img basename 比對。
        page_title (str): 頁面標題，供 topic 重算的比對來源之一。

    Returns:
        dict: {md_frontmatter, md_body, dismatched_img_count, md_has_dismatched_img, topic}，
        供以同主鍵 upsert Collection onenote_note_metadata。
    """
    post = frontmatter.loads(md_str)
    fm = post.metadata
    if not fm:
        fm = _infer_misposition_metadata(post)

    tags = _normalize_str_list(fm.get("tags", []))
    valid_img = _count_valid_images(post.content, img_paths or [])
    total_links = _count_img_links(post.content)
    dismatched = total_links - valid_img

    md_frontmatter = {
        "tags": tags,
        "date": _normalize_date(fm.get("date")),
        "type": fm.get("type") or None,
        "alias": _normalize_str_list(fm.get("alias", [])),
    }
    md_body = {
        "valid_img_count": valid_img,
        "word_count": len(post.content.split()),
        "recomputed_at": None,
    }
    return {
        "md_frontmatter": md_frontmatter,
        "md_body": md_body,
        "dismatched_img_count": dismatched,
        "md_has_dismatched_img": dismatched > 0,
        "topic": infer_topic(tags, page_title),
    }


def archive_note(page_id: str, dt: str, role: str) -> dict:
    """Gold 層：把 approved 的 md 與 png 歸檔到 archived-notes/，並回寫 frontmatter 做品質確認。

    歸檔到 gs://onenote-vaults/archived-notes/...，先更新一次 Collection onenote_note_metadata，
    再讀回 archived md 檔萃取 frontmatter 做資料品質確認，做第二次 metadata 更新。

    Notes:
        讀回 archived md 與第二次 metadata 更新，如果經使用者體驗發現前端回覆歸檔進度過慢，
        則評估將 step 5 拆開走另一個 route。

    Args:
        page_id (str): OneNote page id。
        dt (str): 版本日期分區字串。
        role (str): 審核者角色 (寫入 reviewed_by_role)。

    Returns:
        dict: {status, md_archive_path, img_archive_path, error}；不同分支帶不同欄位。
    """
    ATTEMPTS = 3  # for step 5

    # 1. 先從 metadata 撈取這份筆記的狀態
    meta = get_version_meta(page_id, dt)
    if not meta:
        return {"status": "not_found", "error": f"無此版本 (page_id={page_id}, dt={dt})"}

    # 本版已歸檔 → idempotent，直接回既有結果不重做
    if meta.get("status") == "archived":
        return {
            "status": "archived",
            "md_archive_path": meta.get("archived_md_path"),
            "img_archive_path": [
                img["archived_image_path"] for img in meta.get("attached_images", []) if img.get("archived_image_path")
            ],
            "note": "already archived",
        }

    enriched_md_path = meta.get("enriched_md_path")
    if not enriched_md_path:
        return {"status": meta.get("status"), "error": "此版本目前無生成 md，無法歸檔"}

    # 取出最近一次歸檔日
    latest_archived = get_latest_archived_version(page_id)
    if latest_archived:
        # this_day = 現在在審閱的是哪個 dt 版本的 note，回傳 date part
        this_day = _dt_to_date(dt)
        archived_at = latest_archived.get("archived_at")
        last_archived_day = archived_at.date() if isinstance(archived_at, datetime) else None

        # 查看的版本 (dt) 如果早於最近一次歸檔日，則不給歸檔，也就是每次歸檔行為會從所有 dt 版本中取一份，
        # 歸檔完成後，其他 dt 不給歸檔，避免造成人工審閱工作繁重。
        if this_day and last_archived_day and this_day < last_archived_day:
            return {
                "status": "archived_conflict",
                "error": f"已有更新版本歸檔 (dt={latest_archived.get('dt')})，不覆寫舊版",
            }

    # 如果 dt ≥ 最後歸檔日，視為可能上一次歸檔後原始筆記有需求更改，
    # 故這版 dt 的筆記能重回 Silver&Gold 層
    archived_prefix = gcs.archived_note_prefix(meta["onenote_user_id"], meta["notebook"], meta["section"], dt)

    now = now_utc()
    try:
        # 2. 執行歸檔：從 processed-notes 複製 md 到 archived-notes
        md_name = PurePosixPath(enriched_md_path).name
        md_dst_blob = f"{archived_prefix}/{md_name}"
        md_md5_hash = gcs.copy_blob(enriched_md_path, md_dst_blob)
        md_archive_uri = gcs.gs_uri(md_dst_blob)

        # 3. 執行歸檔：逐一從 raw-notes 複製 png 到 archived-notes，並把 archived 端路徑/md5
        #    回填進對應的 attached_images Object（保留 raw 端欄位不動）。
        attached_images: list[dict] = []
        img_archive_paths: list[str] = []
        for img in meta.get("attached_images", []) or []:
            raw_uri = img.get("raw_image_path")
            if not raw_uri:
                attached_images.append(img)
                continue
            img_name = PurePosixPath(raw_uri).name
            img_dst_blob = f"{archived_prefix}/_images/{img_name}"
            archived_md5 = gcs.copy_blob(raw_uri, img_dst_blob)
            archived_uri = gcs.gs_uri(img_dst_blob)
            img_archive_paths.append(archived_uri)
            attached_images.append({**img, "archived_image_path": archived_uri, "archived_image_md5": archived_md5})
    except Exception as e:  # noqa: BLE001
        upsert_version_meta(page_id, dt, set_fields={"status": "archive_failed", "error_msg": f"[gold:copy] {e}"})
        logger.exception(f"[gold] 歸檔複製失敗: page_id={page_id}, dt={dt}")
        return {"status": "archive_failed", "error": f"[gold:copy] {e}"}

    # 4. 更新 metadata：歸檔狀態與路徑
    upsert_version_meta(
        page_id,
        dt,
        set_fields={
            "status": "archived",
            "review_result": "approved",
            "reviewed_by_role": role,
            "reviewed_at": now,
            "archived_at": now,
            "archived_md_path": md_archive_uri,
            "md_md5_hash": md_md5_hash,
            "attached_images": attached_images,
            "error_msg": None,
        },
    )

    # 4b. 退役同頁其他仍在審閱的候選版本：本輪已擇一歸檔，其餘連帶結束審閱期。
    #     html_sha_hash 與歸檔版相同者標 overwritten（內容等同已被採納），不同者 rejected。
    archived_hash = meta.get("html_sha_hash")
    for sib in get_sibling_pending_versions(page_id, dt):
        retired_result = "overwritten" if sib.get("html_sha_hash") == archived_hash else "rejected"
        upsert_version_meta(
            sib["page_id"],
            sib["dt"],
            set_fields={
                "status": "review_closed",
                "review_result": retired_result,
                "reviewed_at": now,
            },
        )

    # 5. 後台運作：讀回歸檔完成的 md、萃取 md_frontmatter/md_body/dismatched/topic，
    # 以內嵌 Object upsert Collection onenote_note_metadata
    for _ in range(ATTEMPTS):
        try:
            archived_md = gcs.download_text(md_archive_uri)
            quality = _build_md_quality_meta(archived_md, img_archive_paths, meta["page_title"])
            upsert_version_meta(page_id, dt, set_fields=quality)
            logger.success(f"[gold] archived page_id={page_id}, dt={dt} → {md_archive_uri}")
            return {
                "status": "archived",
                "md_archive_path": md_archive_uri,
                "img_archive_path": img_archive_paths,
            }
        except Exception as e:  # noqa: BLE001
            upsert_version_meta(page_id, dt, set_fields={"error_msg": f"[gold:frontmatter] {e}"})
            logger.warning(f"[gold] frontmatter fail (已歸檔，但無法寫入 frontmatter 到 metadata): {e}")
            continue

    # 重試皆失敗：歸檔本體已完成（md/png 已複製、onenote_note_metadata 已翻 archived），僅 frontmatter 從缺
    return {"status": "archived", "md_archive_path": md_archive_uri, "img_archive_path": img_archive_paths}


def reject_note(page_id: str, dt: str, role: str) -> dict:
    """Gold 層：把 rejected 版本狀態翻成 review_closed，並回寫該 md 的 frontmatter 供品質分析。

    不歸檔；把 gs://onenote-vaults/processed-notes/... (silver 層) md 的 frontmatter 寫回
    Collection onenote_note_metadata，追溯被退件筆記的資料品質，供流程分析。

    Notes:
        不寫任何 GCS。frontmatter 萃取為背景步驟，若萃取失敗只記 error_msg。

    Args:
        page_id (str): OneNote page id。
        dt (str): 版本日期分區字串。
        role (str): 審核者角色 (寫入 reviewed_by_role)。

    Returns:
        dict: {status, review_result, error}；查無版本回 not_found。
    """
    ATTEMPTS = 3
    # 1. 先從 metadata 撈取這份筆記的狀態
    meta = get_version_meta(page_id, dt)
    if not meta:
        return {"status": "not_found", "error": f"無此版本 (page_id={page_id}, dt={dt})"}

    # 2. 不歸檔，直接更新 metadata：審閱狀態
    upsert_version_meta(
        page_id,
        dt,
        set_fields={
            "status": "review_closed",
            "review_result": "rejected",
            "reviewed_by_role": role,
            "reviewed_at": now_utc(),
        },
    )

    # 3. 背景：把 rejected md 的 md_frontmatter/md_body/dismatched/topic 也寫進 metadata，以分析被 reject 的原因
    enriched_md_path = meta.get("enriched_md_path")
    if enriched_md_path:
        raw_img_paths = [img["raw_image_path"] for img in meta.get("attached_images", []) if img.get("raw_image_path")]
        for _ in range(ATTEMPTS):
            try:
                md_str = gcs.download_text(enriched_md_path)
                quality = _build_md_quality_meta(md_str, raw_img_paths, meta["page_title"])
                upsert_version_meta(page_id, dt, set_fields=quality)
                logger.success(f"[gold] rejected page_id={page_id}, dt={dt}, role={role}")
                return {"status": "review_closed", "review_result": "rejected"}
            except Exception as e:  # noqa: BLE001
                upsert_version_meta(page_id, dt, set_fields={"error_msg": f"[reject:frontmatter] {e}"})
                logger.warning(f"[gold] rejected frontmatter fail (已退件，但無法寫入 frontmatter 到 metadata): {e}")
                continue

    # 無 md 可分析、或 frontmatter 重試皆失敗：退件本體已完成，仍回成功結果
    return {"status": "review_closed", "review_result": "rejected"}
