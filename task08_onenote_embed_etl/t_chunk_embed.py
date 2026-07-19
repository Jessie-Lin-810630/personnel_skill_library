"""對 archived md body 做 chunking 與多模態 embedding，產出以 md_archive_path 為血緣鍵的 vector docs。

兩段式 chunking → 每 chunk 解析 markdown ![](_images/x.png) 圖片、以 basename 對上 attached_images
的 archived_image_path → 送 text 與圖片 uri 給多模態模型 gemini-embedding-2 → L2 normalize → 組 vector doc。
chunking / embedding / normalize copy 自 task06_obsidian_embed_etl_v2（copy 而非 import，兩來源各自演化）；
與 obsidian 版差異：圖片語法為標準 markdown ![]()（非 wiki-link）、血緣欄命名 md_path（存 archived md 路徑）。

Required .env keys:
    AGENT_PLATFORM_USER_CREDENTIALS   (On-premise only) Vertex AI gemini-embedding-2 service account key.
    GCP_PROJECT_ID                    Vertex AI project.
    GCS_USER_CREDENTIALS              (On-premise only) path to GCS service account JSON (for downloading archived md).

Optional .env keys:
    ONENOTE_GCS_BUCKET                GCS data lake bucket (defaults to onenote-vaults).
"""

import math
import os
import re
from pathlib import Path, PurePosixPath

from google import genai
from google.genai import types
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from loguru import logger

from .e_scan_metadata import fetch_archived_content

# 多模態 embedding 模型與輸出維度設定
EMBED_MODEL = "gemini-embedding-2"
EMBED_DIM = 1536

# gemini-embedding-2 不支援 task_type 參數，需把任務型式當成 instruction 寫進 prompt 文字。
DOCUMENT_PROMPT_TEMPLATE = "title: {title} | text: {content}"

# 圖片副檔名 → MIME type (送圖片 Part 給模型時用)
_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
}

# OneNote 歸檔 md 的圖片語法為標準 markdown ![alt](_images/xxx.png)；取 () 內連結
_IMAGE_LINK_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _get_genai_client() -> genai.Client:
    """初始化 google-genai client。

    Returns:
        已認證、指向 Vertex AI 的 genai.Client。

    Raises:
        EnvironmentError: 缺少 AGENT_PLATFORM_USER_CREDENTIALS 或 GCP_PROJECT_ID 環境變數時。
    """
    # # 地端測試跑下面區塊：
    # # 先驗環境變數再建 Credentials，否則 json_path 為 None 會讓 Credentials 先拋 TypeError/FileNotFoundError
    # from google.oauth2.service_account import Credentials
    # json_path = os.getenv("AGENT_PLATFORM_USER_CREDENTIALS")
    # project = os.getenv("GCP_PROJECT_ID")
    # if not json_path or not project:
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
    return genai.Client(vertexai=True, project=project, location="us")


