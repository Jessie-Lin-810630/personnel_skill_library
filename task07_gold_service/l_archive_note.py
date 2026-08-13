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
    """把版本分區字串轉成日期物件，供比較版本新舊。

    依序嘗試連字號、斜線、底線三種日期分隔寫法。

    Args:
        dt_str: 版本分區字串。

    Returns:
        對應的日期物件；三種寫法都不符或傳入 None 時，記一筆 warning 後回 None。
    """
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
    """當 frontmatter 誤植到正文時的補救解析，掃正文頂端的欄位區塊把值撿回來。

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

    已是清單時逐項轉成字串並去除前後空白，是字串時先去掉方括號再以逗號切開，兩者都會濾掉空項。

    Note:
        這裡只去空白、不轉小寫，與 task01 對 Obsidian 標籤的處理不同，
        因為 OneNote 的標籤由模型產出時已在 _build_markdown 統一過大小寫。

    Args:
        value: frontmatter 的 tags 或 alias 原始值，型別不定。

    Returns:
        正規化後的字串清單；無法處理的型別回空清單。
    """
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [t.strip() for t in value.replace("[", "").replace("]", "").split(",") if t.strip()]
    return []


def _normalize_date(value) -> datetime | None:
    """把 frontmatter 的 date 正規化成帶 UTC 時區的 datetime。

    已是 datetime 就直接回傳，是日期物件就補上 UTC 午夜時間，
    是字串則依序嘗試連字號、斜線、底線三種日期分隔寫法。

    Note:
        補時間與補時區都是為了讓值能被 BSON 編碼，純日期型別無法直接寫進 MongoDB。

    Args:
        value: frontmatter 的 date 原始值，型別不定。

    Returns:
        帶 UTC 時區的 datetime；無法解析時回 None，該筆記的日期欄位便留空。
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):  # 純日期沒有時間，補 UTC 午夜再轉 datetime
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
    """統計 md 正文裡圖片連結的總數。

    Note:
        總數包含連結被改壞、指向不存在圖片的那些，因此這個數字減去有效張數即為失效張數。

    Args:
        content: md 的正文，不含 frontmatter 區塊。

    Returns:
        圖片連結的出現次數。
    """
    return len(_IMG_LINK_RE.findall(content))


def _count_valid_images(content: str, img_paths: list[str]) -> int:
    """統計 md 正文的圖片連結中，有多少張真的指向這份筆記實際擁有的圖片。

    只比對檔名，不比對完整路徑。

    Note:
        模型輸出帶有隨機性，可能把圖片檔名改壞而讓連結指向不存在的圖，因此需要這個計數
        追蹤模型輸出圖片連結的正確率。歸檔時傳歸檔後的圖片路徑、退件時傳原始圖片路徑，
        兩者檔名相同，所以比對結果一致。

    Args:
        content: md 的正文，不含 frontmatter 區塊。
        img_paths: 這份筆記實際擁有的圖片位址清單。

    Returns:
        連結檔名命中實際圖片的次數；沒有任何圖片時回 0。
    """
    valid_names = {PurePosixPath(p).name for p in (img_paths or [])}
    if not valid_names:
        return 0
    return sum(1 for link in _IMG_LINK_RE.findall(content) if PurePosixPath(link.strip()).name in valid_names)


def _build_md_quality_meta(md_str: str, img_paths: list[str] | None, page_title: str) -> dict:
    """讀一份 md，組出要寫回 metadata 的品質欄位。

    解析 frontmatter，欄位區是空的時改用正文頂端補救；統計圖片連結的有效與失效張數；
    最後以標籤與頁面標題重新推算 topic。

    Note:
        topic 在 Bronze 階段只憑標題初判，這裡拿模型產出的標籤一起重算會更準確，
        因此同一份筆記的 topic 可能在此改變。失效張數由連結總數減去有效張數得出，
        數值大於 0 代表模型改壞了圖片連結，供事後追蹤輸出品質。

    Args:
        md_str: md 全文，歸檔時傳歸檔後的內容、退件時傳 Silver 層的內容。
        img_paths: 這份筆記實際擁有的圖片位址清單，供比對圖片連結是否有效。
        page_title: 頁面標題，作為重算 topic 的比對來源之一。

    Returns:
        含 md_frontmatter、md_body、dismatched_img_count、md_has_dismatched_img 與 topic
        五個鍵的字典，供呼叫端以同一組複合唯一鍵寫回 onenote_note_metadata。
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
    """Gold 層的核可歸檔，把通過審查的 md 與圖片複製到 archived-notes/ 並回寫品質欄位。

    1. 讀取該版本的 metadata，取不到就回覆查無此版本；已歸檔過則直接回既有結果。
    2. 比對這一版與最近一次歸檔的日期，較舊就拒絕歸檔。
    3. 把 md 從 Silver 層、圖片從 Bronze 層分別複製到 Gold 層，並回填各張圖歸檔後的路徑與 md5。
    4. 更新 metadata 的歸檔狀態、路徑與審核欄位。
    5. 結束同一頁其他仍在審閱的版本。
    6. 讀回歸檔後的 md，萃取品質欄位再寫回 metadata，最多重試三次。

    Note:
        第二步拒絕舊版本歸檔，是為了避免已有較新內容歸檔後又被舊版覆寫，也讓人工審閱不必回頭處理舊版。
        第五步依內容雜湊決定其他版本的結果：與歸檔版相同者標為已被覆寫，不同者標為退件。
        第六步的重試若全部失敗，仍回報歸檔成功，因為 md 與圖片都已複製完成、狀態也已更新，
        只有品質欄位從缺，失敗原因記在 error_msg。
        若日後審查頁反映歸檔回應太慢，可評估把第六步拆成另一個端點非同步執行。

    Args:
        page_id: OneNote 頁面代號。
        dt: 版本分區字串。
        role: 審核者角色，寫入 reviewed_by_role。

    Returns:
        含 status 的結果字典，md 與圖片寫進 GCS、狀態寫進 MongoDB 的 onenote_note_metadata。
        status 可能是 archived、not_found、archived_conflict、archive_failed 或該版本原本的狀態；
        成功時另帶 md_archive_path 與 img_archive_path 指向歸檔後的位址，失敗時帶 error 說明原因。
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
            logger.success(f"[gold] archived page_id={page_id}, dt={dt}, uri={md_archive_uri}")
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
    """Gold 層的退件處理，把該版本標為結束審閱，並回寫該 md 的品質欄位供事後分析。

    1. 讀取該版本的 metadata，取不到就回覆查無此版本。
    2. 更新狀態與審核欄位，標記為退件。
    3. 讀 Silver 層那份 md，萃取品質欄位再寫回 metadata，最多重試三次。

    Note:
        這支函式完全不寫 GCS，被退件的 md 仍留在 Silver 層不做搬移。
        第三步只是背景分析用，即使該版本沒有 md 可讀、或重試全部失敗，退件本身仍算完成並回報成功，
        失敗原因記在 error_msg。保留這些欄位是為了日後回頭分析筆記為何被退件。

    Args:
        page_id: OneNote 頁面代號。
        dt: 版本分區字串。
        role: 審核者角色，寫入 reviewed_by_role。

    Returns:
        含 status 的結果字典，狀態寫進 MongoDB 的 onenote_note_metadata。
        查無版本時 status 為 not_found 並帶 error 說明；其餘情況 status 為 review_closed、
        review_result 為 rejected。
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
