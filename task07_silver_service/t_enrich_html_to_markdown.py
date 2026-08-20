"""Silver 層 Transform：供 flask app on-demand 呼叫。

執行流程：
    1. 從 UI 透過 flask app 呼叫 t_enrich_html_to_markdown(page_id, dt)，
       讀 Collection onenote_note_metadata 取 html_hash。
    2. 以 html_hash 查是否能快取到已存好的對應 md，命中則撈取既有 md 拋給前端、跳過 LLM call。
    3. 未命中則呼叫 LLM 重整 html 生成 md。
    4. 存 md 到 GCS，再 upsert Collection onenote_note_metadata，更新 html note 的資料血緣。

設計要點：
- 不在 ETL 主動執行；提供 t_enrich_html_to_markdown(page_id, dt) 函式供 UI on-demand 呼叫。
- LLMServiceGuard：LLM API 連續失敗達門檻則暫停 on-demand 一段時間，期間筆記維持 bronze_stored。
- regenerate quota：同一 html_hash 最多 regenerate 2 次。
"""

import os
import re
import time
from pathlib import PurePosixPath

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai
from google.genai import types
from loguru import logger

from task07_common import gcs
from task07_common.audit_log import (
    count_regenerate,
    find_cached_md_by_hash,
    get_version_meta,
    log_enrichment_call,
    upsert_version_meta,
)

from .l_save_markdown import save_enriched_md

load_dotenv()

RESHAPE_MODEL = "gemini-2.5-flash"
REGENERATE_QUOTA = 2

# 內嵌圖片以 gs:// URI 直接交給 Agent Platform 多模態判讀，副檔名 → mime type
_IMG_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
}


def _img_mime(uri: str) -> str:
    """依副檔名判斷圖片的 mime type，供組裝多模態請求時標註。

    Args:
        uri: 圖片的完整物件位址，只取其副檔名參與判斷。

    Returns:
        對應的 mime type 字串；副檔名不在對照表內時一律回 image/png。
    """
    return _IMG_MIME.get(PurePosixPath(uri).suffix.lower(), "image/png")


gemini_response_schema = {
    "type": "object",
    "title": "NoteAnalysisResult",
    "properties": {
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "5-10 keywords (technical terms; mix Chinese/English)",
        },
        "alias": {
            "type": "array",
            "items": {"type": "string"},
            "description": ("one-two concise short titles (2-6 words per alias, same language as the main title)"),
        },
        "new_content": {
            "type": "string",
            "description": (
                "Reshaped content fitted with Markdown hierarchy. "
                "(i) Use #/##/### (ii) Use lists (iii) Keep blank lines between elements "
                "(iv) Do not stick new elements to the end of the previous line."
            ),
        },
    },
    "required": ["tags", "alias", "new_content"],
}


# ── 服務級守門 (當 LLM API 連續失敗則暫停 on-demand) ──────────────────────────────


class _LLMServiceGuard:
    """簡易版 circuit breaker，連續失敗達門檻就暫停呼叫模型一段冷卻時間。

    Note:
        只實作 closed 與 open 兩個狀態，沒有標準 circuit breaker 的 half-open。
        冷卻時間一到就全額恢復流量，不會先放一個試探請求，因此模型端若尚未復原，
        恢復瞬間的請求會一起湧上去，並需再累積一輪連續失敗才會重新跳脫。
        以本服務的規模而言可接受，但不要照標準三狀態去推測它的行為。

        狀態綁在服務層而非單一筆記，因此任何一篇筆記連續失敗都會讓整個服務暫停，
        這是刻意的取捨：連續失敗通常代表模型端或憑證有問題，逐篇重試只會放大損失。
        狀態存在記憶體，服務重啟即歸零，多個執行個體之間也不共享。
    """

    def __init__(self, max_consecutive_failures: int = 5, cooldown_seconds: int = 300):
        """建立 circuit breaker，設定跳脫門檻與冷卻時間。

        Args:
            max_consecutive_failures: 連續失敗幾次就暫停，預設 5 次。
            cooldown_seconds: 暫停多久，單位秒，預設 300 秒。
        """
        self.max = max_consecutive_failures
        self.cooldown = cooldown_seconds
        self._consecutive = 0  # 實際連續失敗次數
        self._open_until = 0.0  # 暫停到何時

    def is_open(self) -> bool:
        """查詢目前是否處於 open 狀態，也就是還在冷卻期間內。

        Returns:
            仍在冷卻時間內為 True，此時呼叫端應略過模型呼叫。
        """
        return time.time() < self._open_until

    def record_success(self) -> None:
        """記錄一次成功，把連續失敗次數歸零並回到 closed 狀態。

        Returns:
            None: 只更新這個物件的內部狀態，不回傳值。
        """
        self._consecutive = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        """記錄一次失敗，連續次數達門檻就跳脫成 open 狀態。

        跳脫時記一筆 error，並把連續次數歸零，讓冷卻結束後重新計算。

        Returns:
            None: 只更新這個物件的內部狀態，不回傳值。
        """
        self._consecutive += 1
        if self._consecutive >= self.max:
            self._open_until = time.time() + self.cooldown
            self._consecutive = 0
            logger.error(f"[circuit] LLM 連續失敗達 {self.max} 次，暫停 on-demand {self.cooldown}s")


