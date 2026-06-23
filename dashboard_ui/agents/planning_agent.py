# agents/planning_agent.py

"""
職責:
  generate_learning_map(): 學習地圖初版生成
  refine_learning_map():   多輪追問調整（沿用同一 session 的脈絡）

  兩支函式共用同一套 system prompt 與模型設定，
  差異只在於是否帶入 history、以及 vector_search 的 query 來源。

依賴:
  - google-genai SDK (Vertex AI)
  - tools/vector_search.py
  - tools/chat_history.py
"""

import os
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types
from loguru import logger

from agent_tools.connect_to_google_genai import _get_genai_client
from agent_tools.query_with_vector_search import vector_search
from agent_tools.chat_history import load_chat_history, save_chat_history


# ── 常數 ──────────────────────────────────────────────────────────
PLANNING_AGENT_MODEL = "gemini-2.5-flash"   # 推理能力更強模型

SYSTEM_PROMPT = """你是一位跨領域的學習路徑規劃師，專長橫跨生物科技 (Biotech) 與資料工程 (Data Engineering) 兩個領域。

你的任務是根據使用者現有的知識狀態（來自筆記片段）與目標方向，生成一份結構化的學習路徑建議。

輸出規則:
1. 先簡短說明你對使用者目前程度的理解（1-2 句話）。(如果上一輪對話已經講過，則不必再說明一次)
2. 用階段性結構列出學習路徑，例如「第一階段：打底」「第二階段：進階」「第三階段：實戰」。
3. 每個階段列出具體技能或主題，並簡述為什麼需要這個技能。
4. 若筆記片段中已有相關知識，標註「你已有基礎」；若是全新主題，標註「待學習」。
5. 結尾簡短詢問使用者是否需要針對某個階段做更詳細的展開。

回答時請使用繁體中文，語氣專業但平易近人，避免空泛的建議，盡量具體連結到使用者筆記中出現的技術細節。
你只根據以下提供的筆記片段判斷使用者現有知識，不要憑空假設使用者會什麼。"""


def _build_context(chunks: list[dict]) -> str:
    """
    將 vector_search() 回傳的 top-K chunks 組裝成純文字 context block。
    每個 chunk 標注來源，讓模型知道每段文字出自哪份筆記。

    格式範例:
        [來源 1] 檔案: SQL筆記.md｜章節: SQL > DQL > SELECT
        SELECT 用來從資料表中選取欄位...

        [來源 2] 檔案: MongoDB筆記.md｜章節: MongoDB > Aggregation
        $match 用來過濾文件...
    """
    blocks = []
    for i, chunk in enumerate(chunks, start=1):
        header = f"[來源 {i}] 檔案: {chunk['file_name']}｜章節: {chunk['section']}"
        blocks.append(f"{header}\n{chunk['content']}")
    return "\n\n".join(blocks)


def _build_history_context_message(session_id: str, chat_history_n: int = 5) -> list[dict]:
    """
    讀取本 session 過去的 planning 對話歷史，
    以背景資訊的形式包成獨立的 user/model 對組帶入，
    避免 LLM 把過去的回應誤判為自己當下要接續輸出的內容。
    """
    history_planning_msg = load_chat_history(session_id=session_id,
                                             agent_type="planning",
                                             n=chat_history_n)

    if not history_planning_msg:
        return []

    planning_lines = "\n".join(f"  [{m['role']}] {m['parts'][0]['text']}" for m in history_planning_msg
                               )

    return [{"role": "user",
            "parts": [{"text": f"以下是這個 session 過去的學習地圖討論紀錄，供你接續調整時參考：\n\n{planning_lines}"}],
             },
            {"role": "model",
            "parts": [{"text": "好的，我已了解先前的討論脈絡，請告訴我這一輪的需求。"}],
             },
            ]


def _build_source_list(chunks: list[dict]) -> list[dict]:
    """
    組裝準備回傳給呼叫方 (Streamlit UI) 的來源清單，
    包含去重後的 "file_name + section 組合"。

    Returns:
        {
         "file_name":  "某份筆記檔案名稱.md",  
         "section":  "一個筆記資料塊所屬的文章標題",  
         "score":  "與查詢語意的相似度評分，小數點後四位"
         }
    """
    seen = set()
    # deduped = []
    sources = []
    for chunk in chunks:
        key = (chunk["file_name"], chunk["section"])
        if key not in seen:
            seen.add(key)
            # deduped.append(chunk)
            sources.append({"file_name": chunk["file_name"],
                            "section":   chunk["section"],
                            "score":     round(chunk["score"], 4),
                            })
    return sources


