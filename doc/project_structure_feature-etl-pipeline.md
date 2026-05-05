# The project folder in the branch of feature/etl-pipeline
```
    feature/etl-pipeline/
        ├── .env
        ├── pyproject.toml
        ├── task01_obsidian_etl/
        │   ├── __init__.py
        │   ├── e_scan_obsidian.py       # 掃描vault內所有.md 檔、解析 frontmatter
        │   ├── t_transform_obsidian.py  # 清洗、分類、統計邏輯
        │   ├── l_load_to_mongodb.py     # 寫入 MongoDB
        │   └── main.py                  # 執行
        │
        ├── task02_github_restapi_etl/
        │   ├── __init__.py
        │   ├── e_request_github_api.py  # 獲取個人持有或協作的repos之詳細資訊，包含commit次數、訊息、readme連結
        │   ├── t_transform_github.py    # 清洗、分類、統計邏輯
        │   ├── l_load_to_mongodb.py     # 寫入 MongoDB
        │   └── main.py                  # 執行
        │
        └── tests/
            └── test_task01_obsidian_etl.py   # 快速驗證用
```

# Schema design of MongoDB collection in task01
```json
    // Collection name: `obsidian_notes`
    {
    "_id": "ObjectId",
    "file_name": "2024-01-15_daily.md",
    "file_path": "/vault/01_daily-logs/2024-01-15_daily.md",
    "note_type": "daily-log",          // daily-log | knowledge-base | projects
    "tags": ["python", "sql"],
    "alias": "Python基礎筆記",
    "date": "2024-01-15",
    "topic": "python",                  // 從tags或資料夾推斷的主分類
    "word_count": 342,
    "created_at": "2025-04-23T10:00:00"
    }
```

```json
    // Collection name: `obsidian summary`
    {
    "_id": "ObjectId",
    "snapshot_date": "2025-04-23",
    "total_notes": 87,
    "by_type": {
        "daily-log": 40,
        "knowledge-base": 32,
        "project": 15
    },
    "by_topic": {
        "python": 18,
        "sql": 12,
        "ml": 8,
        "cloud": 6,
        "biotech": 14,
        "other": 29
    }
    }
```

# Schema design of MongoDB collection in task02
```json
    // Collection name: `github_repos` (One document means one repo)
    {
        "repo_id": 123456789,
        "repo_name": "etl-pipeline",
        "repo_full_name": "yourname/etl-pipeline",
        "description": "...",
        "language": "Python",
        "is_private": false,
        "role": "owner",           // owner | collaborator
        "created_at": "2024-01-01T00:00:00Z",
        "pushed_at": "2025-04-23T10:00:00Z",
        "commit_count": 42,
        "commits": [
                    {
                        "sha": "abc123",
                        "message": "init: scaffold ETL structure",
                        "committed_at": "2025-04-20T09:00:00Z"
                    }
                    ],
        "readme_summary": "This project is an ETL pipeline...",  // 前 300 字
        "readme_html_url": "https://github.com/jessie/my_repo/blob/main/README.md",
        "topics": ["etl", "python", "mongodb"],
        "stars": 0,
        "fetched_at": "2026-04-28T10:00:00Z"
    }
```

```json
    // Collection name: github_summary
    {
    "snapshot_date": "2026-04-28",
    "total_repos": 15,
    "by_role": { "owner": 12, "collaborator": 3 },
    "by_language": { "Python": 8, "SQL": 2, "Shell": 1, "other": 4 },
    "total_commits": 287,
    "recent_repos": [              
        { "repo_name": "...", "pushed_at": "...", "language": "..." }
    ]
    }
```

# Schema design of MongoDB collection in task03
```json
    // Collection name: `solved_problems_on_ccClub` (One document means one problem solved before)
    {
        {"problem_id": "180001",
        "problem_type": "ACM", 
        "score": 0, 
        "topic": ["String"], 
        "difficulty": "Low"
        }
    }
```

```json
    // Collection name: `solved_problems_on_leetcode` (One document means one problem solved before)
    {
    {"frontendQuestionId": "1", // 對應API回傳的data/problemsetQuestionList/questions/frontendQuestionId
    "title": "Two Sum",// 對應API回傳的data/problemsetQuestionList/questions/title
    "topic": ["string", "database"], // 對應API回傳的data/problemsetQuestionList/questions/topicTags之name欄位
    "difficulty": "Low" //對應API回傳的data/problemsetQuestionList/questions/difficulty
    }
    }
```

```json
    // Collection name: `ccClub&leetcode_summary`
    {
    "snapshot_date": "2026-04-28",
    "totalSolvedProblemsOnCCclub": 264, // 計算collection documents
    "totalSolvedProblemsOnLeetcode": 15, // 計算collection documents
    "problemDifficultyOnLeetcode": [ { "difficulty": "Easy", 
                                    "percentage": 81.71},
                                  {"difficulty": "Medium",
                                   "percentage": 17.74},
                                  {"difficulty": "Hard",
                                  "percentage": null}
                                ], // 對應API回傳的data/matchedUser/problemsSolvedBeatsStats
    "problemDifficultyOnCCclub": [ {   
                                  "difficulty": "Easy",
                                    "percentage": 81.71},
                                  {"difficulty": "Medium",
                                   "percentage": 17.74},
                                  {"difficulty": "Hard",
                                  "percentage": null}
                                ], // 需要自行從collection `solved_problems_on_ccClub`自行計算
    "topicsPercentOnCCclub": {"string": 20.0, "math": 80.0, "link-list": 0}, // 從計算collection `solved_problems_on_ccClub`的topic，計算後以百分比呈現
    "topicsPercentOnLeetcode": {"string": 13.4,     "math": 12.6, "link-list": 74.0}// 取自collection `solved_problems_on_leetcode`的topic，計算後以百分比呈現
    }
```