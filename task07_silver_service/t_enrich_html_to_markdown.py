"""Silver 層 Transform：純 Lazy Loading，提供 t_enrich_html_to_markdown 供 UI on-demand 呼叫。

執行流程：UI 呼叫 t_enrich_html_to_markdown(page_id, dt) → 讀 Collection onenote_note_metadata
取 html_hash → 查 html_hash 是否能快取到已存好的對應 md (命中則撈取既有 md 拋給前端、跳過 LLM call)
→ 未命中則呼叫 LLM 重整 html 生成 md
→ 存 md 到 GCS 在 upsert Collection onenote_note_metadata，更新 html note 的資料血緣。

設計要點：
- 不在 ETL 主動執行；提供 t_enrich_html_to_markdown(page_id, dt) 函式供 UI on-demand 呼叫。
- 服務級守門：LLM API 連續失敗達門檻則暫停 on-demand 一段時間，期間筆記維持
  bronze_stored、不懲罰單一筆記；取代原本綁「單筆記版本次數」的斷路器。
- regenerate quota：同一 html_hash 最多 regenerate 2 次 (per-note 成本上限)。

Required .env keys:
    AGENT_PLATFORM_USER_CREDENTIALS   Vertex AI Gemini service account JSON.
    GCP_PROJECT_ID                    GCP project ID for Vertex AI.
"""

import os
import re
import time
from pathlib import PurePosixPath

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.oauth2.service_account import Credentials
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

# 內嵌圖片以 gs:// URI 直接交給 Vertex AI 多模態判讀，副檔名 → mime type
_IMG_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
}


def _img_mime(uri: str) -> str:
    """由 URI 副檔名推出圖片 mime type；未知副檔名一律回 image/png。"""
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
    """連續失敗達門檻則開斷路一段冷卻時間。綁服務、不綁單一筆記。"""

    def __init__(self, max_consecutive_failures: int = 5, cooldown_seconds: int = 300):
        self.max = max_consecutive_failures
        self.cooldown = cooldown_seconds
        self._consecutive = 0  # 實際連續失敗次數
        self._open_until = 0.0  # 暫停到何時

    def is_open(self) -> bool:
        return time.time() < self._open_until

    def record_success(self) -> None:
        self._consecutive = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        self._consecutive += 1
        if self._consecutive >= self.max:
            self._open_until = time.time() + self.cooldown
            self._consecutive = 0
            logger.error(f"[circuit] LLM 連續失敗達 {self.max} 次，暫停 on-demand {self.cooldown}s")


_guard = _LLMServiceGuard()


# ── Gemini ────────────────────────────────────────────────────────────────────


def _get_genai_client() -> genai.Client:
    """初始化指向 Vertex AI 的 google-genai client (限定給 location=us-central1 模型用)。

    與 query_with_vector_search._get_embed_client 分開，因為該函式只調用在 us 的模型。

    Returns:
        指向 Vertex AI (location=us-central1) 的 google-genai Client 物件。

    Raises:
        EnvironmentError: 缺少 GCP_PROJECT_ID 或 AGENT_PLATFORM_USER_CREDENTIALS 時拋出。
    """
    json_path = os.getenv("AGENT_PLATFORM_USER_CREDENTIALS")
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    credentials = Credentials.from_service_account_file(json_path, scopes=scopes)

    project = os.getenv("GCP_PROJECT_ID")
    if not project or not credentials:
        raise EnvironmentError(
            "找不到 GCP_PROJECT_ID / AGENT_PLATFORM_USER_CREDENTIALS，請確認已設定在 .env 或 secret manager。"
        )
    return genai.Client(vertexai=True, project=project, location="us-central1", credentials=credentials)


def _classify_note_type(filename: str) -> str:
    """依檔名是否含日期字樣分類：有日期為 daily-log，否則 knowledge-summary。"""
    DATE_IN_FILENAME = re.compile(
        r"\d{4}-\d{2}-\d{2}|"
        r"\d{4}_\d{2}_\d{2}|"
        r"\d{8}(?!\d)|"
        r"\d{4}年\d{1,2}月\d{1,2}日"
    )
    return "daily-log" if DATE_IN_FILENAME.search(filename) else "knowledge-summary"


def convert_img_tag_to_md_str(html_content: str) -> BeautifulSoup:
    """把 html 中每個 <img> 就地換成 markdown 圖片語法 `![alt](src)`。

    Args:
        html_content (str): 原始 html 字串。

    Returns:
        BeautifulSoup: 已將 img tag 替換為 markdown 圖片語法的 soup 物件；
            後續可再 `.get_text()` 取純文字送入 LLM。
    """
    soup = BeautifulSoup(html_content, "html.parser")
    for img in soup.find_all("img"):
        alt = " ".join(img.get("alt", "").split()) or "image"
        alt = alt.replace("]", "-")  # alt 替代避免文字可能會有 ] 符號會讓 md 檔圖片顯示失敗
        src = img.get("src", "")

        # conver to string to meet the link syntax of image in a markdown file
        img.replace_with(f"\n![{alt}]({src})\n")
    return soup


def _call_llm(
    client: genai.Client, page_title: str, plain_text: str, img_uris: list[str] | None = None
) -> tuple[dict, dict]:
    """呼叫 Gemini 做多模態 document enrichment，回傳 (parsed_dict, token_usage)。失敗則 raise。

    除了文字，內文 ![]() 連結對應的原圖會以 gs:// URI 一併送入，讓 model 實際判讀圖片
    內容、產出更精準的「AI生成圖釋」。每張圖前面附一段文字標籤，標明它對應內文哪個
    `_images/<檔名>` 連結，方便 model 對齊。

    Args:
        client (genai.Client): google-genai Client 物件。
        page_title (str):  筆記標題。
        plain_text (str):  欲讓模型判讀的文本。
        img_uris (list[str] | None = None):  欲讓模型生成圖釋的圖片 URI。

    Returns:
        parsed_dict, token_usage (tuple[dict, dict]):
            parsed_dict 為 LLM enrich 過的文本；token_usage 為 token 劑量
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
    """把 LLM 回傳的 tags / alias / new_content 組成含 Obsidian frontmatter 的 md 全文。

    Args:
        llm (dict): `_call_llm()` 回傳的解析結果，含 `tags`、`alias`、`new_content`。
        page_title (str): 頁面標題，供 alias 預設值與 note_type 分類。
        dt (str): 執行日期字串，寫入 frontmatter 的 `date`。

    Returns:
        str: frontmatter + 內文的完整 markdown 字串。
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
    """Silver 層: 由 on-demand 觸發 Document enrichment。供 UI 點擊某版本時呼叫。

    依序做：regenerate 配額檢查 → 相同 html_hash 在 collection metadata 中，
    是否找得到已經生成好的對應 md (命中則撈取既有 md 拋給前端、當次 消耗 LLM call tokens=0)
    → 無命中，先由服務級斷路器檢查 LLM call 是否過量 → 無過量才允許下載 html 後呼叫 LLM 生成 md
    → 存 md 到 GCS 並 upsert metadata，更新 html note 之資料血緣。

    Args:
        page_id (str): OneNote page id。
        dt (str): 版本日期分區字串 (對齊 bronze layer Extract task 執行日)。
        trigger (str, optional): 觸發來源；`regenerate` 會略過快取、強制重生並受配額限制。
            Defaults to "on_demand".
        client (genai.Client | None, optional): 可注入的 genai client；省略則自行初始化。
            Defaults to None.

    Returns:
        dict: {status, cache_hit, md_path, circuit_open, error}；不同分支帶不同欄位。
    """
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