_guard = _LLMServiceGuard()


# ── Gemini ────────────────────────────────────────────────────────────────────


def _get_genai_client() -> genai.Client:
    """初始化指向 Agent Platform 的 google-genai client，供重整 html 的模型呼叫。

    這個 client 綁定 us-central1，因為本服務使用的模型部署在該 region。

    Note:
        雲端執行時憑證由 Cloud Run 的 runtime service account 以應用程式預設憑證供給，
        地端則需先解除函式內的註解區塊，改以 service account 金鑰檔初始化，否則會取不到憑證。

    Returns:
        綁定 us-central1 的 google-genai Client 物件。

    Raises:
        EnvironmentError: 環境變數 GCP_PROJECT_ID 未設定時拋出。
    """
    # # 地端測試跑下面區塊：
    # # 先驗環境變數再建 Credentials，否則 json_path 為 None 會讓 Credentials 先拋 TypeError/FileNotFoundError
    # from google.oauth2.service_account import Credentials
    # json_path = os.getenv("AGENT_PLATFORM_USER_CREDENTIALS")
    # project = os.getenv("GCP_PROJECT_ID")
    # if not project or not json_path:
    #     raise EnvironmentError(
    #         "找不到 GCP_PROJECT_ID / AGENT_PLATFORM_USER_CREDENTIALS，請確認已設定在 .env 或 secret manager。"
    #     )
    # scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    # credentials = Credentials.from_service_account_file(json_path, scopes=scopes)
    # return genai.Client(vertexai=True, project=project, location="us", credentials=credentials)

    # Cloud run 跑下面區塊：
    project = os.getenv("GCP_PROJECT_ID")
    if not project:
        raise EnvironmentError("找不到 GCP_PROJECT_ID，請確認已設定在 secret manager。")
    return genai.Client(vertexai=True, project=project, location="us-central1")


def _classify_note_type(filename: str) -> str:
    """依檔名是否帶有日期字樣，判斷這份筆記屬於哪一種類型。

    可辨識的日期寫法有連字號、底線、純數字八碼與中文年月日四種。

    Args:
        filename: 筆記檔名或頁面標題。

    Returns:
        帶日期字樣時回 daily-log，否則回 knowledge-summary。
    """
    DATE_IN_FILENAME = re.compile(
        r"\d{4}-\d{2}-\d{2}|"
        r"\d{4}_\d{2}_\d{2}|"
        r"\d{8}(?!\d)|"
        r"\d{4}年\d{1,2}月\d{1,2}日"
    )
    return "daily-log" if DATE_IN_FILENAME.search(filename) else "knowledge-summary"


def convert_img_tag_to_md_str(html_content: str) -> BeautifulSoup:
    """把 html 裡的每個圖片標籤就地換成 Markdown 的圖片語法。

    替代文字取自圖片標籤本身，缺漏時填 image；其中的中括號與驚嘆號會換成連字號，
    避免這些符號讓 Markdown 的圖片語法解析失敗。

    Args:
        html_content: 原始 html 字串。

    Returns:
        圖片標籤已替換成 Markdown 語法的 soup 物件，呼叫端可再取其純文字送進模型。
    """
    soup = BeautifulSoup(html_content, "html.parser")
    for img in soup.find_all("img"):
        alt = " ".join(img.get("alt", "").split()) or "image"
        # alt 替代避免文字可能會有 ] 、 [ 、 ! 符號會讓 md 檔圖片顯示失敗
        alt = alt.replace("]", "-").replace("[", "-").replace("!", "-").replace("！", "-")
        src = img.get("src", "")

        # conver to string to meet the link syntax of image in a markdown file
        img.replace_with(f"\n![{alt}]({src})\n")
    return soup


