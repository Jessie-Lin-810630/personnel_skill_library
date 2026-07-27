# Phase II 部署工作流程

## 目標
**在 branch `develop` 完成以下五項部署**
1. **ETL task01**（Obsidian）→ Cloud Run Job
2. **ETL task02**（GitHub）→ Cloud Run Job
3. **ETL task03**（LeetCode/ccClub）→ Cloud Run Job
4. **ETL task05**（Skill Radar / Google Sheets）→ Cloud Run Job
5. **Streamlit Dashboard**（app.py + pages/）→ Cloud Run Service


## Branch Develop 的工作原則

| 項目 | 做法 |
|---|---|
| 繼承來源 | 繼承 `feature/etl-pipeline` + `feature/dashboard-ui` 的所有腳本，如遇到 bug，必須 fix 後合併回feature/* |
| Obsidian .md 同步 | gsutil rsync 上傳至 GCS |
| 環境變數 | **不使用 .env**，全部改存 GCP Secret Manager，因為 Cloud Run 可以refere to Secret Manager 的值，容器啟動即注入這些值變成環境變數 |
| 機密存取方式 | Cloud Run Job/Service 與 Secret Manager 在同一 GCP project，透過 IAM 授權直接存取 |
| Docker Image | 每個 task 獨立打包成 image，*不可內包任何機密* |
| CI/CD | GitHub Actions 負責自動 build image，然後 push to Artifact Registry 與 deploy job |
| 資料庫 | 從 MongoDB localhost 切換到 **MongoDB Atlas** |


## 執行計劃
### Step 0：GCP 前置準備
```
- 建立 GCP Project ID
- 至少啟用以下 API：
    - Cloud Run API
    - Artifact Registry API
    - Secret Manager API
    - Cloud Storage API
- 建立 Artifact Registry repository（repo 採 Docker 格式）
- 建立 GCS Bucket，手動將本地 Obsidian Vault 的 markdown & images 存入 GCS，資料管道打通後可改成 gsutil rsync 指令
```
- 建立 Service Account，授予以下角色 (roles)：

| Service Name  | Artifact Factory  | Google Sheet API  | Cloud Run  | Cloud Storage  | AI Agent Platform  | Grant what roles to service  | Service Account Name  |
|--|--|--|--|--|--|--|--|
| GitHub Actions  | push images to AF  | no interaction  | deploy the container firstly (trigger by `cloud scheduler`)  | no interaction  | no interaction  | - Artifact Registry Reader<br>- Artifact Registry Writer<br>- Workload Identity User<br>- Cloud Run Admin<br>- Service Account User (Granted to *`SA-level` resource: `psd-task01`, `psd-no-gcs-task`, and `psd-embedding-task`*)  | github-cloud-run-deployer  |
| Cloud Scheduler  | no interaction  | no interaction  | trigger the cloud run [job](https://docs.cloud.google.com/iam/docs/roles-permissions/run#run.developer) as scheduled once deployment  | no interaction  | no interaction  | - Cloud Run Developer (Granted to *`job-level` resource: `psd-task01`, `psd-no-gcs-task`, and `psd-embedding-task`*)  | cloud-scheduler-trigger |
| Cloud Run Service Instance -<br>Dashboard-UI (frontend)  | pull images from AF  | no interaction  | invoke the other cloud run instances  | view and download (read) the objects  | call model (LLM, embedding model) to<br>generate result of queries routing, rewrite queries,<br>generate answer in neutral languages.  | - Agent Platform User<br>- Cloud Run Invoker<br>- Secret Manager Secret Accessor<br>- Storage Object Viewer  | person-skill-dashboard  |
| Cloud Run Job Instance -<br>Task01 (DAG01)  | pull images from AF  | no interaction  | no interaction  | list, view, download (read) and create the objects<br>and view objects' metadata in the same bucket  | no interaction  | - Secret Manager Secret Accessor<br>- Storage Object User  | task01  |
| Cloud Run Job Instance -<br>Task02 (DAG02)  | pull images from AF  | no interaction  | no interaction  | no interaction  | no interaction  | - Secret Manager Secret Accessor  | psd-no-gcs-task  |
| Cloud Run Job Instance -<br>Task03 (DAG03)  | pull images from AF  | no interaction  | no interaction  | no interaction  | no interaction  | - Secret Manager Secret Accessor  | psd-no-gcs-task  |
| Cloud Run Job Instance -<br>Task05 (DAG05)  | pull images from AF  | view and edit the sheets on<br>google drive  | no interaction  | no interaction  | no interaction  | - Secret Manager Secret Accessor<br>- Google sheet Editor (從google sheet端啟動'共用'，非 IAM 介面)  | psd-no-gcs-task  |
| Cloud Run Job Instance -<br>Task06 (DAG06)  | pull images from AF  | no interaction  | no interaction  | view and download (read) the objects<br>and view objects' metadata in the same bucket  | call model (embedding model) to<br>generate embeds.  | - Agent Platform User<br>- Secret Manager Secret Accessor<br>- Storage Object Viewer  | psd-embedding-task  |
| Bronze of Task07 (Bronze of DAG07)  | no interaction  | no interaction  | no interaction  | no interaction  | no interaction  | no role  | -  |
| Cloud Run Service Instance -<br>Silver of Task07 (Silver of DAG07)  | pull images from AF  | no interaction  | no interaction  | view, download (read), create and update the objects<br>and view objects' metadata in the same bucket  | call model (LLM) to<br>generate enriched context in neutral languages.  | - Agent Platform User<br>- Secret Manager Secret Accessor<br>- Storage Object User  | psd-enrich-task  |
| Cloud Run Service Instance -<br>Gold of Task07 (Gold of DAG07)  | pull images from AF  | no interaction  | no interaction  | view, download (read) and copy (create) the objects<br>and view objects' metadata in the same bucket  | no interaction  | - Secret Manager Secret Accessor<br>- Storage Object Viewer<br>- Storage Object Creator  | psd-archive-task  |
| Cloud Run Job Instance -<br>Task08 (DAG08)  | pull images from AF  | no interaction  | no interaction  | view and download (read) the objects<br>and view objects' metadata in the same bucket  | call model (embedding model) to<br>generate embeds.  | - Agent Platform User<br>- Secret Manager Secret Accessor<br>- Storage Object Viewer  | psd-embedding-task  |
> **GitHub Actions（github-cloud-run-deployer）解釋**：
> - `gcloud run deploy` 需要有 [Cloud Run Admin 或 Cloud Run Developer ＋ Service Account User (對每支 runtime SA 授 `actAs`)](https://docs.cloud.google.com/run/docs/configuring/description)。Workload Identity User 用來讓 GitHub Actions 利用短期 OIDC tokens 取得使用 GCP API 的權限，實際上能做到什麼程度要看綁 WIF 的這支帳號還有被授權哪些角色，例如： Artifact Registry Reader。
> -  Cloud Run Admin 或 Cloud Run Developer 角色讓 GitHub Actions 有權部署 Cloud Run job container。
> - Service Account User 允許 GitHub Actions 把 runtime SA 綁到 workload (即，指派啟動之 job 要帶什麼 SA)。

### Step 1：MongoDB Atlas 設定
```
- 建立 MongoDB Atlas 免費叢集（M0）
- 建立 database user
- 設定 Network Access → 允許 GCP Cloud Run IP（或暫時 0.0.0.0/0 且設定6 hours、1 day 或 1 wks刪除此連線允許）
- 取得 connection string → 存入 Secret Manager MONGO_URI
- 驗證：本地用 Atlas URI 跑一次 task01，確認寫入成功。測試範例：`poetry run python -c "import pymongo,os; client = pymongo.MongoClient('放入altas_uri_string');print(client.list_database_names())"`
```

### Step 2：Secret Manager 設定

```
# secrets 項目以 .env.example 要求為主
- MONGO_ALTAS_URI    # MongoDB Atlas connection uri string
- MONGO_DB_NAME
- GITHUB_TOKEN
- GITHUB_USERNAME
- GITHUB_MAIL
- CCCLUB_USERNAME
- CCCLUB_PASSWORD
- LEETCODE_USERNAME
- LEETCODE_ACCOUNT
- LEETCODE_PASSWORD
- CSRF_TOKEN
- LEETCODE_SESSION
- GOOGLE_SHEET_KEY
```

### Step 3：修改 ETL 腳本、streamlit 腳本讀取環境變數的方式
**刪除 load_dotenv()**:
地端執行時，腳本用 `import python-dotenv` 讀 `.env`，遷移到雲端時，可不需要 import。
```python
# 範例:
# 原本（Phase I）
from dotenv import load_dotenv
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

# 改成（Phase II）
import os
MONGO_URI = os.getenv("MONGO_ALTAL_URI")
```

**讀取JSON KEY FILE改成直接解析JSON string**:
上傳到 Secret Managers 的 JSON key file，會由 GCP 自動解析成 JSON-like 字串，因此原本在地端執行的腳本，在雲端上執行後，不再需調用讀取 file 的相關函式，直接 json-string 轉 python-dict，然後依照業務需求做字典取值即可。


### Step 4: 將 Task01 掃描的 Obsidian Vault 從本地端資料夾修改為 GCS object path

新增 scan_vault_gs() 函式，掃描 GCS bucket `personal-vaults`，部署至 cloun run 時，task01的 main.py 當調用 scan_vault_gs()，而不是地端開發時的 scan_vault() 函式。

```python
# 原本（Phase I）
def scan_vault(vault_path: str) -> list[dict]:
    # 中間省略....
    vault = Path(vault_path)
    all_md_files = vault.rglob("*.md")
    md_files = []
    for f in all_md_files:
        if f.parent.name[0:2] not in FOLDER_TYPE_MAP.keys():
            continue
        md_files.append(f)
    # 中間省略....
    post = frontmatter.load(str(md_file))

# 改成（Phase II）
def scan_vault_gs(bucket_name: str = "personal-vaults") -> list[dict]:
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    all_blobs = client.list_blobs(bucket_name)
    md_blobs = []
    for blob in all_blobs:
        if not blob.name.endswith(".md"):
            continue
        folder_prefix = blob.name.split("/")[0][:2]
        if folder_prefix not in FOLDER_TYPE_MAP:
            continue
        md_blobs.append(blob)
    # 中間省略....
    content_str = blob.download_as_text(encoding="utf-8")
    post = frontmatter.loads(content_str)
```

### Step 5：為每個 task 撰寫 Dockerfile

> 關鍵：Dockerfile 不能 COPY .env 避免資料外洩。\

> 關鍵：為了減輕 image 大小，從poetry.lock、pyproject.toml export requirements.txt，放於根目錄，只將 requirements.txt 包進 image。每個 task 獨立一個 Dockerfile，放在 /docker/資料夾內：
```text
    專案根目錄/
    ├── requirements.txt    # 所有 dockerfile 共用
    ├── .dockerignore       # 忽略部分快取檔案或防止誤包機密檔案。
    ├── docker/
    │   ├── Dockerfile.task01
    │   ├── Dockerfile.task02
    │   ├── Dockerfile.task03
    │   ├── Dockerfile.task05
    │   └── Dockerfile.dashboard_ui
    ├── task01_obsidian_etl/
    ├── task02_github_restapi_etl/
    │
    ......
    ...
    ..
```
**先地端測試一次映像檔能被順利建立**：
在地端開啟Docker Desktop，然後build image後，用docker run試啟動，但因為沒有包 .env，所以通常會在啟動後觸發OSError，執行到此即可:

```bash
    # 1. 建立映像檔指令
    docker build --platform=linux/amd64 -f <path-to-dockerfile> -t <image_name>:<tag> .
    # 這個 flag 很重要，因為本機是 Apple Silicon（arm64），Cloud Run 執行環境是通常是 linux/amd64。

    # 2. 啟動指令
    docker run -it -d --name <container_name> -- <image_name>:<tag>
```

### Step 6：GitHub Actions Workflow 撰寫

在 `.github/workflows/` 建立各 task 的 workflow.yml，觸發條件為 push to `develop`，相關 path 的檔案有變動才觸發 workflow，以 `.github/workflows/deploy-task01.yml` 結構為例：

```yaml
on:
  push:
    branches: [develop]
    paths:
      - task01_obsidian_etl/**
      - docker/Dockerfile.task01

jobs:
  build-and-push:
    steps:
      - Checkout
      - Authenticate to GCP（使用 GitHub Secret 存放 GCP SA）
      - Build Docker image
      - Push to Artifact Registry
```

> 讓 GitHub Actions 的 GCP 認證走 **Workload Identity Federation**，避免在 GitHub Secrets 存 SA JSON key，整體步驟較多，紀錄在[後方](#建立-workload-identity-provider)

> image 命名原則:
```markdown
    asia-east1-docker.pkg.dev/<GCP project ID>/<AR_repo_name>/task01_obsidian_etl:latest

    asia-east1-docker.pkg.dev/<GCP project ID>/<AR_repo_name>/task02-github0restapi-etl:latest

    asia-east1-docker.pkg.dev/<GCP project ID>/<AR_repo_name>/task03-leetcode-ccclub-etl:latest

    asia-east1-docker.pkg.dev/<GCP project ID>/<AR_repo_name>/task05-googlesheet-skill-etl:latest

    asia-east1-docker.pkg.dev/<GCP project ID>/<AR_repo_name>/dashboard-ui:latest

```

### Step 7：每個 task 各一個 Cloud Run Job 設定
- 在 GCP Console 建立 Cloud Run Job
- 指定 image：Artifact Registry 的 task01 image
- 掛載 Secret Manager secrets 為環境變數
- 指定 Service Account
- 手動觸發一次，確認執行成功、Atlas 有資料寫入
- 建立 Cloud Scheduler，定期觸發 Job

### Step 8：Cloud Run Service 設定 Streamlit Dashboard
- dashboard_ui/Dockerfile 撰寫
- GitHub Actions 打包 dashboard image → push Artifact Registry
- 建立 Cloud Run Service
    - port: 8080
    - 掛載 MONGO_ALTAS_URI、MONGO_DB_NAME secrets
    - 存取 public
    - min-instances: 0（節省費用）
- 取得公開 URL endpoint，驗證畫面正常

## 注意事項備忘
- csrf + session 有效期約 1~2 週，task03 Job 失敗時需手動到瀏覽器取新 cookie 並更新 Secret Manager。
- Obsidian .md 手動上傳 GCS：`gsutil cp -r ~/path/to/obsidian-vault/ gs://your-bucket/obsidian/`
- task01 在 Cloud Run 中需從 GCS 讀取 .md（不再讀本地路徑），需確認 task01 腳本的路徑來源是否需要修改
- 未來 Branch `Main`，MongoDB Atlas Network Access 正式環境建議改為 GCP Cloud Run 的固定 Egress IP (需開 VPC)

## 建立 Workload Identity provider
- 建立 Pool
    ```bash
        gcloud iam workload-identity-pools create "github-pool" \
        --location="global" \
        --display-name="GitHub Actions Pool" \
        --project=$GCP_PROJECT_ID

        # 輸出範例：
        # Created workload identity pool [github-pool].
    ```

- 建立 Provider（填入 GitHub username 和 repo name）
    ```bash
        gcloud iam workload-identity-pools providers create-oidc "github-provider" \
        --location="global" \
        --workload-identity-pool="github-pool" \
        --display-name="GitHub Provider" \
        --issuer-uri="https://token.actions.githubusercontent.com" \
        --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
        --attribute-condition="assertion.repository=='YOUR_GITHUB_USERNAME/YOUR_REPO_NAME'"
    ```
- 將 SA 綁定到 WIF provider
    ```bash
        export SA_EMAIL="person-skill-dashboard@causal-inquiry-484423-e7.iam.gserviceaccount.com"
        export PROJECT_NUMBER=$(gcloud projects describe causal-inquiry-484423-e7 --format="value(projectNumber)")

        gcloud iam service-accounts add-iam-policy-binding $SA_EMAIL \
        --role="roles/iam.workloadIdentityUser" \
        --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME"
    ```
- 取得 WIF provider的值
    ```bash
        export PROJECT_NUMBER=$(gcloud projects describe causal-inquiry-484423-e7 --format="value(projectNumber)")

        echo "WIF Provider:"
        echo "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider"
    ```
- 將 WIF provider 與 SA 帳號存到 GitHub repo 的 Repository secrets。
