"""對 archived md body 做 chunking 與多模態 embedding，產出以 md_archive_path 為 join 鍵的 vector docs。

1. 對內文做兩段式 chunking。
2. 每個 chunk 解析 markdown ![](_images/x.png) 圖片，以 basename 對上 attached_images
   的 archived_image_path，並打 GCS 確認圖片仍存在。
3. 把 text 與圖片 uri 送給多模態模型 gemini-embedding-2。
4. 對回傳向量做 L2 normalize，再組成 vector doc。

chunking / embedding / normalize copy 自 task06_obsidian_embed_etl_v2（copy 而非 import，兩來源各自演化）；
與 obsidian 版差異：圖片語法為標準 markdown ![]()（非 wiki-link）、
data lineage 依據的欄位命名 md_path（存 archived md 路徑）。

Required .env keys:
    AGENT_PLATFORM_USER_CREDENTIALS   (On-premise only) Agent Platform gemini-embedding-2 service account key.
    GCP_PROJECT_ID                    Agent Platform project.
    GCS_USER_CREDENTIALS              (On-premise only) path to GCS service account JSON (for downloading archived md).

Optional .env keys:
    ONENOTE_GCS_BUCKET                GCS data lake bucket (defaults to onenote-vaults).
"""

import math
import os
import re
from pathlib import Path, PurePosixPath

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
    ".tiff": "image/tiff",
}