def _call_llm(
    client: genai.Client, page_title: str, plain_text: str, img_uris: list[str] | None = None
) -> tuple[dict, dict]:
    """呼叫模型對筆記做多模態重整，同時產出標籤、別名與重整後的內容。

    除了文字，內文圖片連結對應的原圖也會一併送入，讓模型實際判讀圖片內容並產出圖片概述。
    每張圖前面各附一段文字標籤，標明它對應內文哪一個圖片連結，方便模型對齊。
    模型以 JSON schema 約束輸出，因此回應可直接解析成結構化結果。

    Args:
        client: google-genai Client 物件。
        page_title: 筆記標題，寫進 prompt 供模型理解主題。
        plain_text: 要讓模型判讀的純文字內容。
        img_uris: 要讓模型判讀的圖片位址清單，預設為 None，代表這篇沒有圖片。

    Returns:
        模型解析結果與 token 用量組成的 tuple。前者含 tags、alias 與 new_content 三個鍵，
        後者含輸入、輸出與合計三種 token 數。

    Raises:
        ValueError: 模型回應無法解析成結構化結果時拋出。
    """
    img_uris = img_uris or []
    prompts = f"""Analyze this note and extract:
                    1. reshape the hierarchy: Reshape the hierarchy of content but no changing any original letters,
                        after reshaping, the new content should fitted with the markdown. A good fitness means:
                        (i) 標題用 # / ## / ###
                        (ii) 清單用 - 或 *
                        (iii) 圖片、標題、清單之間留空行
                        (iv) 不要把新元素黏在上一行尾巴
                        (v) 如文章中有「詞彙(terminology)定義」、「參考資料連結」或「參考資料文件名稱」，
                            把他們移到整篇文章的前面，當作前言，然後才排序其他主文標題。
                        (vi) 如果遇到![]()這樣的文字，代表它是與 markdown 語法相容的圖片link，
                             **請不要隨意移出他原本所屬的章節，也不可以修改![]()這裡面的任何文字符號，但可以調整縮排**。
                             本次請求已把該連結對應的原始圖片一併附在後面（依 `_images/<檔名>` 對齊），
                             **請實際觀看每張圖片的內容**，為其在原連結下方生成 3-10 行精準圖片概述，
                             並標注此段為「AI生成圖釋」。
                        (v) 根據上下文，優先補全句子文法破碎的段落，例如："任務A...done"，補全為"任務A已經完成"，
                            將句子的主詞、動詞、受詞等完整的表達出來。
                        (vi) 刪除跟上下文不連貫沒有意義的標點符號，例如：文章尾巴冗餘的"句號"、-、*、...、
                             TBD 等沒有接續任何文章語意的記號。
                    2. tags: 5-10 keywords (technical terms; mix Chinese/English to match the note's language)
                    3. alias: one-two concise short titles (2-6 words per alias, same language as the main title)

                    Title: {page_title}
                    Content:
                    {plain_text}
                """
    contents: list = [types.Part.from_text(text=prompts)]
    for uri in img_uris:
        name = PurePosixPath(uri).name
        contents.append(types.Part.from_text(text=f"（下面這張圖片對應內文連結 _images/{name}）"))
        contents.append(types.Part.from_uri(file_uri=uri, mime_type=_img_mime(uri)))

    response = client.models.generate_content(
        model=RESHAPE_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.2, response_mime_type="application/json", response_json_schema=gemini_response_schema
        ),
    )
    raw = response.parsed
    if not raw:
        raise ValueError(f"No JSON in response: {raw}")
    usage = {
        "input_tokens": response.usage_metadata.prompt_token_count,
        "output_tokens": response.usage_metadata.candidates_token_count,
        "total_tokens": response.usage_metadata.total_token_count,
    }
    return raw, usage


