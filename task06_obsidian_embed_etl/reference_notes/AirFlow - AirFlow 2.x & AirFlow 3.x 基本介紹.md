
---
tags: [Orchestration, AirFlow, AirFlow-2, AirFlow-3]
date: 2026-01-18
type: knowledge_summary
alias: [AirFlow Introduction]

---

# 目的
歸納 AirFlow 基本功能與組成元件。

# AirFlow 基本介紹
- AirFlow 是一種 Workflow Orchestration (工作流編排) 工具，用以自動化管理排程、追蹤紀錄異常節點。
- 底層用 python 寫成，使用者可透過 python 程式碼來定義、排程與監控複雜的工作流程。
- AirFlow 由於最早進入市場，2014 年開源，目前 community 最大，2025 年可以開始使用 Airflow 3.x 版本、但可能部分團隊還正在使用AirFlow 2.x。
- 其他競品：Prefect (後起之秀、致力在解決airflow的某些痛點，例如：簡化一點ETL pipelines)、dbt (外商或像外商的台商在使用，例如：Dcard、piko)。

# AirFlow 誰在用？
- **資料工程師（Data Engineers）：** 建立穩定、自動化的 ETL/ELT 資料管道（Data Pipeline）。
- **資料科學家 / 機器學習工程師（Data Scientists / MLEs）：** 自動化模型訓練、特徵工程與定時預測流程。
- **維運工程師（DevOps / SREs）：** 處理定時的系統備份、日誌清理或跨雲端服務的資源調度。
### 現代編排工具推出前，遇到的痛點
- **相依性混亂：** 步驟 B 必須等步驟 A 成功才能執行，如果步驟 A 遲到或失敗，後續很難自動處理。
- **黑盒子與維護地獄：** 任務散落各處，不知道哪裡出錯，缺乏統一的監控與警報機制。
- **重試機制 (Retry) 困難：** 網路斷線導致某個 API 失敗，需要手動重跑或寫複雜的程式碼來處理重新嘗試。
### Cron Jobs
- Linux Cron Jobs 是早期最傳統的方法。雖然定時很準，但**完全無法處理任務之間的跨伺服器相依性**。如果 A 機器上的腳本失敗了，B 機器的 Cron Job 依然會傻傻地啟動，導致資料出錯。