# OneNote 歸檔 md 的圖片語法為標準 markdown ![alt](_images/xxx.png)；取 () 內連結
_IMAGE_LINK_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _get_genai_client() -> genai.Client:
    """初始化指向 Agent Platform 的 google-genai client，供 embedding 模型呼叫。

    這個 client 綁定 us，因為 embedding 模型只在該 region 提供服務。

    Note:
        - 雲端執行時憑證由 Cloud Run 的 runtime service account 以應用程式預設憑證供給，
          地端則需先解除函式內的註解區塊，改以 service account 金鑰檔初始化，否則會取不到憑證。

    Returns:
        綁定 us 的 google-genai Client 物件。

    Raises:
        EnvironmentError: 環境變數 GCP_PROJECT_ID 未設定時拋出。
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

    1. 依 H1 到 H4 四層標題切開，並把命中的標題串成章節路徑。
    2. 對每個標題段落再依字元數切小。
    3. 濾掉純空白的片段。

    Note:
        - 第二段切分的分隔符依序是空行、換行、句號、逗號、空格，這個順序對中文較友善，
          能盡量在語意邊界斷開而不是硬切在字中間。

    Args:
        content: 從歸檔 .md 取出的筆記正文。
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
    text_in_chunk: str, archived_by_basename: dict[str, str], bucket: Bucket, bucket_name: str = "onenote-vaults"
) -> tuple[str, list[str]]:
    """從單一 chunk 的文字抽出所有 markdown 圖片語法，解析成 GCS 上的完整位址。

    OneNote 歸檔後的 .md 使用標準 markdown 圖片語法，連結多是相對路徑，因此取連結的檔名部分，
    對上該筆記 attached_images 記錄的歸檔位址，再確認該圖片在 GCS 上仍然存在，存在才收下。

    Note:
        - 圖片位址不自行推算而是查 attached_images，因為 OneNote 的歸檔位址由 task07 決定，
          無法從 .md 的相對連結還原。
        - 查到位址後仍要再確認一次檔案存在，是為了防範 metadata 有記錄、但歸檔圖片事後被移動或刪除。
        - 檔名對不上或圖片已不在 GCS 時記一筆 warning 後略過該張，這個 chunk 仍會以剩下的內容繼續向量化，
          所以回傳的圖片數可能少於文字中出現的次數。

    Args:
        text_in_chunk: 單一 chunk 的原始文字，可能含 markdown 圖片語法。
        archived_by_basename: 該筆記的圖片檔名對到其歸檔位址的對照表。
        bucket: 已建立的 GCS Bucket 物件，用來檢查圖片是否存在。
        bucket_name: GCS bucket 名稱，用來從歸檔位址剝除 gs 協定與 bucket 前綴。

    Returns:
        送進模型的純文字與圖片位址清單組成的 tuple。純文字已拿掉 markdown 圖片語法並整理過空行，
        因為圖片改以獨立的 Part 傳入模型；該 chunk 沒有對上任何圖片時位址清單為空。
    """
    image_uris = []
    for m in _IMAGE_LINK_PATTERN.finditer(text_in_chunk):
        base = PurePosixPath(m.group(1).strip()).name  # 取連結 basename，例如 _images/x.png → x.png
        archived_uri = archived_by_basename.get(base)
        if not archived_uri:
            logger.warning(f"找不到對應 archived 圖片，略過：{base}")
            continue
        # metadata 有記路徑，仍打一次 GCS 確認圖片沒被移走/刪除，存在才准送模型
        if bucket.blob(blob_name_from_uri(archived_uri, bucket_name)).exists():
            image_uris.append(archived_uri)
        else:
            logger.warning(f"archived 圖片已不存在於 GCS，略過：{archived_uri}")

    # 圖片改以 Part 形式傳入模型，故其他傳給模型的文字形式，可把 ![]() 標記拿掉並整理空行；
    text_for_model = _IMAGE_LINK_PATTERN.sub("", text_in_chunk)
    text_for_model = re.sub(r"\n{3,}", "\n\n", text_for_model).strip()
    return text_for_model, image_uris


def _normalize(vec: list[float]) -> list[float]:
    """對向量做 L2 normalize，轉成長度為 1 的單位向量。

    Note:
        - gemini-embedding 只有在使用預設的 3072 維時才會自動正規化，以 MRL 截斷到 1536 維時不會，
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
    archived_by_basename: dict[str, str],
    note_title: str,
    bucket: Bucket,
    bucket_name: str = "onenote-vaults",
) -> list[dict]:
    """對一份筆記的每個 chunk 做多模態向量化。

    每個 chunk 各呼叫模型一次，逐一完成三件事：
    1. 以 chunk 內圖片連結的檔名對上該筆記歸檔圖片在 GCS 上的位址。
    2. 依官方建議的文件格式組出 prompt，標題由筆記標題接上該 chunk 的章節路徑組成，
       文字與各張圖片再一起組成單一則多模態內容。
    3. 把模型輸出做 L2 normalize 後存回該筆 chunk。

    Note:
        - 多模態呼叫無法像純文字那樣把多個 chunk 併成一次請求，因此呼叫次數等同 chunk 數，
          筆記越長成本越高。
        - prompt 格式必須與查詢時使用的格式配對，改動其中一邊就要同步改另一邊。

    Args:
        chunks: _chunk_markdown 產出的 chunk 清單，每筆含 content 與 section 兩個鍵。
        genai_client: 已初始化的 google-genai Client 物件。
        archived_by_basename: 該筆記的圖片檔名對到其歸檔位址的對照表。
        note_title: 筆記標題，取自別名或 OneNote 頁面標題，組進 prompt 的標題部分。
        bucket: GCS Bucket 物件，用來檢查圖片是否存在。
        bucket_name: GCS bucket 名稱，預設 onenote-vaults。

    Returns:
        在每筆 chunk 上補齊欄位後的清單。除原有的 content 與 section 外，
        另有 image_paths 記錄該 chunk 引用的圖片位址，沒有圖片時為空清單；
        以及 embedding 存放長度 1536 且已完成 L2 正規化的向量。
        content 保留原始寫法，markdown 圖片語法不會被拿掉。
    """
    embedded = []
    for chunk in chunks:
        text_for_model, image_uris = _resolve_chunk_images(chunk["content"], archived_by_basename, bucket, bucket_name)

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
    """把一份筆記的 attached_images 整理成圖片檔名對到歸檔位址的對照表。

    逐張取出歸檔位址，以位址的檔名部分當鍵；沒有歸檔位址的圖片不收。

    Note:
        - 沒有歸檔位址代表該張圖片尚未被 task07 歸檔，此時 chunk 內引用它的語法會對不上而被略過，
          這份筆記的其餘內容仍會照常向量化。

    Args:
        note: get_embedding_gate_list 回傳的單筆版本文件，含 attached_images。

    Returns:
        圖片檔名對到其歸檔位址的對照表；沒有任何可用圖片時為空字典。
    """
    mapping: dict[str, str] = {}
    for img in note.get("attached_images", []) or []:
        archived = img.get("archived_image_path")
        if archived:
            mapping[PurePosixPath(archived).name] = archived
    return mapping