def _chunk_markdown(content: str, chunk_size: int = 800, chunk_overlap: int = 100) -> list[dict]:
    """對一份筆記內文做兩段式 chunking，先依標題切、再把過長段落切小。

    1. 用 MarkdownHeaderTextSplitter 依 H1 到 H4 切，並把命中的標題串成 section 路徑。
    2. 對每個標題段落再用 RecursiveCharacterTextSplitter 切小，分隔符順序對中文較友善。
    3. 濾掉純空白的片段。

    Args:
        content: 已取出的筆記內文。
        chunk_size: 每個 chunk 的目標字元數，預設 800。
        chunk_overlap: 相鄰 chunk 的重疊字元數，預設 100。

    Returns:
        list，每筆是含 content 純文字片段與 section 標題路徑的字典。
    """
    # 第一段:  設定 MarkdownHeaderTextSplitter 要識別的標題層級
    headers_to_split_on = [
        ("#", "H1"),
        ("##", "H2"),
        ("###", "H3"),
        ("####", "H4"),
    ]

    # 第一段: 依標題切
    md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on, strip_headers=False)
    header_chunks = md_splitter.split_text(content)

    chunks_a_md = []
    for hchunk in header_chunks:
        # 組合標題路徑字串，例如 "SQL - DQL敘述比較 > 針對一筆資料列…"
        section_parts = []
        for _, level in headers_to_split_on:
            # hchunk.metadata 是 {"H1": "...", "H4": "..."}
            if hchunk.metadata.get(level):
                section_parts.append(hchunk.metadata.get(level))
        sections_str = " > ".join(section_parts) if section_parts else ""

        # 第二段: 對過長 chunk 再切
        char_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "，", " ", ""],  # 中文友善的分隔符順序
        )
        # hchunk.page_content 是文字
        sub_chunks = char_splitter.split_text(hchunk.page_content)

        # 將 切下的 sub_chunk 之 content 與 所屬 sections_str 放在 dict，再將 dicts 裝入 list
        for sub in sub_chunks:
            if sub.strip():
                chunks_a_md.append(
                    {
                        "content": sub.strip(),
                        "section": sections_str,
                    }
                )
    return chunks_a_md


def _resolve_chunk_images(text_in_chunk: str, archived_by_basename: dict[str, str]) -> tuple[str, list[str]]:
    """從一個 chunk 的文字抽出所有 markdown 圖片 ![](_images/xxx.png)，對上 archived 圖片 gs:// URI。

    OneNote 歸檔 md 的圖片為標準 markdown 語法、連結多為相對的 `_images/<檔名>`；
    以連結 basename 對上該筆記 attached_images 的 archived_image_path（gate 已帶精確路徑，
    不需重推 GCS 路徑）。對不上 basename 者記 warning 後略過。

    Args:
        text_in_chunk: 單一 chunk 的原始文字 (可能含 ![]() 圖片)。
        archived_by_basename: 該筆記 {圖片 basename: archived_image_path(gs:// URI)} 對照表。

    Returns:
        tuple (text_for_model, image_uris)：去除 ![]() 後的純文字，
        與該 chunk 命中的 archived gs:// URI 清單 (無圖為 [])。
    """
    image_uris = []
    for m in _IMAGE_LINK_PATTERN.finditer(text_in_chunk):
        base = PurePosixPath(m.group(1).strip()).name  # 取連結 basename，例如 _images/x.png → x.png
        archived_uri = archived_by_basename.get(base)
        if archived_uri:
            image_uris.append(archived_uri)
        else:
            logger.warning(f"找不到對應 archived 圖片，略過：{base}")

    # 圖片改以 Part 形式傳入模型，故其他傳給模型的文字形式，可把 ![]() 標記拿掉並整理空行；
    text_for_model = _IMAGE_LINK_PATTERN.sub("", text_in_chunk)
    text_for_model = re.sub(r"\n{3,}", "\n\n", text_for_model).strip()
    return text_for_model, image_uris


