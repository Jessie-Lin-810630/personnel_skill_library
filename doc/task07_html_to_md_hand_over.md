# Feature Branch: `feature/html-to-markdown` — 新支線開發執行成果摘要

> **開發目標**：展示一個從生技領域跨足到資料工程的雙棲求職者所具備的知識庫與資料工程技術。既定計劃從LeetCode、ccClub、GitHub、 Google Sheet、local Obsidian 盤點個人技能範疇，並寫入 MongoDB Altas，local Obsidian vault 作為學習機器人的 RAG 來源。而後自 2026-05-30 起，計畫新增支線將 Microsoft OneNote 筆記萃取、清洗/轉換、存於 MongoDB Altas，此 ETL 數據管道在於為慣用微軟 OneNote 筆記軟體但不習慣/尚未學習 markdown 語法做筆記的使用者/單位，清理出適合用於機器學習、AI 模型閱讀的形式，以長遠更能有效擴展 RAG 外部知識庫的可用性，減少因為過往檔案格式與 現代 AI 工具不全相容而導致知識無法有效管理、保留、被 AI 理解後服務人類的窘境。

> **完成日期**：2026-06-14

> **執行環境**：macOS with Web browser / VS Code IDE / pyenv (Python 3.14) / Poetry

---

## 專案資料夾結構

```
feature/html-to-markdown/
├── .env                         
├── poetry.lock
├── pyproject.toml
│
├── .agents/                     # Workspace harmonizing muilti-AI agents in the same project such as sharing the skills btw agents. The internal structure is totally identical with the "./.claude/" (see bellows).
│
├── .claude/
│   ├── commands/                # project-level commands
│   ├── hooks/                   # project-level hooks
│   └── skills/                  # project-level skills
│    ├── openspec-apply-change/  # One of 11 Skills for SDD
│    ├── openspec-onboard/       # One of 11 Skills for SDD
│    └── ..../
│
├── task07_obsidian_etl/
│   ├── e_onenote_download.py    # Extract and download raw notes 
│   │                            # from Azure OneNote Graph API.
│   ├── t_html_to_markdown.py    # Parsing raw .html file to 
│   │                            # lightweight of .md files and 
│   │                            # keyword extraction by LLM
│   ├── l_save_markdown.py       # Storage .md files to on-premise
│   ├── main.py                  # 串接 Extract / Transform / Load
│   └── utils/
│         └── audit_log.py/      # Save log to MongoDB. Callback 
│                                # frequently when running  
│                                # e_, t_, l_ three scripts.
│
└── tests/

```

---

## Task 07 — OneNote ETL

### 資料來源
Azure graph API

### Tools, Framework
- msal
- google gen ai sdk
- gemini 2.5 flash lite model

### database, data storage
- MongoDB Altas (for log storage)
- local filesytem (for storage of the first fetched html and generated markdown files)
- GCS (data lake receiving the html and markdown files uploaded from local side)


### Brown layer - Storage of raw notes
- Hierarchy of blobs
```plaintext
gcs://onenote-vaults
├── <employee_note_account_name>/      # without '@ and domain'
│       ├── <Notebook1_name>/
│       │       ├── <Section1_name_of_NB1>/  
│       │       │       ├── Page1_name_of_sec1.html  
│       │       │       ├── Page2_name_of_sec1.html  
│       │       │       ├── ....
│       │       │       ├── PageN_name_of_sec1.html  
│       │       │       └── _images/
│       │       │             ├── image01.PNG
│       │       │             ├── image02.PNG
│       │       │             └── image0x.PNG
│       │       │
│       │       ├── <Section2_name_of_NB1>/
│       │       │       ├── Page1_name_of_sec2.html  
│       │       │       ├── ....
│       │       │       └── _images/
│       │       │
│       │       ├── <Section3_name_of_NB1>/  
│       │       │       ├── ....
│       │       │       └── _images/
│       │       │
│       │       └── <SectionN_name_of_NB1>/
│       │               ├── ....
│       │               └── _images/
│       │
│       └── <Notebook2_name>/
│               ├── <Section1_name_of_NB2>/  
│               │        ├── Page1_name_of_sec1.html  
│               │        ├── Page2_name_of_sec1.html  
│               │        ├── ....
│               │        ├── PageN_name_of_sec1.html  
│               │        └── _images/
│               └── <SectionN_name_of_NB2>/
│        
├── <employee_note_account_name>/
│       ├── <Notebook1_name>/
....    .....
```