def _note_title(note: dict) -> str:
    """取出一份筆記要放進 prompt 標題的名稱，優先使用別名。

    frontmatter 的別名欄位可能是清單，此時取第一個；沒有別名時改用 OneNote 的頁面標題。

    Note:
        - 優先取別名是因為別名的命名比 OneNote 頁面標題少雜訊，頁面標題常帶有分頁編號或日期，
          那些字串進到 prompt 標題只會稀釋語意。

    Args:
        note: get_embedding_gate_list 回傳的單筆版本文件，含 md_frontmatter 與 page_title。

    Returns:
        可放進 prompt 標題的筆記名稱；別名與頁面標題都沒有時回空字串。
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
    """逐份處理待向量化的版本，串接下載、切塊與向量化三個步驟。

    每份筆記依序拉取歸檔後的正文、切成 chunk，最後逐個 chunk 做多模態向量化。

    Note:
        - 單份筆記處理失敗時只記一筆 warning 後略過，不中斷整批，該版本的 embedded_status 維持 false，
          下一輪會再被挑出來重試。
        - 切塊結果為空的筆記，例如空白筆記，仍算成功處理並列入回傳的對照表，
          否則每一輪都會被重新挑出來卻永遠切不出東西。
        - 待做清單為空時直接回傳，不會初始化 client，因此不會產生任何呼叫成本。

    Args:
        gate_list: get_embedding_gate_list 回傳的待做版本清單，每筆含 archived_md_path 與 md_md5_hash 等欄位。
        bucket_name: GCS bucket 名稱，預設 onenote-vaults。
        genai_client: 已初始化的 google-genai Client 物件；省略時由 _get_genai_client 自行建立。

    Returns:
        向量文件清單與成功版本對照表組成的 tuple。

        向量文件清單可直接寫入 note_vectors_multimodal，每筆分四組欄位。
        追蹤來源的有 md_path 記錄歸檔後的 .md 路徑並作為 data lineage 的依據、file_name 記錄 OneNote 頁面標題、
        chunk_index 為該 chunk 在筆記中的序號並從 0 起算、chunk_total 為這份筆記的 chunk 總數。
        定位語意的有 section 記錄章節路徑、content 保留 chunk 原始文字且圖片語法不更動、
        image_paths 記錄該 chunk 引用的圖片位址。向量本體是 embedding，長度 1536 且已完成 L2 正規化。
        另有 tags、note_type 與 date 三個欄位繼承自 md_frontmatter，供 Atlas 做前置篩選。

        成功版本對照表的鍵是 archived_md_path，值是該版本的 md_md5_hash，
        供 Load 層先刪後插定位向量並作為 CAS 的守衛值。處理失敗的版本不會列入這份對照表。

        待做清單為空時，兩者都回空值。
    """
    if not gate_list:
        return [], {}  # 無待做版本：不需初始化 genai client，直接回空
    if not genai_client:
        genai_client = _get_genai_client()
    bucket = storage.Client().bucket(bucket_name)  # 供 embed 階段檢查圖片是否存在
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
            embedded = _embed_chunks_a_markdown(
                chunks, genai_client, archived_by_basename, _note_title(note), bucket, bucket_name
            )

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
        except Exception:
            # 失敗的檔之 embedded_status 維持 False，待下次執行本函式時重試（刻意吞掉、不中斷整批）
            # 此處是該例外的終點（不再往外拋），故用 opt(exception=True) 保留 traceback 供診斷，否則會徹底遺失
            logger.opt(exception=True).warning(f"處理失敗，略過：{md_archive_path}")
            continue

    logger.info(
        f"向量化完成：{len(all_vector_docs)} 個 vector docs，成功處理 {len(embedded_md5_by_md_path)} 份 onenote 筆記"
    )
    return all_vector_docs, embedded_md5_by_md_path