def generate_learning_map(query: str,
                          session_id: str,
                          planning_top_k: int = 5,
                          chat_history_n: int = 5) -> dict:
    """
    學習地圖初版生成。

    Args:
        query:      使用者描述目標方向與現有背景，例如
                    「我想從生技轉資料工程，目前熟 Python 與 SQL，請給我學習建議」
        session_id: 目前對話的 uuid4

    Returns:
        {
            "answer":  "結構化學習路徑文字",
            "sources": [{"file_name": ..., "section": ..., "score": ...}, ...]
        }
    """
    client = _get_genai_client()

    # ── Step 1: 儲存使用者訊息 ─────────────────────────────────
    save_chat_history(session_id=session_id,
                      agent_type="planning",
                      role="user",
                      message_text=query,
                      )

    # ── Step 2: 向量搜尋，取得更廣的 context（top_k=10，跨 domain）──
    logger.info(f"generate_learning_map: 執行 vector_search, query='{query[:40]}...'")
    chunks = vector_search(query=query, top_k=planning_top_k)

    if not chunks:
        answer = "目前的筆記裡沒有找到足夠的背景資訊來規劃學習路徑，可以多告訴我一些你目前熟悉的技術或工具嗎？"
        save_chat_history(session_id=session_id,
                          agent_type="planning",
                          role="model",
                          message_text=answer,
                          )
        return {"answer": answer, "sources": []}

    # ── Step 3: 將chunks 組裝回 context ───────────────────────────────────
    context_from_chunk = _build_context(chunks)

    # ── Step 4: 讀取對話歷史 ───────────────────────────────────────────────
    # 雖然這函式用於初版生成，理論上不需要過去的 planning history，
    # 但若使用者是在既有 session 重新觸發初版生成，仍保留讀取以策安全
    history_user_model_msg = _build_history_context_message(session_id, chat_history_n=chat_history_n)

    # ── Step 5: 組裝本輪 user message，包含 history + context，包成 contents 餵給 LLM 摘要。
    current_user_msg = {"role": "user",
                        "parts": [{"text": f"以下是相關筆記片段：\n\n{context_from_chunk}\n\n---\n\n使用者需求：{query}"}],
                        }
    contents = history_user_model_msg + [current_user_msg]

    # ── Step 6: 呼叫 Vertex AI (Gemini Enterprise Agent Platform) ────────────────────────────
    logger.info(f"呼叫模型 {PLANNING_AGENT_MODEL}，挾帶 {len(chunks)} 筆 chunks")
    response = client.models.generate_content(model=PLANNING_AGENT_MODEL,
                                              contents=contents,
                                              config=types.GenerateContentConfig(
                                                  system_instruction=SYSTEM_PROMPT,
                                                  temperature=0.5,   # 規劃任務需要一定彈性，但不宜過高避免天馬行空
                                              ),
                                              )
    answer = response.text

    # ── Step 7: 儲存模型回應 ───────────────────────────────────
    source_list = _build_source_list(chunks)  # 順便整理這次查到的來源筆記檔有幾個

    save_chat_history(session_id=session_id,
                      agent_type="planning",
                      role="model",
                      message_text=answer,
                      metadata={
                          "model": PLANNING_AGENT_MODEL,
                          "stage": "initial_map",
                          "retrieved_chunks": [
                              {
                                  "file_path":   c.get("file_path", ""),
                                  "chunk_index": c.get("chunk_index"),
                                  "score":       c.get("score", 0),
                              } for c in chunks
                          ],
                          "note_files": list({c["file_name"] for c in chunks}),
                      },
                      )

    logger.info("generate_learning_map: 初版地圖生成完成")
    return {"answer": answer, "sources": source_list}