- Metadata schema
    - title: page name in a section of a notebook.  
    e.g., "SQL 基本資訊"
    - created_datetime:  Creation date and time in UTC+0 of this page.  
    e.g., 2025-12-20T00:46:09.898Z
    - modified_datetime:  Last modified date and time in UTC+0 of this page.  
    e.g., 2025-12-21T00:51:00.121Z
    - html_path:  <gcspath>/<to>/<blob>.html
    - markdownExportDateTime: exported date and time of markdown file.
    - markdown_path:  <gcspath>/<to>/<blob>.md

### Silver layer - Storage of transformed notes
```plaintext
gcs://onenote-vaults
├── <employee_note_account_name>/      # without '@ and domain'
│       ├── <Notebook1_name>/
│       │       ├── <Section1_name_of_NB1>/  
│       │       │       ├── Page1_name_of_sec1.html  
│       │       │       ├── Page1_name_of_sec1.md      ⬅️ Inserted
│       │       │       ├── Page2_name_of_sec1.html  
│       │       │       ├── Page2_name_of_sec1.md      ⬅️ Inserted
│       │       │       ├── ....
│       │       │       ├── PageN_name_of_sec1.html  
│       │       │       ├── PageN_name_of_sec1.md      ⬅️ Inserted
│       │       │       └── _images/
│       │       │             ├── image01.PNG
│       │       │             ├── image02.PNG
│       │       │             └── image0x.PNG
│       │       │
│       │       ├── <Section2_name_of_NB1>/
│       │       │       ├── Page1_name_of_sec2.html  
│       │       │       ├── Page1_name_of_sec2.md      ⬅️ Inserted
│       │       │       ├── ....
│       │       │       └── _images/
│       │       │
....    ....    ....
...     ...     ...

```

### Gold layer - Storage of verified notes by human review

```plaintext
gcs://personal-vaults
├── 01_daily_logs/
│       ├── <Notebook1_name>/
│       │       ├── <Section1_name_of_NB1>/  
│       │       │       ├── Page1_name_of_sec1.md      ⬅️ Copied  
│       │       │       │                                 from 'onenote-vaults'
│       │       │       ├── Page2_name_of_sec1.md      ⬅️ Copied 
│       │       │       │                                 from 'onenote-vaults'
│       │       │       ├── ....
│       │       │       ├── PageN_name_of_sec1.md      ⬅️ Copied
│       │       │       │                                 from 'onenote-vaults'
│       │       │       └── _images/                   ⬅️ Copied 
│       │       │             ├── image01.PNG             from 'onenote-vaults'
│       │       │             ├── image02.PNG
│       │       │             └── image0x.PNG
├── 02_knowledge_bases/
│       ├── <Notebook1_name>/
│       │       ├── <Section1_name_of_NB1>/
│       │       │       ├── Page1_name_of_sec1.html  
│       │       │       ├── Page1_name_of_sec1.md      ⬅️ Copied 
│       │       │       │                                 from 'onenote-vaults'
│       │       │       ├── ....
│       │       │       └── _images/
│       │       │
....    ....    ....
...     ...     ...

```

### AI layer - Load to MongoDB Altas after Embedding
> Schema design follows [the definitions of task05](./branch_etl_pipeline_summary.md)


### Audit log

> 遵守人、事、時、地、結果 + primary key

#### Collection 1: OneNote Graph API Logs
- Purpose: When downloading from OneNote API and saving .html files on premises.    
- Schema:  **Written pattern: Keep appending. Reading pattern: Query only when trouble shooting.**

| 欄位名稱      | MongoDB 型別| Must   | 說明                                       |
| ------------ | ---------- | ------ | ----------------------------------------- |
| _id          | ObjectId   | Y      | MongoDB 自動產生主鍵                        |
| page_id      | String     | Y      | 對應 OneNote 頁面 ID，關聯其他 collections   |
| timestamp    | ISODate    | Y      | 寫入 audit log 時間 (UTC+0)                |
| event_type   | String     | Y      | 固定值：onenote_api_download                |
| user_id      | String     | N      | 發起者身分： agent skill、mac user、service account |
| method       | String     | Y      | GET、POST                                  |
| api_endpoint | String     | Y      | URL of API Endpoint                       |
| request_id   | String     | Y      | 同一輪 API Request ID，不論 Retry 次數       |
| attempt_id   | Int32      | Y      | calling 次數，從 1 開始，Retry 第一次則 attempt_id 為 2   |
| status       | String     | Y      | success、failure                          |
| status_code  | Int32      | Y      | HTTP Status Code                         |
| latency_ms   | Int32      | Y      | API 回應耗時 (ms)                          |
| error_msg    | String     | N      | 失敗時錯誤訊息                              |
| environment  | String     | Y      | local、dev、prod                          |
| html_path    | String     | Y      | 下載後 HTML 檔案路徑                        |

