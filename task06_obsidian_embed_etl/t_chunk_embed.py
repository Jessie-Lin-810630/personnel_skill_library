"""
Transform layer for task06
================================================
職責: 
  1. fetch_gcs_note_content(): 
     根據傳入的 file_path 從 GCS 重新拉取該檔案的原始 Markdown 內文 (不需要frontmatter)
  2. preprocess_obsidian_content():  清理 Obsidian 特有語法，去掉不需向量化部分
  3. chunk_markdown(): MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter 兩段式切塊
  4. embed_chunks_a_mardown(): 送入一份筆記的多個 chunks，一次呼叫 OpenAI text-embedding-3-small 生成向量
  5. t_chunk_and_embed(): 
    - 接收 task01_obsidian_etl.e_scan_obsidian.py - scan_vault_gs() 回傳的 
      list[dict]， dict 代表一個 .md 的 metadata，包含 file_path。
    - 串接上述函式1~4：
        - 在函式內遍歷該 list，字典取值 file path ，傳給 fetch_gcs_note_content()
        - 在函式內繼續執行preprocess_obsidian_content()、chunk_markdown()、embed_chunks_a_mardown()
        - 回傳 list[dict]，每筆dict代表一個 chunks 的完整資料(向量化前＋後)
        - list 裝有所有 .md 的全部 dicts。
    - 交給 l_upsert_vectors.py upsert 到 MongoDB Atlas 文檔集 obsidian_vectors

# ── 未來升級提醒 ──────────────────────────────────────────────────
# 當切換到 Gemini Embedding 2 (multimodal) 時: 
#   1. preprocess_obsidian_content() 中移除圖片的那行可以拿掉: 
#        content = re.sub(, '', content)  ← 這行
#      改為: 把圖片的 GCS 路徑解析出來，下載圖片 bytes，
#      與文字一起送進 Gemini Embedding 2 的 multimodal input，
#      讓圖片的語意也被向量化。
#   2. embed_chunks_a_mardown(): 函式內替換 client.embeddings.create() 呼叫，
#      改用 google.generativeai 的 embed_content() API。
#   3. embedding 維度從 1536 改為 3072 (或依 MRL 壓縮需求調整) 。
#      MongoDB Atlas Vector Index 需要一併更新 dimension 設定。
# ────────────────────────────────────────────────────────────────
"""

from loguru import logger
import os
import sys
import frontmatter
from google.cloud import storage
from openai import OpenAI
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
import re


