"""對 archived md body 做 chunking 與多模態 embedding，產出以 md_path（archived md 路徑）為 join 鍵的 vector docs。

1. 清理 Obsidian 特有語法。
2. 對內文做兩段式 chunking。
3. 每個 chunk 都把 text 與圖片 uri 送給多模態模型 gemini-embedding-2。
4. 對回傳向量做 L2 normalize，再組成 vector doc。

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
    """初始化指向 Agent Platform 的 google-genai client，供 embedding 模型呼叫。

    這個 client 綁定 us，因為 embedding 模型只在該 region 提供服務。

    Note:
        雲端執行時憑證由 Cloud Run 的 runtime service account 以應用程式預設憑證供給，
        地端則需先解除函式內的註解區塊，改以 service account 金鑰檔初始化，否則會取不到憑證。

    Returns:
        綁定 us 的 google-genai Client 物件。

    Raises:
        EnvironmentError: 環境變數 GCP_PROJECT_ID 未設定時拋出。
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
    """把一個 wiki-link 比對結果還原成純文字，供 re.sub 逐一替換。

    優先取別名，別名不存在時才取原始連結文字。

    Note:
        優先取別名是因為別名通常是作者為該連結寫的可讀說明，語意比連結名稱本身清楚。

    Args:
        match: re.sub 傳入的比對結果物件，第一組是別名，第二組是原始連結文字。

    Returns:
        去除前後空白後的連結顯示文字。
    """
    content = match.group(1) if match.group(1) else match.group(2)
    return content.strip()


