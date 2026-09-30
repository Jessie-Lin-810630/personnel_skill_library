# Tasks

## 1. 前置：GCP 資源與依賴

- [x] 1.1 設定 OAuth 同意畫面：User type 選 External、Publishing status 維持 Testing、把允許登入的 email 加進測試使用者名單。驗證：在 Google Auth Platform 的 Audience 頁看得到該 email 列在 Test users
- [x] 1.2 建立 OAuth Web client，Authorized redirect URIs 填入地端與 Cloud Run 兩筆 `<base-url>/oauth2callback`。驗證：取得 client id 與 client secret，且 Credentials 頁列得出這兩筆 URI
- [x] 1.3 授予 dashboard runtime service account 對自己的 `roles/iam.serviceAccountTokenCreator`，驗證：`gcloud iam service-accounts get-iam-policy <dashboard SA>` 列得出該 binding
- [ ] 1.4 在 Secret Manager 建立 `USER_ALLOWLIST`（JSON 字串，email 對應角色）、`TOKEN_ISSUER_SA`（dashboard runtime SA 的 email）、`OIDC_CLIENT_ID`、`OIDC_CLIENT_SECRET`、`OIDC_COOKIE_SECRET`。驗證：`gcloud secrets versions access latest --secret=USER_ALLOWLIST` 取得的內容可被 `json.loads` 直接解析（內容前後不可有 shell 用的引號，否則解析在第一個字元就失敗），另外四個 secret 讀得到值
- [x] 1.5 `pyproject.toml` 加入 `fastapi`、`uvicorn`、`pyjwt`，執行 `poetry install` 後驗證：`poetry run python -c "import fastapi, uvicorn, jwt"` 不報錯（`flask` 與 `gunicorn` 本次不移除）

## 2. 共用驗證模組 `task07_common/auth.py`

- [x] 2.1 寫 `verify_user` 的 FastAPI dependency：讀 `X-User-Token`，以 dashboard runtime SA 的公開憑證驗簽、驗 `exp`，回傳 email 與角色。驗證：新增 `tests/test_task07_common_auth.py`，以自簽金鑰對造出的 token 測「驗簽通過」「簽章不符」「已過期」三種情形皆符合預期
- [x] 2.2 加入允許清單比對：驗簽通過但 email 不在 `USER_ALLOWLIST` 內時拋出 403。驗證：`tests/test_task07_common_auth.py` 中清單外 email 的案例取得 403，清單內取得對應角色
- [x] 2.3 缺 `X-User-Token`、驗簽失敗、過期一律回 401；連不上 Google 的 JWK 端點改回 503。驗證：同上測試檔三個 401 案例與一個 503 案例都符合預期
- [x] 2.4 提供共用的 `RequestValidationError` handler，把 FastAPI 預設的 422 改成 400。驗證：單元測試對一個最小 FastAPI app 送出缺欄位的請求，收到 400

## 3. Silver 服務改寫

- [x] 3.1 `task07_silver_service/app.py` 從 Flask 改為 FastAPI，路由用 `def` 不用 `async def`，掛上 `Depends(verify_user)` 與 2.4 的 handler。驗證：`poetry run python -m unittest tests.test_silver_service_endpoint -v` 全綠
- [x] 3.2 請求欄位改用 Pydantic model，`trigger` 以 `Literal["on_demand", "regenerate"]` 限制。驗證：測試檔補上「缺 page_id」「trigger 非法」兩案例，皆回 400
- [x] 3.3 `tests/test_silver_service_endpoint.py` 從 `app.test_client()` 改為 FastAPI `TestClient`，所有請求補上合法的 `X-User-Token`。驗證：該測試檔全綠，且移除 token 後的案例回 401
- [x] 3.4 既有狀態碼語意不變（快取命中、斷路器冷卻、quota 用盡回 200，查無版本回 404）。驗證：測試檔既有案例不需修改斷言即可通過

## 4. Gold 服務改寫

- [x] 4.1 `task07_gold_service/app.py` 從 Flask 改為 FastAPI，掛上 `Depends(verify_user)` 與 2.4 的 handler。驗證：`poetry run python -m unittest tests.test_gold_service_endpoint -v` 全綠
- [x] 4.2 `role` 從 request body 移除，改用 `verify_user` 回傳的角色傳給 `archive_note` 與 `reject_note`；body 若帶 `role` 予以忽略。驗證：測試斷言 `archive_note` 收到的 `role` 來自 token 而非 body，且 body 帶假 `role` 時不影響結果
- [x] 4.3 確認 400 與 422 不混用：欄位不合法回 400，md 未生成或複製失敗回 422。驗證：`tests/test_gold_service_endpoint.py` 的 `test_missing_fields_returns_400` 與 `test_approved_no_md_returns_422` 同時通過
- [x] 4.4 `tests/test_gold_service_endpoint.py` 改用 FastAPI `TestClient`，移除請求裡的 `role` 欄位並補上 `X-User-Token`。驗證：該測試檔全綠

## 5. 斷路器加鎖