def _build_markdown(llm: dict, page_title: str, dt: str) -> str:
    """把模型產出的標籤、別名與內容組成含 frontmatter 的 md 全文。

    標籤與別名逐項轉小寫，並把空白與底線換成連字號；筆記類型由頁面標題判斷；
    日期直接取版本分區字串。

    Note:
        標籤與別名的每個元素都用雙引號框住，因為模型輸出浮動，可能出現以特殊符號開頭的值，
        不加引號會讓日後解析 frontmatter 失敗。

    Args:
        llm: _call_llm 回傳的解析結果，含 tags、alias 與 new_content 三個鍵。
        page_title: 頁面標題，供別名的預設值與筆記類型判斷使用。
        dt: 版本分區字串，寫進 frontmatter 的日期欄位。

    Returns:
        frontmatter 接上內文的完整 md 字串。
    """
    tags = llm.get("tags", [])
    alias = llm.get("alias", [page_title])
    md_body = llm.get("new_content", "")

    # 模型輸出浮動，可能出現特殊符號開頭，例如: %rd，以雙引號匡住每個元素避免未來 frontmatter 解析失敗。
    tags_list = "[" + ",".join(f'"{t.lower().replace(" ", "-").replace("_", "-")}"' for t in tags) + "]"
    alias_list = "[" + ",".join(f'"{a.lower().replace(" ", "-").replace("_", "-")}"' for a in alias) + "]"
    note_type = _classify_note_type(page_title)

    # frontmatter suitable opened by Obsidian
    frontmatter = f"---\ntags: {tags_list}\ndate: {dt}\ntype: {note_type}\nalias: {alias_list}\n---\n\n"
    return frontmatter + md_body


# ── on-demand 入口 ─────────────────────────────────────────────────────────────