- indexes
```javascript
  // Four candidates
  { page_id: 1 }
  { request_id: 1 }
  { timestamp: -1 }
  { page_id: 1, timestamp: -1 }
```

#### Collection 2: Gemini 2.5 flash lite LLM log
- When calling Gemini LLM to reshape the structure of content and extract the keywords.
- Schema: **Written pattern: Keep appending. Reading pattern: Query when trouble shooting or tracking the billing by token consumption. **

| 欄位名稱         | MongoDB 型別 | Must    | 說明                        |
| --------------- | ---------- | -------- | -------------------------- |
| _id             | ObjectId   | Y        | MongoDB 自動產生主鍵         |
| page_id         | String     | Y        | 關聯其他 collection         |
| timestamp       | Date       | Y        | 寫入 audit log 時間 (UTC+0) |
| event_type      | String     | Y        | 固定值：gemini_llm_call     |
| user_id         | String     | N        | 發起者身分： agent skill、mac user、service account |
| model           | String     | Y        | Gemini LLM 名稱             |
| html_path       | String     | Y        | 輸入 HTML 路徑              |
| attempt_id      | Int32      | Y        | calling 次數，從 1 開始，Retry 第一次則 attempt_id 為 2   |
| status          | String     | Y        | success、failure           |
| latency_ms      | Int32      | Y        | 回應耗時 (ms)                |
| input_tokens    | Int32      | Y        | Prompt Tokens          |
| output_tokens   | Int32      | Y        | Output Tokens          |
| thinking_tokens | Int32      | Y        | Thinking Tokens        |
| total_tokens    | Int32      | Y        | Total Tokens           |
| error_msg       | String     | N        | 錯誤訊息                   |
| environment     | String     | Y        | local、dev、prod         |

- Indexes
```javascript
  { page_id: 1 }
  { timestamp: -1 }
  { page_id: 1, timestamp: -1 }
  { status: 1 }
```

#### Collection 3: page metadata linkage
- Purpose: Record metadata linkage when a note is converted between three file formats, native html file, LLM-generated markdown file, and human-reviewed markdown file. This collection will be updated frequently when fetching html from OneNoe API, calling Gemini LLM, saving the converted makrdown file and archiving the markdown file upon human review.
- Schema:  **Written pattern: May occur upsert! Reading pattern: Frequently query to check if data loss in development.**

| 欄位名稱           | MongoDB 型別   | Must   | 說明                              |
| ----------------- | ------------- | ------ | ------------------------------- |
| page_id           | String        | Y      | OneNote Page ID，設為 MongoDB ObjectId 或 Unique Index。Upsert 的 filter |
| notebook          | String        | Y      | Notebook 名稱                     |
| section           | String        | Y      | Section 名稱                         |
| page_title        | String        | Y      | 頁面標題                              |
| html_path         | String        | Y      | HTML 檔案路徑                         |
| html_created_at   | Date          | Y      | OneNote graph API 紀錄的 note 原始建立時間 |
| html_modified_at  | Date          | Y      | OneNote graph API 紀錄的 note 最後修改時間 |
| img_count_in_html | Int32         | Y      | HTML 中 img tag 數量              |
| md_path           | String        | N      | LLM 回應後存下的 Markdown 路徑，存檔失敗時為 null |
| img_path          | Array<String> | N      | HTML、Markdown 內文圖片路徑集合，原始筆記內完全沒圖片時為 [] 空陣列 |
| md_exported_at    | Date          | N      | LLM 回應後的 Markdown 匯出時間       |
| note_type         | String        | Y      | knowledge_summary、daily_log       |
| status            | String        | Y      | 文件生命週期狀態，見後方 Table 'Definition of available values for column Status and Review_result'       |
| error_msg         | String        | N      | Collection 1 & 2 沒有接得住的、其他關卡的錯誤訊息 |
| review_result     | String        | N      | null、approved、rejected，值得注意的是 approved 不代表歸檔成功，由欄位 status 說明清楚，見後方 Table 'Definition of available values for column Status and Review_result'  |
| reviewed_by_role  | String        | N      | 審核者角色，null、ML engineer、note_owner、dept_senior_specialist |
| reviewed_at       | Date          | N      | 審核時間                             |
| md_archive_path      | String     | N      | 最終歸檔 markdown 之 GCS 路徑       |
| img_archive_path  | Array<String> | N      | 最終歸檔 markdown 內文圖片在 GCS 上的路徑集合  |
| archived_at       | Date          | N      | Markdown 與 image 完成歸檔時間  |
```

- Indexes
```javasript
  { page_id: 1 }  // unique
  { status: 1 }
  { notebook: 1, section: 1 }
  { review_result: 1 }
  { archived_at: -1 }
