"""Transform layer for Task06 by chunking and embedding text and images originated from notes on Obsidian.

將 Obsidian 筆記軟體產出的筆記文本與圖片，做格式轉換與資料切塊後，利用 Embedding model 向量化，
拼成 document 文檔傳給下游腳本存入 MongoDB Altas 文檔集 obsidian_vectors_multimodal。

職責：
    1. fetch_gcs_note_content(): 根據傳入的 file_path 從 GCS 重新拉取該筆記的原始 Markdown 內文 (body)
    2. preprocess_obsidian_content(): 對一份筆記 Marodown 內文清理 Obsidian 特有語法，去掉不需向量化部分。
    3. chunk_markdown(): MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter 兩段式切塊
    4. embed_chunks_a_mardown(): 把一份筆記的每個 chunk (文字＋解析後的圖片) 逐一送入
                                 多模態模型 gemini-embedding-2 生成向量。
    5. t_chunk_and_embed():
        - 接收 task01_obsidian_etl.e_scan_obsidian.py - scan_vault_gs() 回傳的 list[dict]，
            dict 代表一個 .md 的 metadata，包含 file_path。
        - 串接上述函式1~4:
            - 在函式內遍歷該 list，字典取值 file path，傳給 fetch_gcs_note_content()
            - 在函式內繼續執行 preprocess_obsidian_content()、chunk_markdown()、embed_chunks_a_mardown()
            - 回傳 list[dict]，每筆 dict 代表一個筆記所有 chunks 的完整資料 (向量化前＋後)
            - list 裝有所有 .md 的全部 chunk dicts。
環境變數依賴：
    1. Model 互動：
        AGENT_PLATFORM_USER_CREDENTIALS, GCP_PROJECT_ID
    2. GCS 讀取：
        GOOGLE_APPLICATION_CREDENTIALS

參考資料：
    - https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/embeddings/get-multimodal-embeddings

補充:
    本版已改用多模態模型 gemini-embedding-2 (multimodal, GA)，捨棄初試的 OpenAI 模型。
    因此函式經過以下邏輯重大變動：
    1. preprocess_obsidian_content(): 不再移除 ![[圖片]]，保留進 chunk。
    2. embed_chunks_a_mardown(): 新增由 ![[圖片]] 推算圖片 GCS URI (gs://.../.../_attachment/<檔名>.png)，
        與該 chunk 文字組成 multimodal Content 一起送入模型；
    3. gemini-embedding-2 輸出維度自訂 output_dimensionality=1536 (MRL 截斷)，故需 L2 normalize。
        自建 MongoDB Atlas Vector Index 的 numDimensions 需設 1536 (Atlas M0 上限為 2048)。
    4. gemini-embedding-2 不支援 task_type 參數，需把任務型式當成 instruction 寫進 prompt 文字，
        且不同任務型式有各自的格式:
        - 被檢索的文件 (本腳本，用 document 格式) → "title: {title} | text: {content}"
        - 查詢端 (使用者問題，用 query 格式)    → "task: search result | query: {query}"
        - ⚠️ 日後 dashboard_ui 前端聊天窗口，對使用者提問做 query embedding 時得用 query 格式。
────────────────────────────────────────────────────────────────
"""

import math
import os
import re
import sys
from pathlib import Path

import frontmatter
from google import genai
from google.cloud import storage
from google.cloud.storage import Bucket
from google.genai import types
from google.oauth2.service_account import Credentials
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from loguru import logger

# 多模態 embedding 模型與輸出維度設定
EMBED_MODEL = "gemini-embedding-2"
EMBED_DIM = 1536

# gemini-embedding-2 不支援 task_type 參數，需把任務型式當成 instruction 寫進 prompt 文字，
DOCUMENT_PROMPT_TEMPLATE = "title: {title} | text: {content}"

# 圖片副檔名 → MIME type (送圖片 Part 給模型時用)
_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# 抽取 Obsidian 圖片嵌入語法 ![[xxx.png]]
_IMAGE_EMBED_PATTERN = re.compile(r"!\[\[([^\]]+)\]\]")


logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
)


def _get_genai_client() -> genai.Client:
    """初始化 google-genai client。

    Returns:
        已認證、指向 Vertex AI 的 genai.Client。

    Raises:
        EnvironmentError: 缺少 AGENT_PLATFORM_USER_CREDENTIALS 或 GCP_PROJECT_ID 環境變數時。
    """
    # 先驗環境變數再建 Credentials，否則 json_path 為 None 會讓 Credentials 先拋 TypeError/FileNotFoundError
    json_path = os.getenv("AGENT_PLATFORM_USER_CREDENTIALS")
    project = os.getenv("GCP_PROJECT_ID")
    if not json_path or not project:
        raise EnvironmentError(
            "找不到 GCP_PROJECT_ID / AGENT_PLATFORM_USER_CREDENTIALS ，請確認已設定在 .env 或 secret managers 中。"
        )

    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    credentials = Credentials.from_service_account_file(json_path, scopes=scopes)
    location = "us"
    return genai.Client(vertexai=True, project=project, location=location, credentials=credentials)


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


def fetch_gcs_note_content(file_path: str, bucket_name: str = "personal-vaults") -> str:
    """從 GCS 拉取單一 .md 的 body 內文 (不含 frontmatter)。

    1. 接收 task01_obsidian_etl.e_scan_obsidian.py - scan_vault_gs() 回傳的
       list[dict] (dict = 一個 .md 的 metadata，包含 file_path)
    2. 根據傳入的 file_path 從 GCS 重新拉取該檔案的原始 Markdown 內文 (不需要frontmatter)
    3. 以 UTF-8 decode 後回傳 body 的字串。

    Args:
        file_path: GCS blob 名稱 (= scan_vault_gs() 回傳 dict 內的 file_path)。
        bucket_name: GCS bucket 名稱，預設 "personal-vaults"。

    Returns:
        該 .md 去除 frontmatter 後的 body 文字 (UTF-8)。
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(file_path)
    content_str = blob.download_as_text(encoding="utf-8")
    post = frontmatter.loads(content_str)
    return post.content


def preprocess_obsidian_content(content: str) -> str:
    """在使用 splitter 為 note 做 chunking 之前，清理以下 Obsidian 特有語法。

    1. Block ID (^8e5a21): 移除，這是 Obsidian 內部引用錨點，對語意無意義
    2. [[wiki-link|顯示文字]]: 只保留顯示文字
    3. [[wiki-link]]: 保留連結名稱 (連結名本身帶有語意，例如筆記主題)
    4. ![[image.png]]: 保留不動，留待 embed 階段解析成 GCS 圖片，與文字一起送入多模態模型

    改用多模態模型後，圖片嵌入 ![[xxx.png]] 不再於此步驟移除，而是保留進 chunk，
    交由 embed_chunks_a_mardown() 解析成 gs:// URI 與文字一起向量化，
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