def t_enrich_html_to_markdown(
    page_id: str, dt: str, trigger: str = "on_demand", client: genai.Client | None = None
) -> dict:
    """Silver 層的 on-demand 入口，把一個版本的 html 重整成 md，供審查頁點擊某版本時呼叫。

    1. 讀取該版本的 metadata，取不到就回覆查無此版本。
    2. 若這次是重新生成，先檢查該內容已用掉的配額是否達上限。
    3. 若這次不是重新生成，先查快取，找到相同內容已生成過的 md 就直接重用。
    4. 快取沒命中時檢查 circuit breaker，仍在冷卻期間就不呼叫模型。
    5. 下載 html、把圖片標籤轉成 Markdown 語法、取出純文字與圖片位址後呼叫模型。
    6. 把模型輸出組成含 frontmatter 的 md 寫進 GCS，並更新 metadata。

    Note:
        三道守門的用意各不相同：配額擋的是單篇筆記反覆重生的成本，
        快取擋的是不同版本或不同頁面之間內容重複的成本，circuit breaker 擋的是模型端整體異常時的連續損失。
        命中快取時只更新 metadata 讓該版本進入待審狀態，不重新寫 md，該次 token 記為 0。
        模型呼叫失敗不往外拋，改把版本狀態記成 enrich_failed 並在回傳值帶錯誤訊息，
        因此呼叫端要看回傳的 status 而不是有沒有收到例外。

    Args:
        page_id: OneNote 頁面代號。
        dt: 版本分區字串，值沿用 Bronze 層下載這份筆記的日期。
        trigger: 觸發來源，預設 on_demand；傳 regenerate 會略過快取、強制重新生成並受配額限制。
        client: 可注入的 google-genai Client 物件，預設為 None，此時自行初始化。

    Returns:
        含 status 的結果字典，md 寫進 GCS、狀態寫進 MongoDB 的 onenote_note_metadata。
        status 可能是 not_found、pending_review、enrich_failed 或該版本原本的狀態；
        另依分支帶上 cache_hit 標示是否重用既有 md、md_path 指向產出的 md、
        circuit_open 標示 circuit breaker 是否處於冷卻中、error 說明失敗或配額用盡的原因。
    """
    # # 地端執行的話，加跑下面一行區塊：
    # gcs.get_client_on_premise()

    # 1. 組裝後續 enriched document markdown 在 GCS 上的存放路徑前綴字
    meta = get_version_meta(page_id, dt)
    if not meta:
        return {"status": "not_found", "error": f"無此版本 (page_id={page_id}, dt={dt})"}

    html_hash = meta["html_sha_hash"]
    notebook, section, page_title = meta["notebook"], meta["section"], meta["page_title"]
    html_path = meta["html_path"]
    user_id = meta["onenote_user_id"]
    processed_prefix = gcs.processed_note_prefix(user_id, notebook, section, dt)

    # 2. 檢查 regenerate 配額是否觸及上限
    if trigger == "regenerate" and count_regenerate(html_hash) >= REGENERATE_QUOTA:
        logger.warning(f"[regenerate] html_hash={html_hash[:8]} 已達上限 {REGENERATE_QUOTA} 次")
        return {
            "status": meta.get("status"),
            "error": "regenerate quota exceeded",
            "cache_hit": False,
            "md_path": meta.get("enriched_md_path"),
        }

    # 3. 若不是接收到 regenerate 需求重新 enrichment，則直接快取查找：
    # 找 html_hash 在 metadata 中，是否找得到已經生成好的對應 md
    if trigger != "regenerate":
        cached = find_cached_md_by_hash(html_hash)
        if cached:
            # 有對應 md 不需 call LLM，直接紀錄 log 說明判斷結果
            log_enrichment_call(
                page_id=page_id,
                html_hash=html_hash,
                model=RESHAPE_MODEL,
                cache_hit=True,
                trigger=trigger,
                status="success",
                latency_ms=0,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                error_msg=None,
            )
            # 更新對應的 md 之 metadata，讓它進入待審狀態
            # html_hash 也是用 (page_id, dt) 找到的，故不擔心 upsert 未使用 html_hash 當查詢條件會對不齊
            upsert_version_meta(
                page_id,
                dt,
                set_fields={
                    "enriched_md_path": cached["enriched_md_path"],
                    "md_md5_hash": cached.get("md_md5_hash"),
                    "status": "pending_review",
                    "error_msg": None,
                },
            )
            logger.info(f"[cache hit] html_hash={html_hash[:8]} 重用 {cached['enriched_md_path']} (tokens=0)")
            return {
                "status": "pending_review",
                "cache_hit": True,
                "md_path": cached["enriched_md_path"],
                "circuit_open": False,
            }

    # 若 cache miss:
    # 4. 服務級斷路：開啟期間不打 LLM
    if _guard.is_open():
        logger.warning("[circuit] on-demand enrich 暫停中，資料流動進度保持在 bronze_stored")
        return {
            "status": meta.get("status", "bronze_stored"),
            "cache_hit": False,
            "md_path": None,
            "circuit_open": True,
        }

    # 5. 下載 html、將 img tag 轉為適合 markdown 語法
    upsert_version_meta(page_id, dt, set_fields={"status": "fetched"})
    raw_html = gcs.download_text(html_path)
    plain_text = convert_img_tag_to_md_str(raw_html).get_text(" ", strip=True)

    img_uris = [img["raw_image_path"] for img in meta.get("attached_images", []) if img.get("raw_image_path")]
    # 6. 呼叫多模態 LLM
    client = client or _get_genai_client()

    t0 = time.perf_counter()
    try:
        llm, usage = _call_llm(client, page_title, plain_text, img_uris)
    except Exception as e:
        _guard.record_failure()
        # token 寫入值用 None 而非 0，以表示 LLM call 失敗了。
        log_enrichment_call(
            page_id=page_id,
            html_hash=html_hash,
            model=RESHAPE_MODEL,
            cache_hit=False,
            trigger=trigger,
            status="failure",
            latency_ms=int((time.perf_counter() - t0) * 1000),
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            error_msg=str(e),
        )
        upsert_version_meta(page_id, dt, set_fields={"status": "enrich_failed", "error_msg": str(e)})
        logger.warning(f"[enrich failed] {page_title}: {e}")
        return {"status": "enrich_failed", "cache_hit": False, "md_path": None, "circuit_open": False, "error": str(e)}

    _guard.record_success()
    log_enrichment_call(
        page_id=page_id,
        html_hash=html_hash,
        model=RESHAPE_MODEL,
        cache_hit=False,
        trigger=trigger,
        status="success",
        latency_ms=int((time.perf_counter() - t0) * 1000),
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        total_tokens=usage["total_tokens"],
        error_msg=None,
    )

    # 7. 冠上 Obsidian 的 frontmatter 後存下 md 到 GCS
    md_content = _build_markdown(llm, page_title, dt)
    md_path, _ = save_enriched_md(page_id, dt, page_title, processed_prefix, md_content)
    logger.success(f"enriched {page_title}（{usage['total_tokens']} tokens）")
    return {"status": "pending_review", "cache_hit": False, "md_path": md_path, "circuit_open": False}
