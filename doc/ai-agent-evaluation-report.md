# Phase III AI Agent 架構決策文件

> **專案**: Personal Skill Dashboard — AI Knowledge Agent  
> **文件版本**: v1.0  
> **決策日期**: 2026-05-28  
> **適用階段**: Phase III — Establish Plugin AI Agents  
> **目標 AI 代理功能**:   

    1. 筆記摘要: 對指定筆記或主題產生摘要  
    2. 筆記查詢: 語意搜尋,根據使用者輸入的情境文字找到相關筆記片段  
    3. 個人化學習地圖生成: 根據使用者現有知識狀態 (來自筆記內容) 生成建議學習路徑

---

## 目錄

1. [決策步驟大綱](#1-決策步驟大綱)
2. [Step 1: 三個功能的技術性質分析](#2-step-1-三個功能的技術性質分析)
3. [Step 2: Agent 數量決策](#3-step-2-agent-數量決定-)
4. [Step 3: Intent Routing 層設計](#4-step-3-intent-routing-層設計-)
5. [Step 4: Routing 多輪對話策略](#5-step-4-routing-多輪對話策略-)
6. [Step 5: LLM 廠商選型](#6-step-5-llm-廠商選擇-)
7. [Step 6: Gemini 模型版本選型](#7-step-6-gemini-模型版本選型-)
8. [Step 7: Agent 框架選型](#8-step-7-agent-框架-framework-選型-)
9. [Step 8: chat_history Collection Schema 設計](#9-step-8-chat_history-collection-schema-設計-)
10. [Step 9: 最終架構總結](#10-step-9-最終架構總結-)
    - [決策總表](#決策總表)
    - [完整資料流](#完整資料流)
    - [Tools](#tools-層python-functions)
    - [Service Account 權限規劃](#sa-權限規劃)
    - [預計開發順序](#預計開發順序)
---

## 1. 決策步驟大綱

| Step | 決策主題 | 核心問題 |
|------|----------|----------|
| Step 1 | 功能技術性質分析 | 三個功能在技術上有何根本差異？ |
| Step 2 | Agent 數量 | 用 1 個還是 2 個 Agent？ |
| Step 3 | Intent Routing 策略 | 單一入口下如何分流到正確 Agent？ |
| Step 4 | Routing 多輪對話策略 | 多輪對話中 routing 如何感知上下文？ |
| Step 5 | LLM 廠商選型 | Claude API vs Gemini Vertex AI？ |
| Step 6 | Gemini 模型版本選型 | 各角色使用哪個具體模型版本？ |
| Step 7 | Agent 框架選型 | 用哪個框架或手刻？ |
| Step 8 | chat_history Schema | MongoDB 對話紀錄集合如何設計？ |
| Step 9 | 最終架構總結 | 決策總表、資料流、開發順序 |

---

## 2. Step 1: 三個功能的技術性質分析

### 用途與目標

在進行任何架構決策之前，先釐清三個功能在技術上的根本差異。這個分析結果會直接影響 Agent 數量與框架選型。

### 功能性質要求比較

| 功能 | 核心操作 | 需要 Vector Search？ | 需要多輪對話？ | 輸出結構複雜度 |
|------|----------|----------------------|----------------|----------------|
| **筆記摘要** | Retrieve chunks → 壓縮摘要 | ✅ (加上 file_name 預過濾)  | 低 (單輪為主)  | 低 (純文字段落)  |
| **筆記查詢** | Query → top-K chunks → 列出來源 | ✅ | 低 (單輪為主)  | 中 (來源清單 + 片段)  |
| **學習地圖生成** | 分析知識全貌 → 推理缺口 → 生成路徑 | ✅ (且需更廣的 context)  | 高 (需多輪澄清)  | 高 (結構化路徑圖)  |

### 學習地圖互動模式規劃
討論 3 種互動模式: 
- A. 單輪輸出: 使用者輸入「我想往 MLOps 方向發展」，系統一次輸出完整學習路徑，不追問。
- B. 引導式多輪: Agent 先問「你目前哪些工具用得熟？目標是 3 個月還是 6 個月？」，收集到足夠資訊後再生成地圖。
- C. 都要支援: 先給一個初步地圖，使用者可以繼續追問調整。

針對學習地圖功能，預計與使用者用 **C 模式** 互動: 
- 先給一個初步地圖，使用者可以繼續追問調整。
- 因此，這個模式需要獨立的狀態管理機制，是後續是否拆分 Agent 的主要依據。

### Agents 能力分類

- **筆記摘要、筆記查詢**: 屬於`檢索導向`，流程固定、單輪為主，使用者給問題或主題，系統 retrieve 相關片段，LLM 做整合輸出。
- **學習地圖生成**: 屬於`推理導向`，需要理解使用者目前知識狀態、目標方向，再跨 domain (生技 + 資料工程) 做路徑規劃，可能需要引導式多輪問答。


---

## 3. Step 2: Agent 數量決定 [🏠](#目錄)

### 用途與目標

根據 Step 1 的技術性質差異，評估是否需要將三個功能分配給不同數量、種類的 Agent，進而評估，分配方式對架構複雜度與維護成本的影響。

### 方案比較

| 面向 | 方案 A: 1 個 Agent | 方案 B: 2 個 Agent |
|------|-------------------|-------------------|
| **架構描述** | 單一 agent，用 system prompt + tool routing 分辨三種功能 | Agent 1 負責摘要＋查詢；Agent 2 負責學習地圖 (含多輪狀態)  |
| **複雜度** | 低，維護一套 prompt、一套 session state | 中，需管理兩套 prompt 與各自的 chat history |
| **功能邊界** | 靠 prompt 區分，邊界可能模糊 | 邊界由 UI 或 routing logic 強制切割 |
| **多輪狀態管理** | 共用同一個 chat_history，推理脈絡混在查詢紀錄裡 | 學習地圖有獨立 session，狀態乾淨 |
| **Cloud Run 部署** | 1 個 container，資源管理簡單 | 可以是同一個 Streamlit app 內的模組切分，不一定要兩個 containers |
| **開發工期** | 較短 | 稍長，但結構更清晰 |
| **未來擴充** | 加新功能會讓 single agent prompt 越來越肥 | 各 agent 職責單一，可獨立迭代 |

### 最終決定: 方案 B — 2 個 Agents

**選擇原因: **
- 學習地圖需要多輪互動 (step 1 決定的模式 C)，與摘要/查詢的「單輪 retrieve」性質差異明顯，若混在同一個 agent 會導致狀態管理複雜度爆炸
- 互動頁面是全新的開發 streamlit page (page 3)，沒有舊技術債，適合從架構上做對
- 不論幾個Agents，均部署在同一個 page，且用 Cloud Run Service 服務部署在phase II 的 container，部署成本不會因此而變。

**實作方式: **

```
Streamlit home page (app 入口)
├──── Streamlit page 2
└──── 同一個 Streamlit Page 3
            ├──── Agent 1: RAG Agent (筆記摘要 + 語意查詢) 
            │           # 單輪為主，chat_history 輕量
            └──── Agent 2: Planning Agent (學習地圖) 
                        # 維護獨立 session state，多輪推理
```

---

## 4. Step 3: Intent Routing 層設計 [🏠](#目錄)

### 用途與目標

確定在 page 3 設立單一對話框入口後，便需要設計一個 Routing 層在使用者輸入 (user prompt) 後、進入 Agent 之前，判斷本次輸入應交給哪個 Agent 處理。

### 單一對話框入口

page 3 UI 介面採用**單一對話框**，而不是在 Page 3 讓使用者自己用 tab 切分兩個 Agent。所以，使用者只需在同一個 chat 介面輸入，由 Routing 層自動判斷意圖。

### Routing 方案比較

| 方案 | 做法 | 優點 | 缺點 |
|------|------|------|------|
| **R1. Keyword/Rule-based** | 偵測關鍵字 (如「學習路徑」、「建議」、「怎麼學」) 判斷 intent | 零成本、無延遲 | 中英文夾雜時容易誤判，使用者措辭多變 |
| **R2. LLM classifier** | 用輕量 LLM call 先判斷 intent，回傳 rag_agent 或 planning_agent | 準確率高，能理解語意 | 每次多一個 API call，增加延遲與費用 |
| **R3. Claude tool_use routing** | 把兩個 agent 的能力定義成 tools，讓 LLM 自己決定 call 哪個 | 原生支援、意圖與執行合一 | 對框架依賴較深，初期設計複雜度較高 |

### 最終決定: R1 + R2 混合

**選擇原因: **
- 此專案使用者僅為本人，意圖通常不會太模糊，keyword 快篩可覆蓋大多數情境
- 只有真正模糊以致R1無法判斷的情況才升級到 R2.LLM 判斷，兼顧準確率與成本

**運作邏輯: **

```
使用者輸入 (user prompt)
    ↓
R1 keyword/Rule-based 快篩
    ├── 明確命中學習地圖關鍵字 → Agent 2
    ├── 明確命中查詢/摘要關鍵字 → Agent 1
    └── 模糊 / 無法判斷 → Call R2 LLM 做最終判斷
```
*R2 LLM 模型選擇 gemini-2.5-flash-lite，原因見: *

---

## 5. Step 4: Routing 多輪對話策略 [🏠](#目錄)

### 用途與目標

在多輪對話情境下，單純看當前輸入可能無法正確判斷 intent (例如「根據這些筆記，幫我規劃學習路徑」隱含了上一輪的查詢結果) 。需要決定 Routing 層運作時，是否要參考對話歷史 (chat history)。

### 方案比較

| 選項 | 做法 | 優點 | 缺點 |
|------|------|------|------|
| **A. 每輪獨立判斷** | 每次輸入重新做 routing，不參考上一輪 | 邏輯最簡單 | 無法感知 agent 切換的上下文 |
| **B. 帶 history 做 routing** | Routing 層在判斷時參考最近 N 輪 chat_history | 能感知上下文切換，準確率更高 | 需要讀取 chat_history，多一次 DB query |
| **C. 固定 session 模式** | 使用者主動切換模式 (如輸入 `/map` 指令) ，同一 session 不自動切換 | 最可預測 | 使用者體驗較差，需要記住指令 |

### 最終決定: 選項 B — 帶上最近 N 輪 history 做 routing

**選擇原因: ** 希望系統能自然感知上下文切換，不需要使用者記憶指令或手動切換模式，讓`使用者體驗更流暢`。

**參數設定: **
- N = 3 (預設值，之後若需要，可透過環境變數調整) 
- 讀取條件: 同一 session_id，timestamp 降序取前 N*2 筆 (user + model 各一筆) 

---

## 6. Step 5: LLM 廠商選擇 [🏠](#目錄)

### 用途與目標

決定整個 AI Agent 系統使用哪家 LLM 廠商，影響 API 費用管理、GCP 整合方式、credentials 管理複雜度。

### 方案比較

| 評估維度 | Claude (`claude-sonnet-4-5`) | Gemini on Vertex AI |
|----------|------------------------------|---------------------|
| **多語言 (中英夾雜) ** | 強 | 強 |
| **長 context 處理** | 200K token | 1M token (Gemini 2.5 系列)  |
| **結構化輸出** | 支援 (prompt 引導或 tool_use)  | 支援 (原生 response_schema)  |
| **GCP 整合度** | 需獨立 Anthropic API，不在 GCP 生態內 | 原生 GCP 服務 |
| **Python SDK 成熟度** | anthropic 官方 SDK，文件完整 | google-genai 官方 SDK，文件完整 |
| **RAG 場景適用性** | 成熟 | 成熟 |
| **計費管理** | 獨立 Anthropic 帳單，見下方官方定價 | 統一在 GCP billing，見下方官方定價 |
| **Credentials 管理** | 需額外存 ANTHROPIC_API_KEY 至 Secret Manager | 可沿用現有 SA，調整 IAM role 授權即可調用 Vertex AI，無需額外 API key |

> 官方定價參考: 
> - Anthropic: https://www.anthropic.com/pricing
> - Vertex AI: https://cloud.google.com/vertex-ai/generative-ai/pricing

### 最終決定: Gemini on Vertex AI

**選擇原因: **
- Vertex AI 已在專案中 enabled； 而 Anthropic API key 尚未創立。
- 現有 Cloud Run Service Account 架構熟悉，新建一支專用 SA 或從 IAM 調整現有 SA 的 role 即可，不需要從 Vertex AI platform 創建與管理額外的 API key。
- GCP 帳單統一，`成本追蹤簡單，架構說明一致乾淨`。

**SDK 選擇: ** `google-genai` (Gen AI SDK) 

> 官方文件: https://googleapis.github.io/python-genai/

> ⚠️ 討論過程中發現: `google-cloud-aiplatform` (舊 Vertex AI SDK) 在 [2026 年 6 月後不再更新 Gemini 的 GenerativeModel，新專案必須使用 `google-genai`](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start/libraries)。

---

## 7. Step 6: Gemini 模型版本選型 [🏠](#目錄)

### 用途與目標

在確定使用 Gemini on Vertex AI 後，針對 Routing 層、Agent 1、Agent 2 三個角色分別選擇最適合的模型版本，在能力、速度、成本三者間取得平衡。

### 可用模型比較

| 模型 | Context Window | 適合場景 | 相對成本 | 狀態 |
|------|---------------|----------|----------|------|
| `gemini-2.0-flash-001` | 1M token | — | 低 | ❌ 將於 2026/06/01 停用 |
| `gemini-2.5-flash-lite` | 1M token | 快速回應、`低延遲`的分類、轉派與初階分類 (routing)、單輪 RAG | 低 (輸入比flash便宜 3 倍，輸出比flash便宜 6.25 倍) | ✅ General Availability (global、US、部分Europe)，停用預期日期落在 2026 年 10 月之後 |
| `gemini-2.5-flash` | 1M token | 推理任務、結構化輸出、`更長文本`、`多輪對話` | 中 | ✅ General Availability (global、US、Canada、Europe、Asia Pacific)，停用預期日期落在 2026 年 10 月之後 |
| `gemini-2.5-pro` | 1M token | 複雜推理、長 context 分析 | 高 | ✅ General Availability (global、US、Canada、部分Europe、Asia Pacific)，停用預期日期落在 2026 年 10 月之後 |


### 定價 (截至 20260528 為止)
| 模型名稱 | 輸入價格美金 (Input / 1M Tokens) | 輸出價格美金 (Output / 1M Tokens) | 價格降幅 |
|--------|---------------------------------|--------------------|----------|
|Gemini 2.5 Flash | $0.30 | $2.50 | 基準|
|Gemini 2.5 Flash-Lite | $0.10 | $0.40 | 輸入便宜 3 倍，輸出便宜 6.25 倍！

> 參考來源: [規格](https://cloud.google.com/vertex-ai/generative-ai/docs/learn/models) 與 [定價](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing?_gl=1*1mc92t5*_ga*MTEwMzU3Nzc5NS4xNzc2MzA1MzUw*_ga_WH2QY8WWF5*czE3Nzk5NDgyOTAkbzg1JGcxJHQxNzc5OTUzNTQ1JGo0MSRsMCRoMA..&hl=zh-tw)


### 最終決定: 各角色模型分配

| 角色 | 選用模型 | 理由 |
|------|----------|------|
| **Routing 層** | `gemini-2.5-flash-lite` | 只需判斷 intent，輸出極短，速度與成本優先 |
| **Agent 1: RAG Agent** | `gemini-2.5-flash-lite` | 單輪 RAG，retrieve 完就生成，不需複雜推理 |
| **Agent 2: Planning Agent** | `gemini-2.5-flash` | 跨 domain 推理、多輪狀態、結構化學習地圖輸出，需要更強的推理能力 |

**不選 `gemini-2.5-pro` 的原因: ** 個人 side project 成本考量，`gemini-2.5-flash` 的推理能力對學習地圖生成已足夠，後續可視需要升級。

---

## 8. Step 7: Agent 框架 (framework) 選型 [🏠](#目錄)

### 用途與目標

決定是否引入第三方 Agent 框架、或是手刻所有邏輯以取得最高掌控度，框架的要能夠做的事情有:
- 處理多輪對話狀態管理 (Multi-turn)
- tool/ function calling (向量搜尋、筆記摘要後寫檔到 GCS 等)
- routing 協調
- 對話紀錄持久化到 MongoDB Altas 等通用邏輯，

### 候選框架比較
比較手刻 、 LangChain 、 LlamaIndex 與 Google ADK (Google Agent Development Kit) 四種。
| 面向 | 手刻 | LangChain | LlamaIndex | Google ADK |
|------|------|-----------|------------|------------|
| **學習成本** | 低 (只需熟悉 google-genai SDK)  | 中 | 中 | 中 |
| **MongoDB 原生整合** | ❌ 手刻 | ✅ langchain-mongodb | ✅ llama-index-vector-stores-mongodb | ❌ 手刻 |
| **Vertex AI 原生整合** | ✅ | ✅ langchain-google-vertexai | ✅ llama-index-llms-vertex | ✅ 最佳 |
| **Multi-agent routing** | 手刻 | 可做，設定繁瑣 | 可做，RouterQueryEngine | ✅ 原生支援 |
| **多輪狀態 (multi-run) 管理** | 手刻 | ✅ | ✅ | ✅ |
| **社群資源** | — | 最豐富 | 豐富 | 較少 (框架較新)  |
| **Portfolio 展示價值** | 高 (有助於讓自己展示對底層理解)  | 中 | 中 | 高 (展示 GCP 生態掌握)  |
| **維護穩定性** | 高 | 中 (API 常變動)  | 中 | 中 (框架較新)  |
| **其他** | - | - |  以 RAG 為核心設計的框架，專精在資料檢索、摘要、複雜關聯查詢 | Google 官方推出的 agent 框架 |


> 官方文件: 
> - LangChain: https://python.langchain.com/docs/introduction/
> - LlamaIndex: https://docs.llamaindex.ai/en/stable/
> - Google ADK: https://google.github.io/adk-docs/

### 最終決定: 手刻 + `google-genai` SDK，盡可能貼近 GCP 生態

**選擇原因: **
- 需求規模單純 (個人使用、三個功能) ，手刻量實際應該可控
- 不引入第三方框架，減少版本迭代帶來的維護成本 (LangChain API 常變動) 
- 貼近 GCP 生態優先，`google-genai` SDK 是 Google 官方推薦的現行 SDK
- 最高掌控度，每一層邏輯都自己撰寫，好好練習 RAG pipeline 與 Agent 架構

---

## 9. Step 8: chat_history Collection Schema 設計 [🏠](#目錄)

### 用途與目標

設計 MongoDB Atlas `chat_history` collection，需同時服務三個角色: 
- Routing 層 (讀取最近 N 輪判斷 intent) 
- Agent 1 (讀寫 rag 對話紀錄) 
- Agent 2 (讀寫 planning 對話紀錄，需維護跨輪 session 脈絡)   

同時需考量`安全性與儲存防護`，避免`MongoDB 向量化知識庫被污染`、`API 被非授權者狂打而費用暴增`、`MongoDB 存的對話紀錄庫被污染`。

### 設計原則
因為需要服務三層，為了確保 Agent 在讀取 chat_history 時能找到正確的、來自同個 Agent 的紀錄，需要考量以下三個欄位，保護文檔的可追溯性。

| 原則 | 說明 |
|------|------|
| **session_id** | 使用者點擊「開新對話」時生成 uuid4，區分不同次對話 |
| **agent_type** | 每筆紀錄標記來源 (router / rag / planning) ，各 Agent 只讀自己相關的歷史 |
| **role 格式** | 直接對齊 `google-genai` SDK 的 `contents` 格式 (user / model) ，之後，讀取後就可直接送進 VertexAI API、不需轉換 |
> google SDK content 參考資料: https://adk.dev/streaming/streaming-tools/?query=contents  

### 安全防護策略

由於 phase II 用 streamlit 建立的 dashboard-UI page 1~2 部署在 Cloud Run Service 時，設定為 public authentication，但 page 3 是屬於有個人化專有資產的服務，為避免這個知識庫資產被污染到，page 3 應需額外防護: 

| 防護層 | 做法 | 優先度 |
|--------|------|--------|
| **層 1: 身份驗證** | 用 Streamlit 建一個 `st.login()` 串接 Google OAuth | 🔴 1 |
| **層 2: Rate Limiting** | Streamlit session state 記錄 VertexAI API 呼叫次數，超過閾值拒絕呼叫 LLM | 🟡 2 |
| **層 3: MongoDB 寫入保護** | 單一 session 上限 100 筆；單筆 content 上限 2000 字元 | 🟢 3 |

> `st.login()` 官方文件: https://docs.streamlit.io/develop/api-reference/user/st.login

### Session 生命週期決策

| 選項 | 說明 | 安全風險 |
|------|------|----------|
| A. 每次重整是新 session | 對話紀錄乾淨分隔，但學習地圖脈絡會斷 | 🟡 中 (如不對 page 3 控管訪問權限則惡意用戶可以不斷重整、加速 MongoDB資料增長) |
| B. 以天為單位 | 同天重整不斷，MongoDB 增長較慢 | 🟢 較低 |
| **C. 手動開新對話** ✅ | 使用者主動控制，MongoDB 增長最可預測 | 🟢 最低 |

**選擇 C 的原因: ** 選 C 讓學習地圖的多輪脈絡不因重整而斷掉，開發期間也方便測試；session 生命週期完全由使用者掌控，MongoDB 增長速度最可預測。


### 最終決定: Schema 欄位示意

```json
{
  "_id": "ObjectId (自動生成) ",
  "session_id": "uuid4，使用者點擊「開新對話」時生成",
  "agent_type": "router | rag | planning",
  "role": "user | model",
  "content": "訊息文字內容 (上限 2000 字元) ",
  "timestamp": "ISO 8601 datetime",
  "metadata": {
    "model": "gemini-2.5-flash-lite | gemini-2.5-flash",
    "intent_score": 0.92,
    "retrieved_chunks": ["chunk_id_1", "chunk_id_2"],
    "note_files": ["file_name_1.md"]
  }
}
```

### 最終決定: Schema 欄位說明

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `session_id` | string | ✅ | 區分不同次對話，手動開新對話時生成 |
| `agent_type` | enum | ✅ | router / rag / planning |
| `role` | enum | ✅ | user / model，對齊 Gemini API 格式 |
| `content` | string | ✅ | 訊息純文字內容，上限 2000 字元 |
| `timestamp` | datetime | ✅ | 排序用，讀取最近 N 輪依此排序 |
| `metadata.model` | string | 否 | 記錄生成模型，供日後分析 |
| `metadata.intent_score` | float | 否 | Router 判斷 intent 的信心分數，debug 用 |
| `metadata.retrieved_chunks` | array | 否 | Agent 1 檢索到的 chunk_id，可追溯來源 |
| `metadata.note_files` | array | 否 | 本輪涉及的筆記檔名 |

### 最終決定: Index

```javascript
{ session_id: 1, timestamp: -1 }   // 取某 session 最近 N 筆 (根據資安防護評估那節: 單一 session 將卡上限 100 筆，超過刪除最舊的)
{ agent_type: 1, timestamp: -1 }   // Router 跨 session 分析時用
```

---

## 10. Step 9: 最終架構總結 [🏠](#目錄)

### 決策總表

| 主題 | 項目 | 決策 | 備註 |
|-----|------|------|------|
| App | UI 入口 | 單一對話框 | Page 3，含「開新對話」按鈕與 `st.login()` |
| Agents| Agent 數量 | 2 個 | RAG Agent + Planning Agent |
| Agents | Routing 策略 | Keyword 快篩 + 若模糊則 LLM 補判 | 帶最近 3 輪 history (N=3)，未來有需要仍可透過環境變數調整 |
| Agents - Models | LLM 廠商 | Gemini on Vertex AI | GCP 帳單統一，從現有 SA 架構擴展 |
| Agents - Models| Routing 模型 | `gemini-2.5-flash-lite` | 速度與成本優先 |
| Agents - Models| Agent 1 模型 | `gemini-2.5-flash-lite` | 速度與成本優先 |
| Agents - Models| Agent 2 模型 | `gemini-2.5-flash` | 推理能力較強，適合跨 domain 規劃 |
| Agents - tools| SDK | `google-genai` (Gen AI SDK)  | 非 `google-cloud-aiplatform` |
| Agents - tools| Agent 框架 | 手刻，無第三方框架 | 掌控度最高，Portfolio 能展示底層架構能力 |
| Agents Session | Chat History DB | MongoDB Atlas `chat_history` | 需新建 collection + index |
| Agents Session | Session 生命週期 | 手動開新對話 | uuid4 生成 session_id |
| Access Agents | App 與 Agent 互動權限 | 新建專用 SA，最小權限原則 | `roles/aiplatform.user` 等 |
| Vector Database | Embedding 模型 | OpenAI `text-embedding-3-small` | 沿用現有長篇 .md 筆記之ETL任務過程中調用的模型 (調用源頭寫在分支feature/etl-pipeline) |
| Vector Database | Vector DB | MongoDB Atlas `obsidian_vectors` | 沿用，文檔集創建源頭寫在分支feature/etl-pipeline
| App Security | 身份驗證 | `st.login()` Google OAuth | Streamlit 1.41+ 原生支援 (前 page 1-2 已用1.57.0) |
| App Security | Rate Limiting | Streamlit session state 手刻 | 防止 API 費用爆炸 |
| App Security| MongoDB 寫入保護 | 單 session 上限 100 筆，單筆上限 2000 字元 | 防止儲存無限增長 |
| Project Goal| Phase III 開發範圍 | 筆記摘要、語意查詢、學習地圖 | 聊天輸入向量化延後至後續階段 |

### 完整資料流

```
使用者輸入
    │
    ▼
[st.login() 驗證] ──✗──→ Google 登入頁
    │ ✅
    ▼
[Rate Limit 檢查] ──✗──→ 「請稍後再試」
    │ ✅
    ▼
[load_chat_history (session_id, N=3)]
    │
    ▼
[Intent Router]
  Step 1: keyword 快篩
    │ 模糊時
    ▼
  Step 2: gemini-2.5-flash-lite (帶 3 輪 history) → 輸出 rag_agent | planning_agent
    │
    ├──→ rag_agent
    │         │
    │         ▼
    │    vector_search(query, top_k=5)
    │    → MongoDB Atlas obsidian_vectors
    │         │
    │         ▼
    │    gemini-2.5-flash-lite
    │     (system prompt + chunks + user query → 摘要或查詢回應) 
    │
    └──→ planning_agent
              │
              ▼
         vector_search(query, top_k=10)
         → MongoDB Atlas obsidian_vectors
              │
              ▼
         gemini-2.5-flash
          (system prompt + chunks + planning session history → 學習地圖) 
    │
    ▼
[save_chat_history (session_id, agent_type, role, content, metadata)]
→ MongoDB Atlas chat_history
    │
    ▼
[Streamlit Page 3 渲染回應]
st.chat_message + st.chat_input
```

### Tools 層 (Python Functions) 

| Function | 呼叫方 | 外部依賴 |
|----------|--------|----------|
| `vector_search(query, top_k)` | Agent 1, Agent 2 | MongoDB Atlas `obsidian_vectors` |
| `load_chat_history(session_id, n)` | Router, Agent 1, Agent 2 | MongoDB Atlas `chat_history` |
| `save_chat_history(...)` | Agent 1, Agent 2 | MongoDB Atlas `chat_history` |
| `embed_and_store()` *(Phase IV 新任務)* | Agent 1 | OpenAI API + MongoDB Atlas |
| `write_md_to_gcs()` *(Phase IV 新任務)* | Agent 1 | GCS |

### SA 權限規劃

| 權限 | 說明 |
|------|------|
| `roles/aiplatform.user` | 呼叫 Vertex AI / Gemini API |
| `roles/storage.objectCreator` | 寫入 GCS (*Phase IV 新任務使用*)  |
| `roles/storage.objectViewer` | 讀取 GCS (*Phase IV 新任務使用*)  |
| MongoDB Atlas | IP whitelist + connection string，存於 Secret Manager |
| OpenAI API key | 存於 Secret Manager (Phase IV 使用)  |

> ⚠️ GCP role 名稱官方資料: https://cloud.google.com/iam/docs/understanding-roles

### 預計開發順序

| Sprint | 任務 | 說明 |
|--------|------|------|
| **Sprint 1** | 基礎建設 | 建立 MongoDB `chat_history` collection + index；新建專用 SA 設定 `roles/aiplatform.user`；確認 `google-genai` SDK 在本地可呼叫 Vertex AI |
| **Sprint 2** | Tools 層 | 實作 `vector_search()`；實作 `load_chat_history()` / `save_chat_history()`；撰寫單元測試 |
| **Sprint 3** | Agent 1 (RAG Agent)  | 實作筆記語意查詢；實作筆記摘要；本地測試通過 |
| **Sprint 4** | Routing 層 | 實作 keyword 快篩規則；實作 LLM 補判 (帶 N=3 輪 history) ；測試 intent 切換情境 |
| **Sprint 5** | Agent 2 (Planning Agent)  | 實作學習地圖初版生成；實作多輪追問調整；測試跨 domain (生技 + 資料工程) 推理 |
| **Sprint 6** | Streamlit Page 3 | 實作 `st.login()` Google OAuth；實作 Session Rate Limiting；實作「開新對話」按鈕 + session_id 生成；串接 Router → Agent 1 / Agent 2 → 顯示回應 |
| **Sprint 7** | 部署 | 更新 Dockerfile 加入新依賴；GitHub Actions CI/CD 打包推送；Cloud Run Service 更新部署；端對端測試 |

---

*END of DOCUMENTS*

> **參考文件清單**
> - `google-genai` SDK: https://googleapis.github.io/python-genai/
> - Vertex AI 模型清單: https://cloud.google.com/vertex-ai/generative-ai/docs/learn/models
> - Vertex AI 定價: https://cloud.google.com/vertex-ai/generative-ai/pricing
> - Streamlit st.login(): https://docs.streamlit.io/develop/api-reference/user/st.login
> - GCP IAM Roles: https://cloud.google.com/iam/docs/understanding-roles
> - Cloud Run 驗證: https://cloud.google.com/run/docs/authenticating/overview