def preprocess_obsidian_content(content: str) -> str:
    """在使用 splitter 為 note 做 chunking 之前，清理以下 Obsidian 特有語法。

    共處理四種語法，前三種改寫、第四種原樣保留：
    1. 區塊錨點：整段移除，這是 Obsidian 的內部引用標記，對語意沒有貢獻。
    2. 帶顯示文字的 wiki-link：只留下顯示文字。
    3. 不帶顯示文字的 wiki-link：保留連結名稱，因為連結名本身就帶有語意，例如筆記主題。
    4. 圖片嵌入語法：原樣保留，留待向量化階段解析。

    Note:
        改用多模態模型後，圖片嵌入語法不再於此步驟移除，而是保留進 chunk，
        交由 _embed_chunks_a_markdown 解析成 gs 協定 URI 與文字一起向量化，
        讓截圖、表格與操作示意圖的語意也能被檢索到。

    Args:
        content: 一份 .md 的原始正文文字。

    Returns:
        清理後的文字，其中圖片嵌入語法原樣保留，區塊錨點已移除、wiki-link 已還原成純文字。
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

    1. 依 H1 到 H4 四層標題切開，並把命中的標題串成章節路徑。
    2. 對每個標題段落再依字元數切小。
    3. 濾掉純空白的片段。

    Note:
        第二段切分的分隔符依序是空行、換行、句號、逗號、空格，這個順序對中文較友善，
        能盡量在語意邊界斷開而不是硬切在字中間。

    Args:
        content: 已清理過 Obsidian 語法的筆記內文。
        chunk_size: 每個 chunk 的目標字元數，預設 800。
        chunk_overlap: 相鄰 chunk 的重疊字元數，預設 100。

    Returns:
        每筆含 content 與 section 兩個鍵的字典清單，前者是純文字片段，後者是該片段所屬的標題路徑。
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
    """從單一 chunk 的文字抽出所有圖片嵌入語法，解析成 GCS 上的完整位址。

    圖片放在該 .md 所在目錄底下的 _attachment 資料夾，檔名與嵌入語法內寫的一致，
    因此以筆記自己的目錄為基準即可推算出完整位址。

    Note:
        .md 內只寫檔名的圖片語法完全不更動，只在向量化時據此推算路徑，
        因此不同資料夾底下的同名圖片不會互相衝突。
        圖片在 GCS 上不存在時記一筆 warning 後略過該張，這個 chunk 仍會以剩下的內容繼續向量化，
        所以回傳的圖片數可能少於文字中出現的次數。

    Args:
        text_in_chunk: 單一 chunk 的原始文字，可能含圖片嵌入語法。
        note_file_path: 該 chunk 所屬 .md 的 GCS blob 路徑，用來推算圖片目錄。
        bucket: 已建立的 GCS Bucket 物件，用來檢查圖片是否存在。
        bucket_name: GCS bucket 名稱，用來組出完整位址。

    Returns:
        送進模型的純文字與圖片位址清單組成的 tuple。純文字已拿掉圖片嵌入語法並整理過空行，
        因為圖片改以獨立的 Part 傳入模型；該 chunk 沒有圖片時位址清單為空。
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
    """對向量做 L2 normalize，轉成長度為 1 的單位向量。

    Note:
        gemini-embedding 只有在使用預設的 3072 維時才會自動正規化，以 MRL 截斷到 1536 維時不會，
        因此計算 cosine 相似度前必須自行正規化，否則分數失真。

    Args:
        vec: embedding 模型輸出的原始向量。

    Returns:
        L2 正規化後的單位向量；傳入零向量時原樣回傳，避免除以零。
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
    """對一份筆記的每個 chunk 做多模態向量化。

    每個 chunk 各呼叫模型一次，逐一完成三件事：
    1. 從 chunk 內的圖片嵌入語法推算出各張圖在 GCS 上的位址。
    2. 依官方建議的文件格式組出 prompt，標題由筆記標題接上該 chunk 的章節路徑組成，
       文字與各張圖片再一起組成單一則多模態內容。
    3. 把模型輸出做 L2 normalize 後存回該筆 chunk。

    Note:
        多模態呼叫無法像純文字那樣把多個 chunk 併成一次請求，因此呼叫次數等同 chunk 數，
        筆記越長成本越高。prompt 格式必須與查詢時使用的格式配對，改動其中一邊就要同步改另一邊。

    Args:
        chunks: _chunk_markdown 產出的 chunk 清單，每筆含 content 與 section 兩個鍵。
        genai_client: 已初始化的 google-genai Client 物件。
        note_file_path: 該筆記的 GCS blob 路徑，供解析 chunk 內的圖片位址。
        note_title: 筆記標題，取自別名或檔名，組進 prompt 的標題部分。
        bucket: GCS Bucket 物件，用來檢查圖片是否存在。
        bucket_name: GCS bucket 名稱，預設 personal-vaults。

    Returns:
        在每筆 chunk 上補齊欄位後的清單。除原有的 content 與 section 外，
        另有 image_paths 記錄該 chunk 引用的圖片位址，沒有圖片時為空清單；
        以及 embedding 存放長度 1536 且已完成 L2 正規化的向量。
        content 保留原始寫法，圖片嵌入語法不會被拿掉。
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
    """取出一份筆記要放進 prompt 標題的名稱，優先使用別名。

    frontmatter 的別名欄位可能是清單，此時取第一個；沒有別名時改用去掉副檔名的檔名。

    Note:
        優先取別名是因為別名的命名比檔名少雜訊，例如日誌型筆記的檔名會帶有日期前綴，別名則不會，
        那串日期進到 prompt 標題只會稀釋語意。

    Args:
        note: 從 obsidian_note_metadata 查出的單筆筆記文件。

    Returns:
        可放進 prompt 標題的筆記名稱；別名與檔名都沒有時回空字串。
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
    """逐份處理待向量化的筆記，串接下載、清理、切塊與向量化四個步驟。

    每份筆記依序拉取歸檔後的正文、清掉 Obsidian 特有語法、切成 chunk，最後逐個 chunk 做多模態向量化。

    Note:
        單份筆記處理失敗時只記一筆 warning 後略過，不中斷整批，該筆記的 embedded_status 維持 false，
        下一輪會再被挑出來重試。切塊結果為空的筆記，例如空白筆記，仍算成功處理並列入回傳的對照表，
        否則每一輪都會被重新挑出來卻永遠切不出東西。
        待做清單為空時直接回傳，不會初始化 client，因此不會產生任何呼叫成本。

    Args:
        gate_list: get_embedding_gate_list 回傳的待做筆記清單，每筆含 raw_md_path 與 archived_md_path 等欄位。
        bucket_name: GCS bucket 名稱，預設 personal-vaults。
        genai_client: 已初始化的 google-genai Client 物件；省略時由 _get_genai_client 自行建立。

    Returns:
        向量文件清單與成功筆記對照表組成的 tuple。

        向量文件清單可直接寫入 note_vectors_multimodal，每筆分四組欄位。
        追蹤來源的有 md_path 記錄歸檔後的 .md 路徑並作為 data lineage 的依據、file_name 記錄檔名、
        chunk_index 為該 chunk 在筆記中的序號並從 0 起算、chunk_total 為這份筆記的 chunk 總數。
        定位語意的有 section 記錄章節路徑、content 保留 chunk 原始文字且圖片語法不更動、
        image_paths 記錄該 chunk 引用的圖片位址。向量本體是 embedding，長度 1536 且已完成 L2 正規化。
        另有 tags、note_type 與 date 三個欄位繼承自 frontmatter，供 Atlas 做前置篩選。

        成功筆記對照表的鍵是 raw_md_path，值含 md_path 供 Load 層先刪後插定位向量，
        以及 archived_md5 作為 CAS 的守衛值。處理失敗的筆記不會列入這份對照表。

        待做清單為空時，兩者都回空值。
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
                        "md_path": archived_md_path,  # 向量表 join 鍵＝人工核可後的 archived md 路徑
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