- [x] 5.1 `t_enrich_html_to_markdown.py` 的 `_LLMServiceGuard` 加 `threading.Lock`，包住 `record_failure` 與 `record_success` 整個方法本體，`is_open` 不加。驗證：`tests/test_silver_service_circuit_guard.py` 的門檻、歸零與並行案例全綠
- [x] 5.2 記錄實測結果並改寫理由：GIL 版本不會漏算，加鎖是為了 free-threaded 直譯器。驗證：proposal、design 與 spec 不再宣稱存在現行漏算，測試不宣稱能重現競態

## 6. Dashboard 登入流程

- [x] 6.1 建立 `.streamlit/secrets.toml` 的範本（`redirect_uri`、`cookie_secret`，以及 `[auth.google]` 底下的 `client_id`、`client_secret`、`server_metadata_url`），加入 `.gitignore` 並更新 `.env.example` 說明。驗證：`git status` 不出現 `secrets.toml`，且地端 `poetry run streamlit run dashboard_ui/app.py` 可跳轉到 Google 登入頁
- [x] 6.2 `dashboard_ui/pages/onenote_review.py` 以 `st.login()` 取代 `CREDENTIALS` 帳密比對，登入後以 `st.user.email` 對照允許清單決定 `st.session_state.role`，清單外落 `Guest`。驗證：地端以清單內帳號登入取得審查角色，以清單外帳號登入取得 Guest
- [x] 6.3 `dashboard_ui/pages/ai_knowledge_agent.py` 加登入 gate，移除檔案頂部的 `# TODO: st.login()` 注解區塊。驗證：未登入時頁面只顯示登入入口，`session_id` 不初始化
- [x] 6.4 移除 `ROLE_ML_*`／`ROLE_OWNER_*`／`ROLE_SENIOR_*`／`ROLE_GUEST_*` 八個環境變數與相關程式碼（`Guest` 角色本身保留，改由允許清單推導），更新 `.env.example`。驗證：`grep -rn "ROLE_ML_USERNAME\|ROLE_GUEST_USERNAME" dashboard_ui/ .env.example` 無結果

## 7. Dashboard 簽發與轉傳 token

- [x] 7.1 新增 `dashboard_ui/utils/user_token_for_silver_and_gold.py` 的 `mint_user_token`：呼叫 IAM Credentials 的 `signJwt`，以 dashboard runtime SA 私鑰簽出含 email 與五分鐘 `exp` 的 JWT，不夾帶角色。驗證：`tests/test_user_token_audience_matches.py` 斷言簽發端與驗證端的 audience 常數一致
- [x] 7.2 approve、reject、regenerate 三個呼叫都在 `X-User-Token` 帶上新簽的 JWT，且每次呼叫前重新簽發；Gold 的 body 移除 `role`。驗證：地端同時啟動 Silver（8002）與 Gold（8003），三個按鈕都能成功走完並在服務日誌看到驗證通過
- [x] 7.3 Guest 一律不送請求：Gold 維持既有的假象分支，Silver 新增四道攔截（自動生成、審查列重試按鈕停用、生成失敗重試按鈕停用、`_call_silver` 開頭兜底）。驗證：以 Guest 角色瀏覽與按鈕操作，Silver 與 Gold 的日誌沒有任何請求進來

## 8. 部署設定

- [ ] 8.1 兩支 Dockerfile 的啟動指令從 gunicorn 換成 uvicorn，維持 `--workers 1`。驗證：本機 `docker build` 後 `docker run` 起得來，`curl` 打端點得到 401（因為沒帶 token）
- [ ] 8.2 兩支 workflow 加上 `USER_ALLOWLIST` 的 secret 注入，Cloud Run 的 SA、記憶體、concurrency 參數維持不變。驗證：workflow 的 `--set-secrets` 含新變數，`--service-account` 與 `--concurrency` 與變更前一致
- [ ] 8.3 dashboard 的 workflow 加上 `OIDC_CLIENT_ID`、`OIDC_CLIENT_SECRET`、`OIDC_COOKIE_SECRET`、`USER_ALLOWLIST` 的 secret 注入，並移除八個 `ROLE_*` 的注入。驗證：部署後以測試使用者名單內的 Google 帳號登入成功
- [ ] 8.4 部署完成後，把 Cloud Run 實際的服務網址補進 OAuth Web client 的 Authorized redirect URIs。驗證：雲端登入不再出現 `redirect_uri_mismatch`
- [ ] 8.5 確認測試使用者名單外的帳號登入被 Google 擋下。驗證：以名單外帳號嘗試登入，停在 Google 的錯誤頁，不進到應用程式

## 9. 文件與收尾

- [ ] 9.1 更新 `task07_silver_service/README.md`、`task07_gold_service/README.md` 的 Configuration 與啟動方式（uvicorn、新 header、新環境變數）。驗證：README 的啟動指令照抄可跑
- [ ] 9.2 更新 `dashboard_ui/README.md` 的登入說明與 Configuration。驗證：README 不再提到四組 demo 帳密
- [ ] 9.3 更新根目錄 `CLAUDE.md` 中提及 Flask 端點與 demo 帳密的段落。驗證：`grep -n "Flask" CLAUDE.md` 的結果與實作一致
- [ ] 9.4 全測試通過。驗證：`poetry run python -m unittest discover -s tests` 全綠