# 清除 loguru 預設的設定，並重新配置你想要的 Log 等級 (例如: INFO)
logger.remove()
# 印出在終端機或是會輸日誌檔 .log，以下假設是印出在終端機
logger.add(sys.stderr,
           level="INFO",
           format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>")


def _get_openai_client() -> OpenAI:
    """ 
        初始化 OpenAI client。
        OpenAI() 不傳 api_key 參數時，SDK 會自動讀取環境變數 OPENAI_API_KEY。
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("找不到 OPENAI_API_KEY 環境變數，請確認已設定在 .env 或 Secret Manager 中。")
        raise EnvironmentError("找不到 OPENAI_API_KEY 環境變數，請確認已設定在 .env 或 Secret Manager 中。"
                               )
    return OpenAI(api_key=api_key)


def _clean_wiki_link(match):
    """
    接收 re.sub 傳入的 match 物件。
    優先取 group(1) (別名) ，若無則取 group(2) (原始連結文字) 
    """
    content = match.group(1) if match.group(1) else match.group(2)
    # 使用 strip() 去除前後多餘的空白字元
    return content.strip()


def fetch_gcs_note_content(file_path: str, bucket_name: str = "personal-vaults") -> str:
    """
    1. 接收 task01_obsidian_etl.e_scan_obsidian.py - scan_vault_gs() 回傳的 
       list[dict] (dict = 一個 .md 的 metadata，包含 file_path)
    2. 根據傳入的 file_path 從 GCS 重新拉取該檔案的原始 Markdown 內文 (不需要frontmatter)
    3. 以 UTF-8 decode 後回傳字串 (不含 frontmatter，只要 body) 。
    """

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(file_path)
    content_str = blob.download_as_text(encoding="utf-8")
    post = frontmatter.loads(content_str)
    return post.content  # 只回傳 frontmatter 以外的 body 文字


def preprocess_obsidian_content(content: str) -> str:
    """
    在使用 splitter 為 note 做 chunking 之前，清理 Obsidian 特有語法: 
      - Block ID (^8e5a21): 移除，這是 Obsidian 內部引用錨點，對語意無意義
      - [[wiki-link|顯示文字]]: 只保留顯示文字
      - [[wiki-link]]: 保留連結名稱 (連結名本身帶有語意，例如筆記主題) 
      - ![[image.png]]: 若使用 text-embedding-3-small，則移除![[]]，因為模型無法向量化圖片

    # ── 未來升級提醒 ──────────────────────────────────────────────
    # 切換到 Gemini Embedding 2 multimodal 之後，
    # 圖片那行 (re.sub ) 可以改成: 
    #   解析出圖片路徑，從 GCS 下載圖片 bytes，
    #   與文字一起組成 multimodal input 送入 Gemini Embedding 2
    # 這樣圖片裡的截圖、表格、操作示意圖也能被向量化檢索。
    # ────────────────────────────────────────────────────────────
    """

    # 1. 移除 block ID 標記，例如 ^8e5a21、^7cb2bf
    content = re.sub(r'\s*\^[a-zA-Z0-9]{4,}\s*', ' ', content)

    # 2. 移除圖片嵌入 ![[xxx.png]] (文字模型無法處理圖片)
    # Gemini Embedding 2 升級後這行可以換成圖片下載 + multimodal 送入
    content = re.sub(r'!\[\[[^\]]+\]\]', '', content)

    # 3. 處理 wiki-link，保留連結別名，如沒有別名則保留連結名稱
    # 正規表達式拆解:
    # \[\[                 -> 匹配開頭的 [[
    # (?:[^\]|]*#\^[^\s\]|]*\s*)? -> 可有可無的定位符號 (例如 #^554b8e) ，且後面可能帶有空白
    # (?:                  -> 非捕捉分組，用來處理兩種情況:
    #   [^\]|]*\|([^\]]+)  -> 情況 A: 有別名 (有 | 符號) ，我們只捕捉 | 後面的文字到 group(1)
    #   |                  -> 或者
    #   ([^\]|]+)          -> 情況 B: 沒別名，我們直接捕捉 [[ 後面的文字到 group(2)
    # )
    # \]\]                 -> 匹配結尾的 ]]
    pattern = r"\[\[(?:[^\]|]*#\^[^\s\]|]*\s*)?(?:[^\]|]*\|([^\]]+)|([^\]|]+))\]\]"
    content = re.sub(pattern, _clean_wiki_link, content)

    # 4. 整理多餘空行 (清理後可能留下連續空行)
    content = re.sub(r'\n{3,}', '\n\n', content)

    return content.strip()


def chunk_markdown(content: str, chunk_size: int = 800, chunk_overlap: int = 100) -> list[dict]:
    """
    為一份 note content (充滿 .md 語法文字) 做兩段式 chunking: 
      第一段: MarkdownHeaderTextSplitter 依標題層級切，保留標題作為 chunk 上下文
      第二段: RecursiveCharacterTextSplitter 對超過 chunk_size 的 chunk 再切一次

    回傳 list[dict]，每筆dict包含: 
      - "content": chunking 後得到的純文字片段
      - "section": 該片段所在的標題路徑 (例如:  "SQL - DQL敘述比較 > 針對一筆資料列…") 

    對 text-embedding-3-small model 來說，chunk_size 的單位是字元數，不是 token 數。
    text-embedding-3-small token 上限為 8191，可能等於 5000 個字元(中英文夾雜)，更準的話可以用 tiktoken 函式庫測試。
    若未來換成長文件 (例如 32K token 的 Gemini Embedding 2) ，可以大幅放寬。
    """

    # 第一段:  設定 MarkdownHeaderTextSplitter 要識別的標題層級
    headers_to_split_on = [("#",    "H1"),
                           ("##",   "H2"),
                           ("###",  "H3"),
                           ("####", "H4"),
                           ]
    # 第一段: 依標題切
    md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on,
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
                chunks_a_md.append({"content": sub.strip(),   # sub.strip() 是 string
                                    "section": sections_str,  # sections_str 可能是 list[str] 或 ""
                                    })

    return chunks_a_md


def embed_chunks_a_mardown(chunks: list[dict], openai_client: OpenAI) -> list[dict]:
    """
    對每個一份筆記的所有 chunks 的 content 欄位呼叫 OpenAI embedding API。
    回傳的 list[dict] 增加 "embedding" 欄位，代表chunks向量化結果，為1536個浮點數。

    # ── 未來升級提醒 ──────────────────────────────────────────────
    # 切換到 Gemini Embedding 2 時，改用 google-generativeai SDK: 
    #   import google.generativeai as genai
    #   genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    #   result = genai.embed_content(
    #       model="models/gemini-embedding-2-preview",
    #       content=chunk["content"],
    #       task_type="RETRIEVAL_DOCUMENT",
    #   )
    #   embedding = result["embedding"]  # list[float]，維度最高 3072
    # 同時把 EMBEDDING_DIM 改成對應的維度，並更新 Atlas Vector Index。
    # ────────────────────────────────────────────────────────────
    """

    # OpenAI 支援 batch 送入多個字串，故以下將完整ㄧ份筆記 (list) 的所有chunks (dicts) 的字串(包在dict["content"])
    # 取出後整理放入列表，再傳入模型。
    texts = [c["content"] for c in chunks]

    # 模型input參數一次可接最長 2048 個元素(=字串)的列表，若未來單份筆記字串總數超過 2048 個 ，需要分批向量化
    response = openai_client.embeddings.create(model="text-embedding-3-small",
                                               input=texts,
                                               encoding_format="float",
                                               )  # 回傳 list[float]
    embedded = []
    for i, chunk in enumerate(chunks):
        embedded.append({**chunk,
                         "embedding": response.data[i].embedding,  # data 長度跟 texts、chunks 一樣，故可共用 i
                         })  # embedding 是 list[float]，長度 1536

    # [{"content": 字元, "section": 標題路徑,  "embedding": [1536個浮點數,...]}
    return embedded


def t_chunk_and_embed(raw_notes_metadata: list[dict],
                      bucket_name: str = "personal-vaults",
                      ) -> list[dict]:
    """
    輸出可直接 upsert 到 MongoDB Atlas obsidian_vectors 的 list[dict]。

    每筆輸出的結構: 
    {
        # 來源追蹤
        "file_path":    "03_knowledge/xxx.md",
        "file_name":    "xxx.md",
        "chunk_index":  0,          # 從 0 開始
        "chunk_total":  6,          # 這份筆記共幾個 chunk

        # 語意定位
        "section":      "SQL - DQL敘述比較 > 針對一筆資料列…",
        "content":      " (chunk 純文字) ",

        # Embedding
        "embedding":    [...],      # list[float]，長度 1536

        # 繼承自 frontmatter (支援 Atlas pre-filter) 
        "tags":         ["MongoDB", "MySQL"],
        "note_type":    "knowledge_summary",
        "date":         "2026-04-13",
    }
    """
    openai_client = _get_openai_client()
    all_vector_docs = []

    # count = 0  # ⬅️這句小量測試用，避免浪費 credits ，穩定後可刪

    for note in raw_notes_metadata:
        # 只取 file_path (= GCS blob name)
        file_path = note["file_path"]
        logger.info(f"讀取 .md 檔內文: {file_path}")

        try:
            # 1. 從 GCS 拉取 body 內文
            raw_content = fetch_gcs_note_content(file_path, bucket_name)

            # 2. 清理 Obsidian 特有語法
            clean_content = preprocess_obsidian_content(raw_content)

            # 3. 切塊
            chunks_a_md = chunk_markdown(clean_content)
            if not chunks_a_md:
                logger.warning(f"切塊結果為空，跳過: {file_path}")
                continue

            # 4. Embedding
            logger.info(f"讀取、清理與切塊完成，開始向量化: {file_path}")
            embedded_chunks_a_md = embed_chunks_a_mardown(chunks_a_md, openai_client)

            # 5. 組合最終 vector doc
            chunk_total = len(embedded_chunks_a_md)
            for idx, ec in enumerate(embedded_chunks_a_md):
                vector_doc = {
                    # 來源追蹤
                    "file_path":   file_path,
                    "file_name":   note["file_name"],
                    "chunk_index": idx,
                    "chunk_total": chunk_total,

                    # 繼承自 frontmatter，供 Atlas $vectorSearch 的 filter 欄位使用
                    "tags":      note.get("tags", []),
                    "note_type": note.get("note_type", ""),
                    "date":      note.get("date", ""),

                    # 語意定位
                    "section":  ec["section"],
                    "content":  ec["content"],

                    # Embedding (維度 1536，Atlas Vector Index 需設定 dimension: 1536)
                    "embedding": ec["embedding"],
                }
                all_vector_docs.append(vector_doc)

            # # === ⬇️小量測試用，避免浪費 credits ，穩定後可刪 ===
            # count += 1
            # if count == 2:
            #     break
            # # === ⬆️小量測試用，避免浪費 credits ，穩定後可刪 ===
        except Exception as e:
            logger.warning(f"處理失敗: {file_path} | 原因: {e}")
            continue

    logger.info(f"向量化完成，共產出 {len(all_vector_docs)} 個 vector docs")
    return all_vector_docs


# if __name__ == "__main__":
#     # 本地測試區，測試與 GCS 連線後 ETL 邏輯正確
#     from task01_obsidian_etl.e_scan_obsidian import scan_vault_gs
#     from pathlib import Path
#     from dotenv import load_dotenv
#     load_dotenv()
#     # 將路徑轉為絕對路徑，確保不論在哪個目錄執行都不會出錯
#     json_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
#     if json_path:
#         absolute_path = Path(json_path).resolve()
#         os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(absolute_path)
#     raw_notes_metadata = scan_vault_gs()
#     all_vector_docs = t_chunk_and_embed(raw_notes_metadata)
#     print(all_vector_docs[-1])
