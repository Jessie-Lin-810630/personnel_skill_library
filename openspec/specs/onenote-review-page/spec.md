## ADDED Requirements

### Requirement: Demo login gate
未通過驗證的使用者 SHALL 看到密碼輸入框；密碼與 `REVIEW_PAGE_PASSWORD` 環境變數比對，不符則頁面停止渲染。通過後 `st.session_state.authenticated = True` 並保持整個 session 有效。

#### Scenario: Correct password unlocks the page
- **WHEN** 使用者輸入正確密碼並送出
- **THEN** 頁面顯示完整審核介面，密碼框消失

#### Scenario: Wrong password blocks page
- **WHEN** 使用者輸入錯誤密碼
- **THEN** 顯示「密碼錯誤」提示，頁面停止渲染

---

### Requirement: Role selector
通過登入後，頁面頂部 SHALL 提供角色選擇（ML/DL Engineer、Note Owner、Dept. Senior Specialist）。所選角色存入 `st.session_state.role`，並在觸發 Archive 時一併帶出。

#### Scenario: Role persists during session
- **WHEN** 使用者選擇角色並切換到不同頁面後返回
- **THEN** 角色選擇保持原選項不重置

---

### Requirement: Three-level note selector
頁面上方 SHALL 提供筆記本 → 章節 → 頁面三層下拉選擇器，資料來源為 `onenote_page_metadata` collection。切換筆記本時章節清單重新篩選，切換章節時頁面清單重新篩選。

#### Scenario: Notebook selection filters sections
- **WHEN** 使用者選擇一個筆記本
- **THEN** 章節下拉只顯示該筆記本下的章節

#### Scenario: Section selection filters pages
- **WHEN** 使用者選擇一個章節
- **THEN** 頁面下拉只顯示該章節下的頁面

---

### Requirement: Status badge at top
選定頁面後，頁面頂部 SHALL 顯示當前 `status` 的狀態標籤（pending_review / archived / 其他）。

#### Scenario: Pending review badge shown
- **WHEN** 選定頁面的 `status` 為 `pending_review`
- **THEN** 顯示「待審核」狀態標籤（黃色/橘色）

#### Scenario: Archived badge shown
- **WHEN** 選定頁面的 `status` 為 `archived`
- **THEN** 顯示「已歸檔」橫幅（綠色），並標示 `reviewed_at`

---

### Requirement: Side-by-side HTML and MD view
選定頁面後，頁面 SHALL 以左右兩欄並排顯示：
- 左欄：原始 HTML（從 GCS `onenote-vaults/{帳號}/{筆記本}/{章節}/{頁名}.html` 讀取），以 `st.components.v1.html()` 渲染，HTML 內嵌圖片以 base64 data URI 替換 `_images/` 路徑
- 右欄：轉換後的 MD（從 GCS `onenote-vaults/{帳號}/{筆記本}/{章節}/{頁名}.md` 讀取），以 `st.markdown()` 渲染，MD 內 `![](\_images/foo.png)` 同樣以 base64 data URI 替換

#### Scenario: HTML renders with embedded images
- **WHEN** 使用者選定一個含圖片的頁面
- **THEN** 左欄 HTML 中的圖片正確顯示，不出現破圖

#### Scenario: MD renders with embedded images
- **WHEN** 使用者選定一個含圖片的頁面
- **THEN** 右欄 MD 中的圖片正確顯示，不出現破圖

#### Scenario: GCS blob not found
- **WHEN** GCS 上找不到對應的 HTML 或 MD blob
- **THEN** 該欄顯示「找不到檔案」提示，不 crash 頁面

---

### Requirement: Approve and Reject buttons
頁面底部 SHALL 提供「✅ Approve」與「❌ Reject」按鈕。按下後以 `POST {ARCHIVE_ENDPOINT_URL}` 帶上 `page_id` 與 `role`，並在頁面顯示呼叫結果（成功 / 失敗訊息）。

#### Scenario: Approve triggers archive endpoint
- **WHEN** 使用者按下「✅ Approve」
- **THEN** 送出 `POST /archive` 帶 `{page_id, role, action: "approved"}`，顯示「送出成功」訊息

#### Scenario: Reject triggers archive endpoint
- **WHEN** 使用者按下「❌ Reject」
- **THEN** 送出 `POST /archive` 帶 `{page_id, role, action: "rejected"}`，顯示「送出成功」訊息

#### Scenario: Archive endpoint unreachable
- **WHEN** `ARCHIVE_ENDPOINT_URL` 未設定或端點無回應
- **THEN** 顯示連線錯誤訊息，頁面不 crash

#### Scenario: Archived page disables buttons
- **WHEN** 選定頁面的 `status` 為 `archived`
- **THEN** Approve / Reject 按鈕皆為停用狀態（`disabled=True`）
