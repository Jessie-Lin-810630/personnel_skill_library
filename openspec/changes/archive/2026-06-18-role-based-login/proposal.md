## Why

OneNote Review 頁面目前以單一密碼登入，登入後再以 `st.radio` 自選角色。實務上三種角色（ML/DL Engineer、Note Owner、Dept. Senior Specialist）應各持獨立帳密，角色由帳密決定而非使用者自行選擇，避免任意切換。

## What Changes

- 登入表單改為 **username + password** 雙欄位
- 比對三組角色帳密，成功後角色自動帶入 `st.session_state.role`
- 移除登入後的 `st.radio` 角色選擇器，改以唯讀文字顯示目前登入角色
- 新增「登出」按鈕，清除 session 回到登入頁
- 舊的單密碼環境變數 `REVIEW_PAGE_PASSWORD` 由六個角色帳密變數取代

## Capabilities

### New Capabilities

- `role-based-login`：帳密決定角色的登入 gate，支援三組獨立憑證

### Modified Capabilities

- `onenote-review-page`：登入 gate 改為 username/password、移除 radio、加登出按鈕

## Impact

- **修改檔案**：`dashboard_ui/pages/onenote_review.py`
- **環境變數**：移除 `REVIEW_PAGE_PASSWORD`，新增 `ROLE_ML_USER` / `ROLE_ML_PASS` / `ROLE_OWNER_USER` / `ROLE_OWNER_PASS` / `ROLE_SENIOR_USER` / `ROLE_SENIOR_PASS`
- **無新增檔案**、**無 MongoDB 寫入**（登入 log 列為後續雲端部署再補）