def chunk_markdown(content: str, chunk_size: int = 800, chunk_overlap: int = 100) -> list[dict]:
    """為一份 note content (充滿 .md 語法文字) 做兩段式 chunking。

    第一段: MarkdownHeaderTextSplitter 依標題層級切，保留標題作為 chunk 上下文
    第二段: RecursiveCharacterTextSplitter 對超過 chunk_size 的 chunk 再切一次

    回傳 list[dict]，每筆dict包含:
        - "content": chunking 後得到的純文字片段
        - "section": 該片段所在的標題路徑 (例如:  "SQL - DQL敘述比較 > 針對一筆資料列…")

    chunk_size 的單位是字元數，不是 token 數。
    gemini-embedding-2 單筆輸入 token 上限約 2048，中英文夾雜下 chunk_size=800 字元仍安全在範圍內；
    更精準可用對應 tokenizer 實測。多模態下圖片另以 Part 送入，不佔文字 chunk_size。

    Args:
        content: 已清理的 .md 文字。
        chunk_size: 每個 chunk 的最大字元數，預設 800。
        chunk_overlap: 相鄰 chunk 的重疊字元數，預設 100。不宜過小，
                       若小於 ![[檔名|尺寸]] 圖片字串之最大可能長度，會因切太碎而漏做圖片的 embedding

    Returns:
        list[dict]，每筆含 "content" (純文字片段) 與 "section" (標題路徑字串)。
    """
    # 第一段:  設定 MarkdownHeaderTextSplitter 要識別的標題層級
    headers_to_split_on = [
        ("#", "H1"),
        ("##", "H2"),
        ("###", "H3"),
        ("####", "H4"),
    ]
    # 第一段: 依標題切
    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on,
        strip_headers=False,
    )
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
            if sub.strip():  # 過濾純空白 chunk
                chunks_a_md.append(
                    {
                        "content": sub.strip(),  # sub.strip() 是 string
                        "section": sections_str,  # sections_str 可能是 list[str] 或 ""
                    }
                )

    return chunks_a_md


