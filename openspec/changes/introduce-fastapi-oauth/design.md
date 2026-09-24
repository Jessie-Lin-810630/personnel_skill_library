# Design

## Context

動機見 `proposal.md`。這裡只記形塑做法的既有限制：

- **`Authorization` header 已被佔用。** Silver 與 Gold 都以 `--no-allow-unauthenticated` 部署，該 header 由 Cloud Run 前置代理檢查後就結束任務，不會傳進應用程式，因此無法用來傳遞使用者身分。
- **兩個服務跑在不同 service account 上。** Silver 是 `psd-enrich-task`（需要 Agent Platform 與寫 `processed-notes/`），Gold 是 `psd-archive-task`（只碰 MongoDB 與 `archived-notes/`）。這個分離要保留。
- **Silver 限單一 worker。** `t_enrich_html_to_markdown.py:154` 的 `_LLMServiceGuard` 是 module 層級的單例，狀態存在 process 記憶體，多 worker 會各持一份。Dockerfile 已經為此而設 `--workers 1`，這次仍不改 worker 數量。
- **Streamlit 的 `st.user` 只給解碼後的 claims。** 官方文件說明它是「identity token information」的 dict-like 物件，搭配 `st.user.to_dict()`。原始 ID token 被 Streamlit 換成自己的 identity cookie 之後就不在公開 API 裡，取不到。
- **Guest 目前就不呼叫端點。** `onenote_review.py:668` 的 Guest 分支只更新畫面、直接 return，不送請求。這條路徑要保留。

## Goals / Non-Goals

**Goals:**

- Silver 與 Gold 端點判斷審核者身分時，依據一個可驗簽的憑證，不依據 request body 裡的字串。
- 兩個服務換成 FastAPI 之後，既有的狀態碼語意一個都不變。
- 驗證邏輯只寫一份，兩個服務共用，但維持各自獨立部署。
- 允許清單外的訪客仍能進入審查頁試玩，作品集的展示效果不減。

**Non-Goals:**

- 不做真正的權限分級。三個審查角色的差異只在 audit log 記錄的名稱，端點不因角色不同而允許或拒絕不同操作。
- 不處理 token 撤銷。短效 JWT 到期即失效，不另做黑名單。
- 不把斷路器狀態移出 process。跨實例共享是既有限制，本次只修同一個 process 內的計數問題。
- 不動 Bronze ETL、不合併兩個服務、不改既有的 MongoDB 欄位與 GCS 目錄。

## Decisions

### 1. 身分憑證改用 dashboard 以 runtime SA 私鑰簽發的短效 JWT

- 原本的想法是把登入者的 ID token 原樣轉傳給後端，但 Streamlit 的 `st.user` 拿不到原始 token，這條路走不通。

- 所以改成：dashboard 從 `st.user.email` 取得已驗證的 email，呼叫 GCP IAM Credentials 的 `signJwt`，用 dashboard 自己的 Cloud Run runtime service account 私鑰簽一個短效 JWT，放進 `X-User-Token`。下游服務 Silver 與 Gold 會取該 service account 的公開憑證 (由 Google 公開的) 來針對 `X-User-Token` 驗簽，確認此 Token 的確是在 dashboard 內部簽發出來的且內容沒被動過。

- 選 `signJwt` 而不是自己拿一把密鑰簽，理由是私鑰就不會出現在容器裡，也不必放進 Secret Manager 再輪替。dashboard 只要有自己 service account 的 `roles/iam.serviceAccountTokenCreator`，簽章動作在 GCP 上自動完成。
> 設計思維是 dashboard 呼叫 signJwt 時，是透過 IAM Credentials API 請 Google 用這個 SA 的私鑰簽名，私鑰由 Google 保管，dashboard 自己拿不到。而 IAM 收到請求後會依序檢查：
> 1. 呼叫者是誰？是 dashboard SA，來自 Cloud Run Service 的身分。
> 2. 要替哪個目標SA 簽？也是 dashboard SA。
> 3. 檢查"呼叫者SA" 有沒有 iam.serviceAccounts.signJwt 的權限，爲"目標 SA" 簽發 JWT？
> 所以授權的流程要想成：我要在 "目標SA" 的 service account 設定介面 授予 (grant) "呼叫者SA" 一個 service account token creator 角色。