def _normalize(vec: list[float]) -> list[float]:
    """L2 normalize 成單位向量。

    gemini-embedding 只有預設維度 3072 會自動正規化；MRL 截斷到 1536 時不會，
    cosine 相似度前需自行正規化，否則分數失真。

    Args:
        vec: 待正規化的向量。

    Returns:
        L2 正規化後的單位向量；零向量 (norm 為 0) 則原樣回傳。
    """
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def _embed_chunks_a_markdown(
    chunks: list[dict],
    genai_client: genai.Client,
    archived_by_basename: dict[str, str],
    note_title: str,
) -> list[dict]:
    """對一份 markdown 筆記的每個 chunk 做多模態向量化 (gemini-embedding-2)。

    多模態無法像純文字那樣把多個 chunk batch 在一次呼叫，故每個 chunk 各呼叫一次：
    1. 圖片類型：由 chunk 內 markdown ![]() 連結 basename 對上 archived_image_path。
    2. 文字類型：依官方 document 任務格式組 prompt "title: {title} | text: {content}"，
       title = 筆記標題 + 該 chunk 的 section；文字 part 與圖片 part 組成單一 multimodal Content。
    3. 將輸出做 L2 normalize 後存回。

    Args:
        chunks: _chunk_markdown() 產出的 list[dict]，每筆含 "content" 與 "section"。
        genai_client: 已初始化的 google-genai client。
        archived_by_basename: 該筆記 {圖片 basename: archived_image_path} 對照表。
        note_title: 筆記標題 (alias 或 page_title)，組進 prompt 的 title。

    Returns:
        在每筆 chunk dict 上新增欄位後的 list[dict]，每筆含：
        "content" 原始 chunk 文字、"image_paths" gs:// URI 清單 (無圖為 [])、
        "embedding" 長度 EMBED_DIM(1536) 且已 L2 normalize。
    """
    embedded = []
    for chunk in chunks:
        text_for_model, image_uris = _resolve_chunk_images(chunk["content"], archived_by_basename)

        # 組 multimodal parts：
        section = chunk.get("section") or ""
        title = f"{note_title} > {section}" if section else note_title
        prompt_text = DOCUMENT_PROMPT_TEMPLATE.format(title=title, content=text_for_model)
        parts = [types.Part.from_text(text=prompt_text)]
        for uri in image_uris:
            ext = Path(uri).suffix.lower()
            parts.append(types.Part.from_uri(file_uri=uri, mime_type=_MIME_BY_EXT.get(ext, "image/png")))

        response = genai_client.models.embed_content(
            model=EMBED_MODEL,
            contents=[types.Content(parts=parts)],
            config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
        )
        embedding = _normalize(response.embeddings[0].values)
        embedded.append({**chunk, "image_paths": image_uris, "embedding": embedding})
    return embedded


def _archived_by_basename(note: dict) -> dict[str, str]:
    """把一份筆記的 attached_images 整理成 {archived 圖片 basename: archived_image_path} 對照表。

    只收有 archived_image_path 的項；供 chunk 內 markdown ![]() 連結以 basename 對上。

    Args:
        note (dict): gate 回傳的版本 dict，含 attached_images。

    Returns:
        dict: {basename: archived_image_path(gs:// URI)}。
    """
    mapping: dict[str, str] = {}
    for img in note.get("attached_images", []) or []:
        archived = img.get("archived_image_path")
        if archived:
            mapping[PurePosixPath(archived).name] = archived
    return mapping


def _note_title(note: dict) -> str:
    """優先使用筆記的 alias 作為 prompt 的 title，因為 alias 命名比 page_title 少雜訊。

    Args:
        note (dict): gate 回傳的版本 dict，含 md_frontmatter 與 page_title。

    Returns:
        str: 可套在 prompt title 的筆記標題。
    """
    fm = note.get("md_frontmatter", {}) or {}
    alias = fm.get("alias") or ""
    if isinstance(alias, list):
        alias = alias[0] if alias else ""
    return alias or note.get("page_title", "")


