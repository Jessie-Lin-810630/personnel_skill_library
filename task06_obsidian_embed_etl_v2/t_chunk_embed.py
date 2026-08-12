"""對 archived md body 做 chunking 與多模態 embedding，產出以 md_path（archived md 路徑）為血緣鍵的 vector docs。

清理 Obsidian 特有語法 → 兩段式 chunking → 每 chunk 都送 text 與 圖片 uri 給多模態模型 gemini-embedding-2
→ L2 normalize → 組 vector doc。

Required .env keys:
    AGENT_PLATFORM_USER_CREDENTIALS   (On-premise only) Agent Platform gemini-embedding-2 service account key.
    GCP_PROJECT_ID                    Agent Platform project.
    GCS_USER_CREDENTIALS              (On-premise only) GCS service account JSON path (check archived images exist).
"""

import math
import os
import re
from pathlib import Path

from google import genai
from google.cloud import storage
from google.cloud.storage import Bucket
from google.genai import types
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from loguru import logger

from .e_scan_metadata import blob_name_from_uri, fetch_archived_content

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
}

# 抽取 Obsidian 圖片嵌入語法 wiki-link ![[xxx.png]]
_IMAGE_EMBED_PATTERN = re.compile(r"!\[\[([^\]]+)\]\]")


def _get_genai_client() -> genai.Client:
    """初始化 google-genai client。

    Returns:
        已認證、指向 Agent Platform 的 genai.Client。

    Raises:
        EnvironmentError: 缺少 AGENT_PLATFORM_USER_CREDENTIALS 或 GCP_PROJECT_ID 環境變數時。
    """
    # 地端測試跑下面區塊：
    # 先驗環境變數再建 Credentials，否則 json_path 為 None 會讓 Credentials 先拋 TypeError/FileNotFoundError
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
    # 先驗環境變數再建 Credentials，否則 json_path 為 None 會讓 Credentials 先拋 TypeError/FileNotFoundError
    project = os.getenv("GCP_PROJECT_ID")
    if not project:
        raise EnvironmentError("找不到 GCP_PROJECT_ID，請確認已設定在 secret manager。")
    return genai.Client(vertexai=True, project=project, location="us")


def _clean_wiki_link(match: re.Match) -> str:
    """接收 re.sub 傳入的 match 物件，回傳清理後的 wiki-link 文字。

    優先取 group(1) (別名) ，若無則取 group(2) (原始連結文字)。

    Args:
        match: re.sub 傳入的 re.Match 物件，group(1) 為別名、group(2) 為原始連結文字。

    Returns:
        去除前後空白後的連結顯示文字。
    """
    content = match.group(1) if match.group(1) else match.group(2)
    return content.strip()


def preprocess_obsidian_content(content: str) -> str:
    """在使用 splitter 為 note 做 chunking 之前，清理以下 Obsidian 特有語法。

    移除 block ID、解開 wiki-link，保留 ![[圖片]] 留待 embed 解析：
    1. Block ID (^8e5a21): 移除，這是 Obsidian 內部引用錨點，對語意無意義
    2. [[wiki-link|顯示文字]]: 只保留顯示文字
    3. [[wiki-link]]: 保留連結名稱 (連結名本身帶有語意，例如筆記主題)
    4. ![[image.png]]: 保留不動，留待 embed 階段解析成 GCS 圖片，與文字一起送入多模態模型

    **Notes:**
        改用多模態模型後，情境4 圖片嵌入 ![[xxx.png]] 不再於此步驟移除，而是保留進 chunk，
        交由 _embed_chunks_a_mardown() 解析成 `gs:// URI` 與文字一起向量化，
        讓截圖、表格、操作示意圖的語意也能被檢索。

    Args:
        content: 一份 .md 的原始 body 文字。

    Returns:
        清理後的純文字 (保留 ![[圖片]]，僅移除 block ID、解開 wiki-link)。
    """
    # 1. 移除 block ID 標記，例如 ^8e5a21、^7cb2bf
    content = re.sub(r"\s*\^[a-zA-Z0-9]{4,}\s*", " ", content)

    # 2. 圖片嵌入 ![[xxx.png]] 保留不動 (得留到 embed 階段解析用)。
    #    透過下方 wiki-link 正則以負向後查 (?<!!) 避開圖片的遷入語法 [[...]]，
    #    否則 ![[img.png]] 會被誤切成 !img.png。

    # 3. 處理 wiki-link，保留連結別名，如沒有別名則保留連結名稱
    # 正規表達式拆解:
    # (?<!!)               -> 以負向後查避開圖片嵌入的 [[...]]
    # \[\[                 -> 匹配開頭的 [[
    # (?:[^\]|]*#\^[^\s\]|]*\s*)? -> 可有可無的定位符號 (例如 #^554b8e) ，且後面可能帶有空白
    # (?:                  -> 非捕捉分組，用來處理兩種情況:
    #   [^\]|]*\|([^\]]+)  -> 情況 A: 有別名 (有 | 符號) ，我們只捕捉 | 後面的文字到 group(1)
    #   |                  -> 或者
    #   ([^\]|]+)          -> 情況 B: 沒別名，我們直接捕捉 [[ 後面的文字到 group(2)
    # )
    # \]\]                 -> 匹配結尾的 ]]
    pattern = r"(?<!!)\[\[(?:[^\]|]*#\^[^\s\]|]*\s*)?(?:[^\]|]*\|([^\]]+)|([^\]|]+))\]\]"
    content = re.sub(pattern, _clean_wiki_link, content)

    # 4. 整理多餘空行 (清理後可能留下連續空行)
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content.strip()