```
使用者 ──st.login()──> accounts.google.com ──驗證 email──> Dashboard
                                                            │
                                    signJwt(email, exp)     │
                                    ↓                       │
Authorization:    <runtime SA ID token>   ← Cloud Run IAM 檢查「哪個服務」
X-User-Token: <短效 JWT>              ← 應用程式檢查「哪個人」
                                                            │
                                                            ▼
                                                    Silver / Gold
```


- **其他替代方案一**：dashboard 與兩個服務共用一把 Secret Manager 裡的密鑰做 HMAC 簽章。程式碼更短，但多一個要保管與輪替的密鑰，而且三個服務都要讀得到它，權限面比 `signJwt` 差。所以不採納此替代方案。

- **其他替代方案二**：把 Google 發的原始 ID token 原樣轉傳，後端直接用 Google 的公鑰驗簽。信任鏈上就沒有 dashboard，後端驗的是 Google 的簽章而非 dashboard 的。難點在取得那個 token 的步驟：`st.user` 只提供解碼後的 claims，原始 token 被 Streamlit 寫進名為 `_streamlit_user_tokens` 的 cookie（`streamlit/web/server/server_util.py` 的 `TOKENS_COOKIE_NAME`），要拿到它必須自行從 `st.context.cookies` 撈出、用 `cookie_secret` 解開 `create_signed_value` 的簽章，並把超過瀏覽器大小上限而被切成 `_streamlit_user_tokens_<n>` 的多個區塊拼回去。這三個動作依賴的 cookie 名稱、簽章方式與切塊規則都屬於 Streamlit 的內部實作，不在公開 API 內，升版時可能改動而讓登入後的呼叫全數失敗，且失敗點在 dashboard 而非端點，不容易從服務日誌看出原因。以維護成本考量不採納。

### 2. 允許清單放在環境變數，不放 MongoDB

- 清單內容是「email 對應到角色」，預期只有三到五筆，而且幾乎不變。放環境變數（部署時由 Secret Manager 注入）讓 dashboard 與兩個服務都能各自讀取，不需要為了在 MongoDB 新增資料表 (collection)，以及不需查那一筆資料而讓 Silver 與 Gold 多開一條 MongoDB 連線路徑。

- 注入 Secret Manager 時的格式是 JSON 字串：

```
USER_ALLOWLIST='{"me@example.com": "Note Owner", "other@example.com": "ML/DL Engineer"}'
```

- 另需 `TOKEN_ISSUER_SA`，值為 dashboard runtime service account 的 email。Silver 與 Gold 靠它決定要向哪一個 service account 的 JWK 端點取公開金鑰，並用同一個值比對 JWT 的 payload 裡的 `iss`。它不是機密，但仍隨其他設定一起由部署注入，避免寫死在程式碼裡。

- JWT 的 payload 裡的 `aud` 固定為 `task07-user`，定義在 `task07_common/auth.py` 的常數 `USER_TOKEN_AUDIENCE`。簽發端與驗證端引用同一個常數，避免兩邊各寫一份字串而不一致。

- **其他替代方案**：把角色寫進登入 token 的 claims，後端不必再查對照表。但 Google 發的 ID token claims 內容由 Google 決定，應用程式無法在其中加入自訂的角色欄位；要做到這件事得改用能設定 custom claims 的身分服務，連帶放棄 `st.login()`（理由見決策 8）。為了三筆資料不划算。

### 3. 驗證邏輯放 `task07_common/auth.py`，不合併服務

- `task07_common/` 已經是三個服務共用模組的所在（`gcs`、`audit_log`、`hashing`、`topic`），兩支 Dockerfile 也都已經 `COPY task07_common/`。新增一個 `auth.py` 沿用同一套做法，兩個服務各自 `Depends(verify_user)` 掛上。

