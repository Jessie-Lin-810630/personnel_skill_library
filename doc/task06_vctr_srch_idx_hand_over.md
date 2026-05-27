# Task06 Hand-over：MongoDB Atlas Vector Search Index 建立與驗證

> 官方文件參考：
> - Index 定義語法1：https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-type/
> - Index 定義語法2: https://www.mongodb.com/zh-cn/docs/vector-search/index/vector-search-type/?deployment-type=atlas&embedding=byo&interface=mongosh
> - $vectorSearch 查詢語法：https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/
> - Quick Start：https://www.mongodb.com/docs/atlas/atlas-vector-search/tutorials/vector-search-quick-start/

---

## 前置條件確認

在開始建立 index 之前，確認以下三項都已就緒：

- `obsidian_vectors` 集合已存在（執行過 `l_upsert_vectors.py` 且至少 upsert 過一筆 vector doc）
- 每筆 doc 的 `embedding` 欄位是長度 **1536** 的 `list[float]`（對應 `text-embedding-3-small`的向量維度）
- Atlas 帳號身份有 **Project Search Index Editor** 以上角色權限

---

## Step 1：進入 Atlas Console，找到文檔集 obsidian_vectors

1. 登入 [https://cloud.mongodb.com](https://cloud.mongodb.com)
2. 左側選單 → **Database** → 進入 Cluster
3. 點 **Browse Collections** → 選資料庫 `skill_dashboard` → 選文檔集 `obsidian_vectors`
4. 上方 tab 列點 **Search Indexes**

---

## Step 2：建立 Vector Search Index（JSON Editor）

1. 點右上角 **Create Search Index**
2. 選擇 **Atlas Vector Search**（不是 Atlas Search）
3. Index 建立方式選 **JSON Editor**
4. 填入以下設定：

**Index Name：**
```
obsidian_vectors_index
```

**Database / Collection：**
```
skill_dashboard  /  obsidian_vectors
```

**JSON 定義（貼入 JSON Editor）：**

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 1536,
      "similarity": "cosine"
    },
    {
      "type": "filter",
      "path": "tags"
    },
    {
      "type": "filter",
      "path": "note_type"
    }
  ]
}
```

**欄位說明：**

| 欄位 | 值 | 說明 |
|------|-----|------|
| `path` | `"embedding"` | 對應 vector doc 的 `embedding` 欄位名稱 |
| `numDimensions` | `1536` | 必須與 `text-embedding-3-small` 輸出維度完全吻合；**此值建立後無法修改** |
| `similarity` | `"cosine"` | 語意搜尋的標準選擇；衡量向量方向的相似度，忽略長度差異 |
| `filter: tags` | — | 讓 $vectorSearch 可以先 filter tag 再做向量搜尋（pre-filter） |
| `filter: note_type` | — | 同上，可依筆記類型縮小搜尋範圍 |

5. 點 **Next**，確認設定，點 **Create Search Index**
6. 等待 Status 從 `BUILDING` 變成 `READY`（M0 需 1–3 分鐘）

---

## Step 3：用 mongosh 驗證 Index 已建立

開啟 mongosh（Atlas Console 右上角 → **Connect** → **Shell**）或是用 3T GUI 工具連線 MongoDB Altas，執行：

```js
use obsidian_db
db.obsidian_vectors.getSearchIndexes()
```

預期輸出應包含：

```json
[
  {
    "name": "obsidian_vectors_index",
    "type": "vectorSearch",
    "status": "READY",
    ...
  }
]
```

---

## Step 4：用 $vectorSearch 跑一次驗證查詢

用 mongosh 跑以下查詢，確認 vector search 能正確回傳結果。
`queryVector` 是隨機測試向量（1536 個 0），正式環境會替換成使用者問題的 embedding。

```js
use obsidian_db

db.obsidian_vectors.aggregate([
  {
    $vectorSearch: {
      index: "obsidian_vectors_index",
      path: "embedding",
      queryVector: Array(1536).fill(0.01),  // 測試用，正式環境換成問題的 embedding
      numCandidates: 50,                    // Atlas 從中找候選者的數量，建議是 limit 的 10 倍
      limit: 5                              // 回傳 top-K 筆，此處 K=5
    }
  },
  {
    $project: {
      _id: 0,
      file_name: 1,
      section: 1,
      content: 1,
      score: { $meta: "vectorSearchScore" }  // 相似度分數，範圍 0–1，越高越相似
    }
  }
])
```

預期輸出：回傳 5 筆 chunk，每筆有 `file_name`、`section`、`content`、`score` 欄位。

---

## Step 5（Optional）：加上 pre-filter 測試

確認 `tags` 的 filter 有效（例如只搜尋 MySQL 相關筆記）：

```js
db.obsidian_vectors.aggregate([
  {
    $vectorSearch: {
      index: "obsidian_vectors_index",
      path: "embedding",
      queryVector: Array(1536).fill(0.01),
      numCandidates: 50,
      limit: 5,
      filter: { tags: "MySQL" }   // pre-filter：只在有 MySQL tag 的 chunk 裡搜尋
    }
  },
  {
    $project: {
      _id: 0,
      file_name: 1,
      tags: 1,
      section: 1,
      score: { $meta: "vectorSearchScore" }
    }
  }
])
```

---

## 注意事項

- **numDimensions 無法修改**  
Index 建立後 `numDimensions` 不可更改。未來若換 Gemini Embedding 2（維度 3072），
需要建立新 index（例如命名 `obsidian_vectors_index_v2`），並重跑全量 embedding upsert。

- **為什麼選 cosine 不選 euclidean**  
支援的 similarity 函數有三種：cosine、euclidean、dotProduct。語意搜尋標準選 cosine，因為它衡量的是向量方向的相似度而不是距離，語意相近的文字向量角度小，與向量的長度無關

- **numCandidates 的建議值**  
官方建議 `numCandidates` 至少是 `limit` 的 10 倍，最大不超過 10,000。
數字越大、結果越精準，但查詢速度越慢。RAG 應用 top-5 情境設 50 即可。

- **M0 免費層的限制**  
Atlas M0 支援 Vector Search，但有以下限制：
    - 最多 3 個 Search Index（包含 Vector Search Index）
    - 向量維度上限 2048（1536 安全在範圍內）
    - 不支援 storedSource 功能