```

#### Definition of available values for column Status and Review_result
| Scenarios                                     | status         |review_result |
| ---------------------------------------- | -------------- |-------------- |
| 剛從 OneNote graph API 抓下來，但是寫入 html 失敗     | fetched（卡住，從C1回推 error msg）    | null |
| Gemini LLM 正在生成     | fetched    | null |
| Gemini LLM 生成失敗 | summarized failed（卡住，從C2回推 error msg） | null |
| Gemini LLM 有回但寫 .md 檔失敗 | saved failed（卡住，從C2回推 error msg） | null |
| .md檔產生前任何故意不處理       | fetched        | null |
| 摘要成功、等人檢核       | pending_review | null |
| 按通過、歸檔成功            | archived       | approved      |
| 按通過、歸檔中途失敗 | archive_failed            | approved      |
| 被退回            | review_closed       |rejected      |

> approved ≠ archived，因為審核通過後仍視檔案系統運作得到 archive_failed、archived 兩種可能結果。   \
> 應以 status 作為最終狀態判斷依據。


## Development strategy of this branch
**地端測試階段**

1. 抓取 OneNote — 請求Azure OneNote Graph API ，把 html 與 png 存在地端筆電 (中間需由筆記持有者操作瀏覽器登入允許委派權限(delegated authentication)來讓呼叫端取得 token)，存放路徑 `'~/Desktop/Obsidian/OneNote-Export/{帳戶名}/{筆記本名}/{章節名}/{頁面名}.html'`、`'~/Desktop/Obsidian/OneNote-Export/{帳戶名}/{筆記本名}/{章節名}/_images/{images_id}.png`。帳戶名取 owner email 的 @ 前段。同時在 MongoDB Atlas append 一筆紀錄到 [Collection-1-onenote-graph-api-logs](#collection-1-onenote-graph-api-logs)，upsert 一筆紀錄到 [collection-3-page-metadata-linkage](#collection-3-page-metadata-linkage)的欄位`page_id`、`notebook`、`section`、`page_title`、`html_path`、`html_created_at`、`html_modified_at`、`img_count_in_html`、`img_path`、`status`。Collection 3 其他欄位均初始化為 null。