- 不合併服務的理由見 `proposal.md` 的「不在本次範圍」。

### 4. 驗證失敗回 401 與 403，與業務錯誤分開

- 沒帶 `X-User-Token`、驗簽失敗、過期，回 `401`。
- 驗簽通過但 email 不在允許清單內，回 `403`。
- 欄位不合法回 `400`。
- 連不上 Google 的 JWK 端點回 `503`。PyJWT 把 `PyJWKClientConnectionError` 也掛在 `PyJWTError` 底下，一個 `except` 會把它和驗簽失敗混為一談，因此要先單獨攔下。這是本服務對外連線的問題，token 可能完全正常，回 `401` 會讓使用者以為要重新登入，重試多少次都一樣失敗。
- `422` 保留給 Gold 既有的業務錯誤（該版本尚未生成 md、複製失敗）。FastAPI 預設把 Pydantic 驗證失敗回 `422`，會跟這個語意撞在一起，所以要覆寫 `RequestValidationError` 的 handler 改回 `400`。這件事兩個服務都要做，放在 `task07_common` 裡一併提供。

### 5. Guest 的攔截維持在前端，後端只做兜底

- Guest 現在就不送請求（`onenote_review.py:668`），這個行為保留，因為它讓試玩的訪客不會消耗 LLM 配額，也不會產生 audit log 雜訊。

- 後端仍然實作「驗簽通過但不在允許清單內就回 403」，理由是後端不該假設前端一定會擋下，不過正常流程下後端的這條實作路徑不會被觸發。

### 6. `_LLMServiceGuard` 只鎖兩個寫入方法

- `record_failure` 與 `record_success` 各自以 `threading.Lock` 包住整個方法本體。`is_open` 不加 `threading.Lock`。三者判斷分別如下：

        - `record_failure` 的鎖必須涵蓋 `if self._consecutive >= self.max` 的判斷，不能只鎖 `+= 1`：三個步驟（累加、判斷、跳脫並歸零）必須是一個不可分割的動作，否則兩條執行緒可能都看到門檻值、都設一次冷卻時間。

        - `record_success` 雖然只是兩行賦值，仍要鎖，因為它必須與 `record_failure` 互斥。否則可能出現「`record_failure` 跳脫到一半，`record_success` 把計數歸零，`record_failure` 接著設定冷卻」的矛盾狀態。

        - `is_open` 不鎖的理由是，它讀出「冷卻到什麼時候結束」這一個數字，但自己不改任何東西，所以不會發生「別人改到一半就被它讀走」的情況。

### 7. gunicorn 換 uvicorn，維持單一 worker

```
uvicorn <module>:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --timeout-keep-alive 600
```

- 路由函式用 `def` 而非 `async def`。底層的 pymongo、google-cloud-storage、genai 都是 blocking client，寫成 `async def` 會把事件迴圈卡住；用 `def` 讓 FastAPI 自動丟到 threadpool，行為與現在的 gunicorn threads 相同。

- 兩個服務都維持單一 worker，但理由不同：

        - Silver 的單一 worker 是 `_LLMServiceGuard` 的必要條件。它是 module 層級的單例，狀態存在 process 記憶體裡，開多個 worker 會變成每個 process 各持一份計數，斷路器形同失效。

        - Gold 沒有這個限制，但也沒有開多 worker 的理由。兩支 workflow 都沒有指定 `--cpu`，所以兩個服務都只有 1 個 CPU，在 1 個 CPU 上開多 worker 只是讓幾個 process 互搶同一顆核心。需要同時處理更多請求時，Cloud Run 的做法是增加實例，不是在同一個容器裡增加 worker。

- 要留意 worker 數不等於同時能處理的請求數。路由寫成 `def` 之後，FastAPI 會把每個請求丟進 threadpool，所以單一 worker 照樣能同時處理多個請求，行為跟現在的 `gunicorn --workers 1 --threads 8` 一樣。`--workers` 控制的是 process 數量。

