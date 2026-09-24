# Proposal

## Why

審查頁送到 Gold 端點的 `role` 是 request body 裡的一個字串（`task07_gold_service/app.py:52`），後端只檢查它不是空值，不驗證它對應到哪個人。這個 `role` 會寫進 audit log，也會被審查頁讀回來顯示成「誰核准了這個版本」（`dashboard_ui/pages/onenote_review.py:417`）。稽核紀錄的可信度因此取決於呼叫端自律，而不是後端驗證。

現在的登入是四組寫在 env 的 demo 帳密（`ROLE_ML_*`／`ROLE_OWNER_*`／`ROLE_SENIOR_*`），靠字串比對決定角色。作品集會把帳密給人試用，等於任何拿到帳密的人都可以宣稱自己是 Note Owner。Cloud Run 的 `--no-allow-unauthenticated` 擋得住「哪個服務可以呼叫」，擋不住「哪個人下的指令」，這兩件事目前只有前者有把關。

同時，兩個服務的參數檢查是手寫的 if 判斷，重複且沒有機器可讀的介面定義。換成 FastAPI 可以把檢查改成宣告式，並取得 OpenAPI 文件，讓 dashboard 與端點之間的介面定義有單一來源。身分驗證需要在兩個服務各掛一道相同的檢查，FastAPI 的 dependency 機制正好用來掛這種橫向關注點。

## What Changes

### 身分驗證

- dashboard 改用 Streamlit 1.59 內建的 OIDC 登入（`st.login()` / `st.user`），以 Google 為 OIDC provider（discovery 網址 `https://accounts.google.com/.well-known/openid-configuration`），取代四組 env 帳密。
- 第一道防線用 OAuth 同意畫面的測試使用者名單：同意畫面維持 External 與 Testing 狀態，只有列在名單內的 Google 帳號能完成登入流程。
- 第二道防線在應用程式端以 email 允許清單決定角色。清單內的帳號取得完整審查權限，清單外的帳號一律落到既有的 Guest 角色。
- Guest 的行為維持現狀：只呈現操作成功的畫面，不呼叫 Gold 端點，MongoDB 不寫入。作品集的試玩流程因此不受影響。
- dashboard 呼叫 Silver 與 Gold 時多帶一個 header `X-User-Token`，內容是 dashboard 以自己的 runtime SA 私鑰（透過 IAM Credentials 的 `signJwt`）為登入者簽發的短效 JWT。Streamlit 的 `st.user` 只給解碼後的 claims、拿不到原始 ID token，所以改用這個方式傳遞身分。`Authorization` header 不能用，它已經被 Cloud Run IAM 用來放 dashboard runtime SA 的 token。
- Silver 與 Gold 驗證 `X-User-Token` 的簽章與 email，角色改由驗證結果推導，不再讀 request body 的 `role` 欄位。驗證邏輯放在 `task07_common/auth.py`，兩個服務以 FastAPI dependency 掛載。
- AI agent 頁只加登入 gate，不涉及 token 轉傳，因為它不呼叫 Silver 或 Gold。

### Web 框架

- Silver 與 Gold 各自從 Flask 換成 FastAPI，**兩個服務維持分開部署**：SA 分離（`psd-enrich-task` 與 `psd-archive-task`）、workflow 分離、Cloud Run 資源參數分離，全部不動。
- 手寫的欄位檢查改為 Pydantic model。既有的業務狀態碼語意原樣保留，其中 Gold 的 422 已經被「md 未生成／複製失敗」佔用，與 Pydantic 預設的驗證失敗狀態碼衝突，需要指定驗證失敗改回 400。
- 兩支 Dockerfile 的 gunicorn 換成 uvicorn。Silver 維持單一 worker，因為斷路器 `_LLMServiceGuard` 仍是 process 內的單例。

### 併發安全

- `task07_silver_service/t_enrich_html_to_markdown.py:96` 的 `_LLMServiceGuard` 補 `threading.Lock`，鎖住 `record_failure` 與 `record_success`，`is_open` 維持不鎖。目前 `_consecutive += 1` 在多執行緒下是沒有保護的讀取後寫入，失敗次數可能漏算，斷路器會比設定值晚跳脫。

### 不在本次範圍