# 需要自動化管理排程的情境
- 定期做、監控工作狀態、無法執行某步驟時要留記錄、設定重跑時機、次數、自動化排程工作要在哪一台電腦 (worker)、哪一台電腦負責做監控整個進度。
- 節錄[官方文件](https://airflow.apache.org/docs/apache-airflow/2.2.5/concepts/overview.html)描述，AirFlow 可管理這種排程：
	- 收集資料、分析或清理資料、確認資料完整性或任務完成度，當有報錯則信箱告警；若無則存入資料庫或是寫入檔案，最後印出任務執行報告。
	![[airflow_intro_image01.png]]

# 教材
- [https://github.com/uuboyscy/airflow-demo](https://github.com/uuboyscy/airflow-demo)

# 如何在 AirFlow 定義工作流程
- 在 Airflow 中，工作流程被定義為 **DAG (Directed Acyclic Graph，有向無環圖)**。每個 DAG 裡面包含許多 Task (任務)，例如：E_步驟 A (爬取天氣資料) -> T_步驟 B (清理資料) -> L_步驟 C(寫入資料庫)。有就是說，工作流程稱為 DAG、工作步驟稱為 Task；==一個 DAG 描述了需要哪些 Tasks 以及這些 **Tasks 的依賴性 (Task dependencies)**。==
- 在實務上，也可以增加 Util (工具) ，在執行各種任務調用工具，這些工具通常是簡易的、沒有固定或完整的商務邏輯，可能是某些函式 (function) 或類別 (class)，但需要在執行任務期間不斷被使用的，例如：不論是哪個業務邏輯，都需要連線資料庫，所以連線用的程式碼可以被包成函式，然後放在 Util 便於調用，也避免重複撰寫連線腳本。
- Task 通常被特定 DAG 綁定，每個 DAG 有其獨特的 Task 組成；Util 則可以被多個 Task 呼叫、甚至也可以在 DAG 層級直接呼叫 Util 來用。
- DAG 與 Task 的關聯圖一般來說可在 AirFlow 的 UI 介面看到，Util 則不會，需要直接檢視 Task/DAG 的程式碼才可能抓得出來哪些是 Utils。

# AirFlow 核心元件
根據[官方文件](https://airflow.apache.org/docs/apache-airflow/2.2.5/concepts/overview.html)，使用 AirFlow 編排、管理任務時，需要以下元件互相協調工作：
	![[airflow_intro_image02.png|492]]
1. **Scheduler**：
	- 負責解析 DAG (= 解析要做什麼 task、模組/util 是否能被正常 import、 task 的程式碼內容在執行前是否有語法錯誤)、決定 DAG 實際執行時間、DAG 啟動後交給 Executor 做任務分發、監控排程並標記 tasks 與 DAGs 的狀態 (e.g. queue、fail、success)。
	- 可以同時啟動多個 Schedulers。
2. **Executor**：
	- 埋在 Scheduler 進程內的一個物件，負責「決定怎麼執行任務」的策略層。
	- Executor 在 AirFlow 的原始碼中，是被包成 Scheduler 類別的一個變數。
	- 在啟動 Scheduler 時，Executor 就會被實例化，無關乎 DAG 怎麼寫。
	- 一個 Scheduler 只有一個 Executor。 ==**AirFlow 允許從多種 Executors 之間擇一設定，不同的 Executor 會影響任務的執行順序數量。**==
	- Executor 負責管理任務的分發、追蹤任務狀態，本身**也不直接跑任務邏輯**。
	- Executor 把任務分發給 Workers 執行。
3. **Worker**：
	- Worker 是獨立於 Scheduler/Executor 的一個進程 (= 執行時有自己的記憶體空間)，Worker 是真正執行任務的元件，一個 DAG 可以由多個 Workers 完成。
	- 小型開發為目的而配的 Executor ，不一定有 Worker、而是直接在 Scheduler 完成；而適用於生產環境的 Executor，通常會分派執行工作給多個 Workers。
4. **Metadata Database**： 
	- Scheduler 會將任務狀態記錄在 Metadata Database，因此啟動 AirFlow 的時候必須確保 給予 Scheduler 有足夠的讀寫權限。
	- 預設是 SQLite，但通常生產環境會建議使用 PostgreSQL 或 MySQL 等其他資料庫s。
5. **Webserver**：前端互動介面，讓開發、維護人員在圖形介面監控任務。


# AirFlow 2.x & AirFlow 3.x 的變革與突破
### AirFlow 2.x
- 舊版 Airflow 的 Scheduler 有單點故障問題。2.0 引入了可以同時啟動多個 Scheduler 的機制，大幅提升了效能與穩定性。
- 以前在任務之間傳遞資料 (XCom) 很麻煩。==**2.0 引入了 TaskFlow API，只要用 Python 的 `@task` 裝飾器，就能像寫一般 Python 函式一樣自然地傳遞資料，也就是撰寫 DAG 的語法糖。**==
### [AirFlow 3.x](https://airflow.apache.org/blog/airflow-three-point-oh-is-here/)
- **DAG 版本控制 (DAG Versioning)**：Airflow 3 實現後，即使在 DAG 執行中上傳了新版本，執行中的 DAG run 仍會以啟動時的版本跑完。所有 DAG run 在 UI 中都會關聯對應的 DAG 版本，包含 Task 結構、程式碼、log 等。
- **Backfill 改善**：改由 Scheduler 統一管理，提升了控制性、可擴展性與診斷能力，並可從 UI 或 API 發起，也可在 UI 中監控進度。
- **全新 UI**：UI 以 React 和 FastAPI 全面重構，Asset 導向與 Task 導向的工作流程可無縫切換，讓開發者自由選擇開發方式，不強制規定「唯一正確做法」。

# 建議專案資料夾架構
^db93cb

```
 my-project/
	├── README.md
	├── .env
	├── .gitignore
	│
	├── .github/
	│   └── workflows/
	│
	├── dags/               # AirFlow DAGs scheduling ETL pipeline
	│   ├── tasks/          # Tasks constributing DAGs
	│   └── utils/
	│
	├── docker/
	│   └── Dockerfile.airflow
	│
	├── docker-compose.yml
	├── requirements.txt
	└── docs/
		└── xxx.md
```