### 8. 登入的 OIDC provider 直接用 Google

- `st.login()` 需要的是一個標準 OIDC provider：對外公開 discovery 文件（`/.well-known/openid-configuration`），文件裡列出 `authorization_endpoint`、`token_endpoint` 與 `jwks_uri`，並且發給本應用程式一組 `client_id` 與 `client_secret`。設定方式是在 `.streamlit/secrets.toml` 填入 `server_metadata_url`、`client_id`、`client_secret`，其餘轉址、換證與驗簽由 Streamlit 自行完成。

- Google 符合上述條件，discovery 網址為 `https://accounts.google.com/.well-known/openid-configuration`，OAuth Web client 在同一個 GCP 專案建立即可，因此直接以 Google 為 provider。

- 限制登入者的做法是 OAuth 同意畫面的測試使用者名單。本專案的 GCP 帳號沒有 Workspace 組織，同意畫面只能選 External；維持 Testing 狀態時只有列在測試使用者名單內的帳號能完成登入，名單上限 100 人。這道關卡由 Google 執行，不需要在專案內實作或部署任何東西。

- **其他替代方案**：以 GCP Identity Platform（GCIP）作為登入來源。難點在 `st.login()` 這一步：GCIP 在 OIDC 的角色是 relying party 而非 provider，它的設定介面 `create_oidc_provider_config(provider_id, client_id, issuer, ...)` 是讓 GCIP 去承接某個外部 provider，本身不對外提供可供第三方應用程式對接的 `authorization_endpoint` 與 `token_endpoint`，也沒有給應用程式用的 discovery 文件。因此 `secrets.toml` 無從填寫，`st.login()` 用不上，登入流程的轉址、以授權碼換取 token、驗簽、登入狀態 cookie 與 token 續期五個步驟都要自行實作；限制登入者則需另外撰寫並部署一個 `beforeSignIn` blocking function，多一個獨立的 Cloud Function 部署單位。以本次的規模與維護成本考量不採納。

## Risks / Trade-offs

- **Dashboard 仍在信任鏈上。** 信任鏈變成「Google 驗人，dashboard 轉述並簽名」。dashboard 的程式碼理論上可以為任何 email 簽 JWT。但這仍比現況 (變更前) 好，因為現況是任何知道 demo 帳密的人都能宣稱自己是 Note Owner 去呼叫 Silver 與 Gold 服務；改完之後，能宣稱身分的只剩我們自己部署的那份程式碼。要完全移除這層信任得自己實作 OAuth code flow 以取得原始 ID token，代價是登入流程的 cookie、session 與 refresh 都要自己維護，因超出目前專案管理人的知識範圍之外，故本次不做。
- **JWT 到期時間要拿捏。** 太短會讓使用者在審查頁停留久了之後操作失敗，太長則延長被盜用的時間窗。初步取五分鐘，並在每次呼叫端點前重新簽發，而不是登入時簽一次存起來。
- **允許清單改動要重新部署。** 清單在環境變數裡，加一個 email 要改 Secret Manager 並重新部署三個服務。以預期的異動頻率（幾乎不變）來說可以接受。
- **測試使用者名單要手動維護。** 要讓新的人登入，必須到 OAuth 同意畫面加入測試使用者，上限 100 人。若日後把同意畫面改成 Published 狀態，這道關卡會消失，屆時擋人就只剩應用程式端的 `USER_ALLOWLIST`。
- **登入依賴 Streamlit 的內建 OIDC 功能。** 它在 1.42 版才加入，升版時若行為改變會直接影響登入流程。`requirements.txt` 目前釘在 `streamlit==1.59.1`。
- **本地開發流程會變。** 現在只要填四組帳密就能跑起來，改完之後地端要設定 OIDC 的 `redirect_uri` 與 `cookie_secret`，`.streamlit/secrets.toml` 要另外準備且不可進版控。
- **既有測試會失效。** 任何直接對 Flask test client 送請求的測試都要改寫成 FastAPI 的 `TestClient`，並補上 `X-User-Token`。