- Bronze ETL 上雲與網頁授權流程（另案評估）。
- 把 Silver 與 Gold 合併成單一服務。合併會讓兩個 SA 的權限取聯集，與本次提升驗證強度的目的相反；也會讓兩支 workflow 的部署條件合而為一，改動任一邊都要重新部署整個服務，可能打斷正在進行的 enrich。
- 把 pymongo、google-cloud-storage、genai 換成 async client。現有的 gunicorn threads 已經提供等待網路回應時處理其他請求的能力，改寫的風險大於收益。
- 快取邏輯、斷路器的跳脫策略、GCS 目錄結構、`onenote_note_metadata` 的欄位定義。

## Capabilities

### New Capabilities

- `user-identity-verification`：審查者身分從登入到後端驗證的完整規則。涵蓋 dashboard 如何取得並簽發身分憑證、以哪個 header 轉傳、Silver 與 Gold 如何驗證簽章與 email、角色如何從驗證結果推導、驗證失敗回什麼狀態碼，以及允許清單外的帳號落到 Guest 的規則。

### Modified Capabilities

- `onenote-review-page`：`Requirement: Demo login gate` 的登入方式從 env 帳密比對改為以 Google 為 provider 的 OIDC 登入；新增允許清單外帳號落到 Guest 的情境；approve／reject／regenerate 三個呼叫都要帶 `X-User-Token`。
- `ai-knowledge-agent-page`：`Requirement: Auth placeholder for future st.login()` 從佔位符改為實際的登入 gate，未登入不得進入頁面。
- `silver-enrich-endpoint`：新增身分驗證前置條件，`X-User-Token` 缺漏或驗證失敗時拒絕請求；`Scenario: 缺少必要欄位` 的檢查改由 Pydantic model 執行，回應狀態碼維持 400。
- `gold-archive-endpoint`：新增身分驗證前置條件；`Requirement: 請求驗證` 的 `role` 欄位從 request body 移除，改由驗證後的身分推導，`Scenario: 缺欄位` 與 `Scenario: 非法 action` 改由 Pydantic model 執行且維持 400，與既有的業務錯誤 422 區隔。

## Impact

- **修改程式**：
    - `task07_silver_service/app.py` & `task07_gold_service/app.py`（框架與驗證）
    - `task07_silver_service/t_enrich_html_to_markdown.py`（斷路器加鎖）
    - （`task07_gold_service/l_archive_note.py` 不需修改：`archive_note` 與 `reject_note` 的 `role` 參數維持原樣，改變的只是端點傳進去的值從 body 換成 token 推導的結果）
    - `dashboard_ui/pages/onenote_review.py`（登入流程與 header）
    - `dashboard_ui/pages/ai_knowledge_agent.py`（登入 gate）
- **新增程式**：`task07_common/auth.py`。
- **Docker 與部署**：`docker/Dockerfile.task07_silver_service`、`docker/Dockerfile.task07_gold_service` 的啟動指令改用 uvicorn。兩支 workflow 的 Cloud Run 參數不變，SA 與 secrets 不變。
- **依賴**：
    - 新增 `fastapi`、`uvicorn`、JWT 驗簽用的 `pyjwt`
    - `flask` 與 `gunicorn` 在部署完成與 archive change 之前不移除。
- **GCP 資源**：需要設定 OAuth 同意畫面（External、Testing、加入測試使用者）、建立 OAuth Web client（兩個 redirect URI：地端與 Cloud Run）、授予 dashboard runtime SA 對自己的 `roles/iam.serviceAccountTokenCreator`。`identitytoolkit.googleapis.com` 與 `iamcredentials.googleapis.com` 已啟用，不需另外開通。
- **環境變數**：
    - `ROLE_ML_*`／`ROLE_OWNER_*`／`ROLE_SENIOR_*` 共六個 demo 帳密變數退場
    - 新增 `USER_ALLOWLIST`（email 對應角色的 JSON object）與 `TOKEN_ISSUER_SA`（dashboard runtime service account 的 email），dashboard、Silver、Gold 三者都要。
    - 新增 dashboard 專用的 OIDC 設定：`OIDC_CLIENT_ID`、`OIDC_CLIENT_SECRET`、`OIDC_COOKIE_SECRET`。
    - 退場與新增都要更新 `.env.example` 與 Secret Manager。
- **不影響**：MongoDB collection 與欄位、GCS 目錄結構、Bronze ETL、task08 向量化、其他 dashboard 頁面。