2. Gemini 摘要成 .md — 用 google genai SDK 調用 Gemini 2.5 Flash Lite 把 地端存放的 html `全部` 重新結構化成 markdown，存放路徑架構為 `'~/Desktop/Obsidian/OneNote-Export/{帳戶名}/{筆記本名}/{章節名}/{頁面名}.md'`，確保 .md 中的圖片是相對路徑表示，以利可以渲染 _images/ 下的圖片。同時在 MongoDB Atlas append 一筆紀錄到 [Collection-2-gemini-25-flash-lite-llm-log](#collection-2-gemini-25-flash-lite-llm-log)，upsert 一筆紀錄到 [collection-3-page-metadata-linkage](#collection-3-page-metadata-linkage)的欄位`md_path`、`img_path`、`md_exported_at`、`note_type`、`status`、`error_msg`。
> 全部結構化是希望透過單人測試先全量 eager 產出，順便當壓力測試量單人 token 貢獻。
> 更好的結構與成本控管應該是讓使用者選擇即時結構化與生成指定筆記，避免浪費資源。

3. 將步驟 1 與步驟 2 產出之 html 、png 與 md 同步到(使用本地端Claude Skill) GCS 上，定位成 staging vault，staging vault 路徑為
  - `gs://onenote-vaults/{帳戶名}/{筆記本名}/{章節名}/{頁面名}.md'`   
  - `gs://onenote-vaults/{帳戶名}/{筆記本名}/{章節名}/{頁面名}.html'`  
  - `gs://onenote-vaults/{帳戶名}/{筆記本名}/{章節名}/_images/{image_id}.png'`
  
  然後，在MongoDB Altas upsert[collection-3-page-metadata-linkage](#collection-3-page-metadata-linkage)的欄位`status`。
  
4. 切換到 repo branch `feature/dashboard-ui` 開發：
  - 地端開發且新增 streamlit 對照頁 : 左邊渲染 staging 的 html、右邊渲染轉出的 .md，上方有檢核狀態查核鈕、筆記名稱切換清單，最下方放檢核確認按鈕，用來提供使用者足夠的 AI 工具的資訊透明度。
  - 這個對照頁也需要頁面加 demo 級登入窗擋陌生人。
  - 使用者會評估Gemini 模型是否生成令人滿意後再檢核確認按鈕按下 `approved`，觸發步驟 5。
  - 同 `feature/dashboard-ui` 開發習慣，Streamlit 網頁在地端檢查。
    
5. 步驟 4 如果有按下`approved`，則呼叫 Archive 端點，端點是另一獨立的腳本，它跟 streamlit 關係為
  - Streamlit 不自己寫入 staging vaults 或 personal vaults，按鈕帶上 note_id 與登入者角色（伺服器端從 session 推導，三選一：ML/DL Engineer｜Note Owner｜Dept. Senior Specialist）去呼叫另一支 Archive service。
  - Archive 持有「讀 staging ＋ 寫 personal vault」兩權限，負責：把 png 複製到 `personal-vaults/{note_type}/{筆記本名}/images/`、讀 staging 的 .md 把圖片連結改寫成相對路徑 `./images/foo.png` 後，把 .md 寫入 `personal-vaults/{note_type}/{頁面名}.md`。其中，`{note_type}`在MongoDB Altas [Collection 3元數據](#collection-3-page-metadata-linkage)可查到。
  - html 留在 staging vault不刪，也就是說以下三個路徑的檔案不自動刪除，改由人工評估持久期。
    - `gs://onenote-vaults/{帳戶名}/{筆記本名}/{章節名}/{頁面名}.md'`   
    - `gs://onenote-vaults/{帳戶名}/{筆記本名}/{章節名}/{頁面名}.html'`  
    - `gs://onenote-vaults/{帳戶名}/{筆記本名}/{章節名}/_images/{image_id}.png'`
    
6. Archive 端點服務也需為 MongoDB Altas [collection-3-page-metadata-linkage](#collection-3-page-metadata-linkage) upsert 更新：
- `status`、`review_result`、`reviewed_by_role`、`reviewed_at`、`md_archive_path`、`img_archive_path`、`archived_at`。
    
7. 為防重複檢核，Streamlit 渲染時讀回 MongoDB Altas [collection-3-page-metadata-linkage](#collection-3-page-metadata-linkage) 狀態；已歸檔的頁面顯示「已歸檔」橫幅並停用按鈕。
    
8. 遺留 html 的保留 — 歸檔後 staging 的 html 不自動刪，保留多久人工評估、在 GCP console 操作，不過度開發。
    

**雲端部署階段（同部門跨帳號，GCP 為平台）**

9. Merge `feature/dashboard-ui` 開發的新頁面到 分支`develop`，修改 dockerfile 包成新 image ，自動觸發 git workflow 推送到 Artifact registry，跑在 cloud run service，此時要設定 streamlit docker container 服務帳戶只持有 staging vaults 的**唯讀**權限；頁面加 demo 級登入窗擋陌生人。 
10. 將 `Archive 端點` 包成 image，同步驟 9 手法，cloud run service/job/function(待定) 啟動另一個 docker container。Archive 端點 Cloud Run service 持有GCS bucket: personal vaults **寫入權限**與 staging vaults 的**唯讀**權限。
  
11. 部署到雲端時，產生之 log 仍然寫入 MongoDB Atlas ，因為地端階段就已把三檔合併進 Atlas 單一 collection，這步在地端其實已完成；雲端只是換成 Cloud Run 容器讀寫同一個 Atlas。

> 核心原則是：Streamlit 直連 Atlas 、 GCS 都僅限唯讀狀態顯示，維持前端的職責。streamlit互動間接觸發的所有寫入（狀態翻轉、檢核者）由 Archive 端點執行。
