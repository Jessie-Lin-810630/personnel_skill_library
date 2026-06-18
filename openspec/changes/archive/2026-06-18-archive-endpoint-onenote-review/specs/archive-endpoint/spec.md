# archive-endpoint

## Overview

獨立的 Archive 端點服務，接收 Streamlit `onenote_review.py` 的審核動作，將 staging vault（`onenote-vaults`）的筆記物件歸檔至 personal vault（`personal-vaults`），並更新 MongoDB `onenote_page_metadata` 狀態。

## Endpoint

`POST /archive`

### Request Body

```json
{
  "page_id": "<string>",
  "role": "<ML/DL Engineer | Note Owner | Dept. Senior Specialist>",
  "action": "<approved | rejected>"
}
```

### Response

- `200 OK`：`{"status": "ok"}`
- `400 Bad Request`：缺少必要欄位
- `404 Not Found`：`page_id` 在 `onenote_page_metadata` 查無記錄
- `500 Internal Server Error`：`{"error": "<message>"}`

## Behavior

### action == "approved"

1. 查 MongoDB `onenote_page_metadata` 取得 `html_path`、`md_path`、`notebook`、`section`、`note_type`（預設 `uncategorized`）
2. 複製 PNG：`onenote-vaults/{account}/{notebook}/{section}/_images/*.png` → `personal-vaults/{account}/from-onenote/{note_type}/{notebook}/{section}/_attachment/*.png`
3. PNG 複製完成後，upsert `img_archive_path`（逗號分隔 blob 路徑或 JSON array）
4. 讀取 staging MD（`onenote-vaults/{account}/{notebook}/{section}/{page}.md`），將 `_images/{file}` 替換為 `./_attachment/{file}`
5. 寫入 MD：`personal-vaults/{account}/from-onenote/{note_type}/{notebook}/{section}/{page}.md`
6. MD 寫入完成後，upsert `md_archive_path`
7. 兩者完成後，一次 upsert：`status="archived"`, `review_result="approved"`, `reviewed_by_role=role`, `reviewed_at=utcnow`, `archived_at=utcnow`
8. Staging 物件（html/md/png）**不刪除**

### action == "rejected"

1. 查 MongoDB 確認 `page_id` 存在
2. Upsert：`status="rejected"`, `review_result="rejected"`, `reviewed_by_role=role`, `reviewed_at=utcnow`
3. GCS 不操作

## MongoDB Upsert Key

Collection: `onenote_page_metadata`  
Upsert 唯一鍵：`page_id`

## GCS Path Derivation

- Account name：從 `html_path` strip `ONENOTE_OUTPUT_DIR/` 後取第一層目錄名
- Staging blob prefix：strip `ONENOTE_OUTPUT_DIR/` 得到 `{account}/{notebook}/{section}/{page}.html`，section prefix = `{account}/{notebook}/{section}`

## Environment Variables

| 變數 | 說明 |
|------|------|
| `MONGO_ALTAS_URI` | MongoDB Atlas 連線字串 |
| `MONGO_DB_NAME` | MongoDB 資料庫名稱 |
| `GOOGLE_APPLICATION_CREDENTIALS` | GCS service account JSON 路徑 |
| `ARCHIVE_PERSONAL_BUCKET` | personal vault bucket 名稱（預設 `personal-vaults`） |
| `ONENOTE_OUTPUT_DIR` | OneNote 本地輸出根目錄（用於 blob 路徑推導） |
