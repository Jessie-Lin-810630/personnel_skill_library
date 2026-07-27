## Context

`onenote_review.py` 現有單密碼 gate + 登入後 radio 角色選擇。目標是讓帳密直接決定角色，同時保持 demo 易操作（一人可開三分頁模擬三角）。

## Goals / Non-Goals

**Goals:**
- 登入表單改為 username + password
- 三組帳密對應三個角色，比對失敗顯示通用錯誤訊息（不揭露哪組錯）
- 登入後顯示唯讀角色標籤 + 登出按鈕
- 移除 `st.radio` 角色選擇器

**Non-Goals:**
- 登入失敗計數 / 鎖定機制
- 登入 log 寫入 MongoDB（雲端部署階段再補）
- 加密儲存密碼（demo 等級，env var 明文即可）

## Decisions

### 帳密比對邏輯

從環境變數讀取三組 `(username, password, role)` tuple，登入時逐一比對；找到第一個完全符合的即成功。比對失敗一律顯示「帳號或密碼錯誤」，不揭露是哪組不符。

```python
CREDENTIALS = [
    (os.getenv("ROLE_ML_USER",""), os.getenv("ROLE_ML_PASS",""), "ML/DL Engineer"),
    (os.getenv("ROLE_OWNER_USER",""), os.getenv("ROLE_OWNER_PASS",""), "Note Owner"),
    (os.getenv("ROLE_SENIOR_USER",""), os.getenv("ROLE_SENIOR_PASS",""), "Dept. Senior Specialist"),
]
```

### Session 狀態

成功登入後設定：
- `st.session_state.authenticated = True`
- `st.session_state.role = <matched_role>`

登出時清除 `authenticated` 與 `role`，呼叫 `st.rerun()`。

### 登入後角色顯示

移除 `st.radio`，改以 `st.markdown` inline 顯示：
```
目前角色：**ML/DL Engineer**　[登出]
```
登出按鈕放在同一行右側（用 `st.columns` 對齊）。

## Risks / Trade-offs

- **明文帳密**：env var 不加密，符合 demo 定位；雲端部署時改由 GCP Secret Manager 管理
- **無 HTTPS**：本地開發無 TLS，密碼明文傳輸，demo 可接受
