## 1. 環境變數

- [x] 1.1 提醒使用者在 `.env` 移除 `REVIEW_PAGE_PASSWORD`，新增六個角色帳密變數：`ROLE_ML_USER` / `ROLE_ML_PASS` / `ROLE_OWNER_USER` / `ROLE_OWNER_PASS` / `ROLE_SENIOR_USER` / `ROLE_SENIOR_PASS`

## 2. 修改 onenote_review.py

- [x] 2.1 移除 `REVIEW_PASSWORD = os.getenv("REVIEW_PAGE_PASSWORD", "")` 單密碼讀取，改為定義 `CREDENTIALS` list（三組 username/password/role tuple）
- [x] 2.2 登入 gate：將 `st.text_input("密碼")` 改為 username + password 雙欄位；實作比對邏輯；空白輸入提示「請輸入帳號與密碼」
- [x] 2.3 移除登入後的 `st.radio` 角色選擇器
- [x] 2.4 新增唯讀角色標籤（`目前角色：{role}`）+ 右側「登出」按鈕，按下清除 session 並 `st.rerun()`

## 3. 驗證

- [x] 3.1 語法檢查（`python -c "import ast; ast.parse(open('...').read())"`）
- [x] 3.2 提示使用者啟動 Streamlit，以三組帳密分別在不同分頁登入，確認角色正確顯示且互不干擾