def _resolve_chunk_images(
    text_in_chunk: str, note_file_path: str, bucket: Bucket, bucket_name: str
) -> tuple[str, list[str]]:
    """從一個 chunk 的文字抽出所有 Obsidian 圖片嵌入 ![[xxx.png]]，解析成 gs:// URI。

    解析規則 (依 vault 在 GCS 的儲存結構)：
      圖片放在「該 .md 所在目錄」底下的 _attachment/ 子資料夾，檔名與 ![[ ]] 內一致。
      例：note = lucky123456/from-obsidian/01-daily-logs/xxx.md
         圖片  = lucky123456/from-obsidian/01-daily-logs/_attachment/<檔名>.png
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

    # 拼裝圖檔的 GCS uri
    for m in _IMAGE_EMBED_PATTERN.finditer(text_in_chunk):
        ref = m.group(1).split("|")[0].strip()  # 去掉 ![[name.png|492]] 的尺寸/別名，留下 name.png
        base = Path(ref).name  # 雖然 Obsidian 圖片連結語法只寫檔名，但用 .name 再取一次檔名保險
        blob_path = f"{note_dir}/_attachment/{base}"
        if bucket.blob(blob_path).exists():
            image_uris.append(f"gs://{bucket_name}/{blob_path}")
        else:
            logger.warning(f"找不到圖片，略過：{blob_path}")

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


def embed_chunks_a_mardown(
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
        chunks: chunk_markdown() 產出的 list[dict]，每筆含 "content" 與 "section"。
        genai_client: 已初始化的 google-genai client。
        note_file_path: 該筆記的 GCS blob 路徑，供解析 chunk 內圖片。
        note_title: 筆記標題 (alias 或檔名)，組進 prompt 的 title。
        bucket: GCS Bucket 物件，檢查圖片是否存在。
        bucket_name: GCS bucket 名稱，預設 "personal-vaults"。

    Returns:
        在每筆 chunk dict 上新增欄位後的 list[dict]，每筆含：
        "content" 原始 chunk 文字 (含 ![[ ]])、"image_paths" gs:// URI 清單 (無圖為 [])、
        "embedding" 長度 EMBED_DIM(1536) 且已 L2 normalize。
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

    # [{"content": 原始chunk文字 (含 ![[ ]]), "section": 標題路徑,
    #   "image_paths": [...], "embedding": [1536浮點數]}, ...]
    return embedded


def t_chunk_and_embed(
    gcs_notes: list[dict],
    bucket_name: str = "personal-vaults",
) -> tuple[list[dict], list[str]]:
    """串接 fetch→preprocess→chunk→embed，產出可入庫的 vector docs 與成功處理清單。

    回傳 (all_vector_docs, processed_files)：
      - all_vector_docs：可直接寫入 MongoDB Atlas obsidian_vectors_multimodal 的 list[dict]
      - processed_files：本次「成功讀取＋切塊＋向量化 (含切塊為空)」的 file_path 清單。
        供 load 層做「先刪後插 + CAS 翻 embedding_done」只對成功的檔翻 done，
        失敗 (拋例外) 的檔不列入，下輪會重試 (embedding_done 仍為 False)。

    all_vector_docs 每筆輸出的結構：

        ```
        {
            # 來源追蹤
            "file_path":    "03_knowledge/xxx.md",
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
        gcs_notes: scan_vault_gs() 回傳的 list[dict]，每筆是一份 .md 的 metadata (須含 file_path)。
        bucket_name: GCS bucket 名稱，預設 "personal-vaults"。

    Returns:
        tuple (all_vector_docs, processed_files)：可入庫的 vector docs 清單 (每筆結構見上)，
        與本次成功處理 (含切塊為空) 的 file_path 清單。
    """
    genai_client = _get_genai_client()
    bucket = storage.Client().bucket(bucket_name)  # 供 embed 階段檢查圖片是否存在
    all_vector_docs = []
    processed_files = []  # 成功處理 的 file_path，供 load to database 時有依據可翻轉 embedding_done 的狀態(boolean)

    for gcs_note in gcs_notes:
        file_path = gcs_note["file_path"]
        logger.info(f"讀取 .md 檔內文: {file_path}")

        try:
            # 1. 從 GCS 拉取 body 內文
            raw_content = fetch_gcs_note_content(file_path, bucket_name)

            # 2. 清理 Obsidian 特有語法: BlockID 與 Wikilink
            clean_content = preprocess_obsidian_content(raw_content)

            # 3. 切塊
            chunks_a_md = chunk_markdown(clean_content)
            if not chunks_a_md:
                # 切塊為空 (例如空筆記) 仍算「成功處理」：列入 processed_files，
                logger.warning(f"切塊結果為空，視為已處理 (無 chunk): {file_path}")
                processed_files.append(file_path)
                continue

            # 4. Embedding
            #    優先使用 note 的 alias 作為 prompt 的 title，因為 alias 命名比 file name 少雜訊，
            #    例如不會參雜日誌型筆記的前綴 20250909
            alias = gcs_note.get("alias") or ""
            if isinstance(alias, list):
                alias = alias[0] if alias else ""
            note_title = alias or Path(gcs_note["file_name"]).stem

            logger.info(f"讀取、清理與切塊完成，開始向量化: {file_path}")
            embedded_chunks_a_md = embed_chunks_a_mardown(
                chunks_a_md, genai_client, file_path, note_title, bucket, bucket_name
            )

            # 5. 組合最終 vector doc
            chunk_total = len(embedded_chunks_a_md)
            for idx, ec in enumerate(embedded_chunks_a_md):
                vector_doc = {
                    # 來源追蹤
                    "file_path": file_path,
                    "file_name": gcs_note["file_name"],
                    "chunk_index": idx,
                    "chunk_total": chunk_total,
                    # 繼承自 frontmatter，供 Atlas $vectorSearch 的 filter 欄位使用
                    "tags": gcs_note.get("tags", []),
                    "note_type": gcs_note.get("note_type", ""),
                    "date": gcs_note.get("date", ""),
                    # 語意定位
                    "section": ec["section"],
                    "content": ec["content"],
                    # 該 chunk 含的圖片 gs:// URI (多模態來源追蹤，無圖則為 [])
                    "image_paths": ec.get("image_paths", []),
                    # Embed；
                    "embedding": ec["embedding"],
                }
                all_vector_docs.append(vector_doc)

            processed_files.append(file_path)  # 此檔向量化成功
        except Exception as e:
            # 失敗的檔不列入 processed_files，embedding_done 維持 False，待下次執行本函式時重試
            logger.warning(f"處理失敗: {file_path} | 原因: {e}")
            continue

    logger.info(f"向量化完成，共產出 {len(all_vector_docs)} 個 vector docs，成功處理 {len(processed_files)} 份筆記")
    return all_vector_docs, processed_files