def _chunk_markdown(content: str, chunk_size: int = 800, chunk_overlap: int = 100) -> list[dict]:
    """對一份筆記內文做兩段式 chunking，先依標題切、再把過長段落切小。

    1. 用 MarkdownHeaderTextSplitter 依 H1 到 H4 切，並把命中的標題串成 section 路徑。
    2. 對每個標題段落再用 RecursiveCharacterTextSplitter 切小，分隔符順序對中文較友善。
    3. 濾掉純空白的片段。

    Args:
        content: 已清理過 Obsidian 語法的筆記內文。
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


def _resolve_chunk_images(
    text_in_chunk: str, note_file_path: str, bucket: Bucket, bucket_name: str = "personal-vaults"
) -> tuple[str, list[str]]:
    """從一個 chunk 的文字抽出所有 Obsidian 圖片嵌入 ![[xxx.png]]，解析成 gs:// URI。

    解析規則 (依此專案在 GCS 的儲存結構)：
      圖片放在「該 .md 所在目錄」底下的 _attachment/ 子資料夾，檔名與 ![[ ]] 內一致。
      例：note = personal-vaults/archived-notes/.../.../xxx.md
         圖片  = personal-vaults/archived-notes/.../.../_attachment/<檔名>.png
      以 note 自己的目錄解析，天然避開不同資料夾 _attachment/ 內同名 .png 的衝突。

    .md 內的圖片寫法 (只有檔名) 完全不更動，只在 embed 時據此推算 GCS 絕對路徑。
    回傳 (送入模型用的純文字, [gs:// URI, ...])；圖片不存在則記 warning 後略過。

    Args:
        text_in_chunk: 單一 chunk 的原始文字 (可能含 ![[圖片]])。
        note_file_path: 該 chunk 所屬 .md 的 GCS blob 路徑，用來推算圖片目錄。
        bucket: 已建立的 GCS Bucket 物件，用來檢查圖片是否存在。
        bucket_name: GCS bucket 名稱，用來組 gs:// URI。

    Returns:
        tuple (text_for_model, image_uris)：去除 ![[ ]] 後的純文字，
        與該 chunk 解析出的 gs:// URI 清單 (無圖為 [])。
    """
    note_dir = Path(note_file_path).parent
    image_uris = []

    # 拼裝圖檔的 GCS uri：
    # 理由：切塊後，每個 chunk 內是否有提到 image 連結的語法已不知道，
    # 從 collection *_note_metadata 中查詢 image 的路徑也不準確，
    # 故只能直接對 chunk 內文做一次 task01 也做過的事。
    for m in _IMAGE_EMBED_PATTERN.finditer(text_in_chunk):
        ref = m.group(1).split("|")[0].strip()  # 去掉 ![[name.png|492]] 的尺寸/別名，留下 name.png
        base = Path(ref).name  # 雖然 Obsidian 圖片連結語法 只寫檔名，但用 .name 再取一次檔名保險
        blob_path = f"{note_dir}/_attachment/{base}"
        if bucket.blob(blob_path).exists():
            image_uris.append(f"gs://{bucket_name}/{blob_path}")
        else:
            logger.warning(f"找不到 archived 圖片，略過：{blob_path}")

    # 圖片會改以 Part 形式傳入模型，故其他傳給模型的文字形式，可把 ![[ ]] 標記拿掉並整理空行；
    text_for_model = _IMAGE_EMBED_PATTERN.sub("", text_in_chunk)
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
    note_file_path: str,
    note_title: str,
    bucket: Bucket,
    bucket_name: str = "personal-vaults",
) -> list[dict]:
    """對一份 markdown 筆記的每個 chunk 做多模態向量化 (gemini-embedding-2)。

    多模態無法像純文字那樣把多個 chunk batch 在一次呼叫，故每個 chunk 各呼叫一次：
    1. 圖片類型：由 chunk 內的 ![[圖片]] 推算 GCS gs:// URI (note 目錄下 _attachment/)。
    2. 文字類型：依官方 document 任務格式組 prompt "title: {title} | text: {content}"，
       title = 筆記標題 + 該 chunk 的 section；文字 part 與圖片 part 組成單一 multimodal Content。
    3. 將輸出做 L2 normalize 後存回。

    Args:
        chunks: _chunk_markdown() 產出的 list[dict]，每筆含 "content" 與 "section"。
        genai_client: 已初始化的 google-genai client。
        note_file_path: 該筆記的 GCS blob 路徑，供解析 chunk 內圖片。
        note_title: 筆記標題 (alias 或檔名)，組進 prompt 的 title。
        bucket: GCS Bucket 物件，檢查圖片是否存在。
        bucket_name: GCS bucket 名稱，預設 "personal-vaults"。

    Returns:
        在每筆 chunk dict 上新增欄位後的 list[dict]，每筆含：
        "content" 原始 chunk 文字 (含 ![[ ]])、"image_paths" gs:// URI 清單 (無圖為 [])、
        "embedding" 長度 EMBED_DIM(1536) 且已 L2 normalize。

    Examples:
        >>> chunks = [{"content": "![[img.png]] 這是內容", "section": "簡介"}]
        >>> process_chunks(chunks, client, "path/note.md", "我的筆記", bucket)
        [{
            'content': '![[img.png]] 這是內容',
            'section': '簡介',
            'image_paths': ['gs://personal-vaults/note/_attachment/img.png'],
            'embedding': [0.015, -0.023, ..., 0.004]
        }]
    """
    embedded = []
    for chunk in chunks:
        text_for_model, image_uris = _resolve_chunk_images(chunk["content"], note_file_path, bucket, bucket_name)

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


def _note_title(note: dict) -> str:
    """優先使用筆記的 alias 作為 prompt 的 title，因為 alias 命名比 file name 少雜訊，

    舉例來說，alias 不會參雜日誌型筆記的前綴 '20250909...'

    Args:
        note (dict): collection obsidian_note_metadata 結果，

    Returns:
        str: 可套在 prompt title 的筆記的 alias
    """
    fm = note.get("archived_md_frontmatter", {}) or {}
    alias = fm.get("alias") or ""
    if isinstance(alias, list):
        alias = alias[0] if alias else ""
    return alias or Path(note.get("file_name", "")).stem


def t_chunk_and_embed_v2(
    gate_list: list[dict],
    bucket_name: str = "personal-vaults",
    genai_client: genai.Client | None = None,
) -> tuple[list[dict], dict[str, dict]]:
    """串接 fetch → preprocess → chunk → embed，產出 vector docs 與 {raw_md_path: {md_path, archived_md5}}。

    回傳 (all_vector_docs, embedded_by_raw_md_path)：
      - all_vector_docs：可寫入 note_vectors_multimodal 的 list[dict]，每筆血緣欄為 md_path（＝人工核可後的
        archived_md_path 值），作為向量表與 collection obsidian_note_metadata 的 join 鍵。
      - embedded_by_raw_md_path：本次成功處理（含切塊為空）的 {raw_md_path: {"md_path": archived_md_path,
        "archived_md5": archived_md_md5_hash}}。key 為 metadata 唯一鍵 raw_md_path（CAS 仍以它定位筆記），
        value 帶 md_path 供 load 層以向量欄位先刪後插、archived_md5 作 CAS 守衛值。失敗（拋例外）的檔不列入。

    all_vector_docs 每筆輸出的結構：

        ```
        {
            # 來源追蹤
            "md_path":      "gs://personal-vaults/archived-notes/.../xxx.md",  # 血緣鍵（archived md 路徑）
            "file_name":    "xxx.md",
            "chunk_index":  0,          # 從 0 開始
            "chunk_total":  6,          # 這份筆記共幾個 chunk

            # 語意定位
            "section":      "SQL - DQL敘述比較 > 針對一筆資料列…",
            "content":      " (chunk 原始文字，保留 ![[圖片]] 寫法不更動) ",
            "image_paths":  ["gs://personal-vaults/.../_attachment/xxx.png"],  # 該 chunk 含的圖片，無圖為 []

            # Embedding
            "embedding":    [...],      # list[float]，長度 1536，已 L2 normalize

            # 繼承自 frontmatter (支援 Atlas pre-filter)
            "tags":         ["MongoDB", "MySQL"],
            "note_type":    "knowledge_summary",
            "date":         "2026-04-13",
        }
        ```

    Args:
        gate_list: get_embedding_gate_list() 回傳的待做筆記清單（每筆含 raw_md_path/archived_md_path 等）。
        bucket_name: GCS bucket 名稱，預設 "personal-vaults"。
        genai_client: 已初始化的 google-genai client；省略則由 _get_genai_client() 建立。

    Returns:
        tuple (all_vector_docs, embedded_by_raw_md_path)：可入庫的 vector docs 清單 (每筆結構見上)，
        與本次成功處理 (含切塊為空) 的 {raw_md_path: {"md_path": archived_md_path, "archived_md5": md5}}。
    """
    if not gate_list:
        return [], {}  # 無待做筆記：不需初始化 genai client，直接回空
    if not genai_client:
        genai_client = _get_genai_client()
    bucket = storage.Client().bucket(bucket_name)  # 供 embed 階段檢查圖片是否存在
    all_vector_docs = []
    embedded_by_raw_md_path: dict[str, dict] = {}

    for note in gate_list:
        raw_md_path = note.get("raw_md_path")
        try:
            # 取鍵放進 try：缺鍵的畸形 gate doc 只略過該筆，不讓整個 run crash
            archived_md_path = note["archived_md_path"]
            archived_md_blob_name = blob_name_from_uri(archived_md_path, bucket_name)
            fm = note.get("archived_md_frontmatter", {}) or {}
            # 1. 從 GCS 拉取 body 內文
            body = fetch_archived_content(archived_md_path, bucket_name)

            # 2. 清理 Obsidian 特有語法: BlockID 與 Wikilink
            clean_content = preprocess_obsidian_content(body)

            # 3. 切塊
            chunks = _chunk_markdown(clean_content)
            if not chunks:
                # 切塊為空 (例如空筆記) 仍算「成功處理」
                logger.warning(f"切塊結果為空，視為已處理 (無 chunk): {archived_md_path}")
                embedded_by_raw_md_path[raw_md_path] = {
                    "md_path": archived_md_path,
                    "archived_md5": note["archived_md_md5_hash"],
                }
                continue

            # 4. Embedding
            logger.info(f"讀取、清理與切塊完成，開始向量化: {archived_md_path}")
            embedded = _embed_chunks_a_markdown(
                chunks, genai_client, archived_md_blob_name, _note_title(note), bucket, bucket_name
            )
            # 5. 組合最終 vector doc
            chunk_total = len(embedded)
            for idx, ec in enumerate(embedded):
                all_vector_docs.append(
                    {
                        "md_path": archived_md_path,  # 向量血緣鍵＝人工核可後的 archived md 路徑
                        "file_name": note.get("file_name", ""),
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
            embedded_by_raw_md_path[raw_md_path] = {
                "md_path": archived_md_path,
                "archived_md5": note["archived_md_md5_hash"],
            }
        except Exception:
            # 失敗的檔之 embedded_status 維持 False，待下次執行本函式時重試（刻意吞掉、不中斷整批）
            # 此處是該例外的終點（不再往外拋），故用 opt(exception=True) 保留 traceback 供診斷，否則會徹底遺失
            logger.opt(exception=True).warning(f"處理失敗，略過：{raw_md_path}")
            continue

    logger.info(f"向量化完成：{len(all_vector_docs)} 個 vector docs，成功處理 {len(embedded_by_raw_md_path)} 份筆記")
    return all_vector_docs, embedded_by_raw_md_path