def t_chunk_and_embed_onenote(
    gate_list: list[dict],
    bucket_name: str = "onenote-vaults",
    genai_client: genai.Client | None = None,
) -> tuple[list[dict], dict[str, str]]:
    """串接 fetch → chunk → embed，產出 vector docs 與 {md_archive_path: 本次 md_md5_hash}。

    回傳 (all_vector_docs, embedded_md5_by_md_path)：
      - all_vector_docs：可寫入 note_vectors_multimodal 的 list[dict]，每筆帶 md_path（= md_archive_path），
        作為與 collection onenote_note_metadata 的數據血緣。
      - embedded_md5_by_md_path：本次成功處理（含切塊為空）的 {md_archive_path: md_md5_hash}，
        供 load 層做「先刪後插 + CAS 翻 embedded_status」只對成功的檔翻 done，
        失敗 (拋例外) 的檔不列入，下輪會重試。

    all_vector_docs 每筆輸出的結構：

        ```
        {
            "md_path":      "gs://onenote-vaults/archived-notes/.../n.md",  # 血緣鍵（archived md 路徑）
            "file_name":    "n",          # page_title
            "chunk_index":  0,            # 從 0 開始
            "chunk_total":  6,            # 這份筆記共幾個 chunk
            "section":      "SQL - DQL敘述比較 > 針對一筆資料列…",
            "content":      " (chunk 原始文字) ",
            "image_paths":  ["gs://onenote-vaults/.../_images/xxx.png"],  # 該 chunk 命中的 archived 圖片
            "embedding":    [...],        # list[float]，長度 1536，已 L2 normalize
            "tags":         ["MongoDB"],  # 繼承自 md_frontmatter，支援 Atlas pre-filter
            "note_type":    "knowledge_summary",
            "date":         "2026-04-13",
        }
        ```

    Args:
        gate_list: get_embedding_gate_list() 回傳的待做版本清單（每筆含 md_archive_path/md_md5_hash 等）。
        bucket_name: GCS bucket 名稱，預設 "onenote-vaults"。
        genai_client: 已初始化的 google-genai client；省略則由 _get_genai_client() 建立。

    Returns:
        tuple (all_vector_docs, embedded_md5_by_md_path)：可入庫的 vector docs 清單 (每筆結構見上)，
        與本次成功處理 (含切塊為空) 的 {md_archive_path: md_md5_hash}。
    """
    if not gate_list:
        return [], {}  # 無待做版本：不需初始化 genai client，直接回空
    if not genai_client:
        genai_client = _get_genai_client()
    all_vector_docs = []
    embedded_md5_by_md_path: dict[str, str] = {}

    for note in gate_list:
        md_archive_path = note.get("archived_md_path")
        try:
            # 取鍵放進 try：缺鍵的畸形 gate doc 只略過該筆，不讓整個 run crash
            md_md5_hash = note["md_md5_hash"]
            fm = note.get("md_frontmatter", {}) or {}
            archived_by_basename = _archived_by_basename(note)
            # 1. 從 GCS 拉取 archived md body 內文
            body = fetch_archived_content(md_archive_path, bucket_name)

            # 2. 切塊
            chunks = _chunk_markdown(body)
            if not chunks:
                # 切塊為空 (例如空筆記) 仍算「成功處理」
                logger.warning(f"切塊結果為空，視為已處理 (無 chunk): {md_archive_path}")
                embedded_md5_by_md_path[md_archive_path] = md_md5_hash
                continue

            # 3. Embedding
            logger.info(f"讀取、切塊完成，開始向量化: {md_archive_path}")
            embedded = _embed_chunks_a_markdown(chunks, genai_client, archived_by_basename, _note_title(note))

            # 4. 組合最終 vector doc
            chunk_total = len(embedded)
            for idx, ec in enumerate(embedded):
                all_vector_docs.append(
                    {
                        "md_path": md_archive_path,
                        "file_name": note.get("page_title", ""),
                        "chunk_index": idx,
                        "chunk_total": chunk_total,
                        "tags": fm.get("tags", []),
                        "note_type": fm.get("type", ""),
                        "date": fm.get("date", ""),
                        "section": ec["section"],
                        "content": ec["content"],
                        "image_paths": ec.get("image_paths", []),
                        "embedding": ec["embedding"],
                    }
                )
            embedded_md5_by_md_path[md_archive_path] = md_md5_hash
        except Exception as e:
            # 失敗的檔之 embedded_status 維持 False，待下次執行本函式時重試
            logger.warning(f"處理失敗，略過：{md_archive_path} | 原因：{e}")
            continue

    logger.info(
        f"向量化完成：{len(all_vector_docs)} 個 vector docs，成功處理 {len(embedded_md5_by_md_path)} 份 onenote 筆記"
    )
    return all_vector_docs, embedded_md5_by_md_path