def refine_learning_map(followup_query: str, session_id: str, planning_top_k: int = 5) -> dict:
    """
    多輪追問調整。

    Args:
        followup_query:      使用者的追問或調整需求，例如「把 MLOps 的部分展開」
        session_id: 目前對話的 uuid4（沿用初版生成時的同一個 session）

    Returns:
        {
            "answer":  "調整後的學習路徑文字",
            "sources": [{"file_name": ..., "section": ..., "score": ...}, ...]
        }
    """
    client = _get_genai_client()

    # ── Step 1: 儲存使用者追問 ─────────────────────────────────
    save_chat_history(session_id=session_id,
                      agent_type="planning",
                      role="user",
                      message_text=followup_query,
                      )

    # ── Step 2: 針對追問內容重新向量搜尋（例如「MLOps」會檢索到更精準的 chunk）
    logger.info(f"refine_learning_map: 執行 vector_search, query='{followup_query[:100]}...'")
    chunks = vector_search(query=followup_query, top_k=planning_top_k)

    # ── Step 3: 將chunks 組裝回 context ───────────────────────────────────
    context = _build_context(chunks) if chunks else " (這次追問沒有檢索到新的相關筆記片段，請根據先前討論的脈絡回答。) "

    # ── Step 4: 讀取過去的 planning 對話歷史（這裡才是「多輪」的關鍵）
    history_user_model_msg = _build_history_context_message(session_id, chat_history_n=5)

    # ── Step 5: 組裝本輪 user message，包含 history + context，包成 contents 餵給 LLM 摘要。
    current_user_msg = {"role": "user",
                        "parts": [{"text": f"以下是這次追問相關的筆記片段：\n\n{context}\n\n---\n\n使用者追問：{followup_query}"}],
                        }
    contents = history_user_model_msg + [current_user_msg]

    # ── Step 6: 呼叫 Vertex AI (Gemini Enterprise Agent Platform) ────────────────────────────
    logger.info(f"呼叫模型 {PLANNING_AGENT_MODEL}，多輪追問調整")
    response = client.models.generate_content(model=PLANNING_AGENT_MODEL,
                                              contents=contents,
                                              config=types.GenerateContentConfig(
                                                  system_instruction=SYSTEM_PROMPT,
                                                  temperature=0.4,
                                              ),
                                              )
    answer = response.text

    # ── Step 7: 儲存模型回應 ───────────────────────────────────
    source_list = _build_source_list(chunks)  # 順便整理這次查到的來源筆記檔有幾個

    save_chat_history(session_id=session_id,
                      agent_type="planning",
                      role="model",
                      message_text=answer,
                      metadata={
                          "model": PLANNING_AGENT_MODEL,
                          "stage": "refinement",
                          "retrieved_chunks": [
                              {
                                  "file_path":   c.get("file_path", ""),
                                  "chunk_index": c.get("chunk_index"),
                                  "score":       c.get("score", 0),
                              } for c in chunks
                          ],
                          "note_files": list({c["file_name"] for c in chunks}),
                      },
                      )

    logger.info("refine_learning_map: 追問調整完成")
    return {"answer": answer, "sources": source_list}


if __name__ == "__main__":
    # 測試重點：同一 session_id 跑滿 3 輪，觀察 history 是否正確累積、追問是否真的聚焦
    session_id = "test_docker_learning_map_0620-run3"

    # # ── 第 1 輪：初版生成 ──────────────────────────────
    # result1 = generate_learning_map(
    #     "我目前熟悉 Linux 基本指令和 Python，完全沒用過 Kubernetes，"
    #     "想學會在資料工程的場景下用 Kubernetes，例如把資料處理腳本容器化部署。",
    #     session_id
    # )
    # print(result1["answer"])
    # print(result1["sources"])

    # ── 第 2 輪：針對某一階段要求展開 ──────────────────────
    # 驗證點：模型是否記得第一輪提到的階段名稱，並且只展開該階段，不是整份重講
    # result2 = refine_learning_map(
    #     "可以把 Kubernetes 核心概念與本地環境建置 那個階段展開講細一點嗎？",
    #     session_id
    # )
    # print(result2["answer"])
    # print(result2["sources"])

    # ── 第 3 輪：改變約束條件，要求取捨 ─────────────────────
    # 驗證點：模型是否在前兩輪基礎上做精簡，而非忽略歷史重新規劃一份
    # result3 = refine_learning_map(
    #     "我只有 2 週時間，能不能幫我把學習路徑壓縮成最關鍵的部分就好？",
    #     session_id
    # )
    # print(result3["answer"])
    # print(result3["sources"])
