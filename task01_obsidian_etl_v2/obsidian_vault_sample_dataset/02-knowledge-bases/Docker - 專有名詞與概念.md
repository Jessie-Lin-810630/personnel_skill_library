

---
tags: [docker, development-environment, virtual-environment, commands, 容器化技術]
date: 2025-12-22
type: knowledge_summary
alias: [basic-of-docker]

---

# 目的
歸納習得的 docker 基礎概念。


# Docker 是什麼
- Docker 是一個用於創建、運行、傳送應用程式的平台工具。一個docker可以將**OS、運行所需環境、第三方函式庫、應用程式、環境變數、配置文件、啟動指令**打包在一起。以確保應用程式在任何環境 (開發、測試、生產) 中都可以**快速開啟運行**。

# Docker 能解決什麼
Docker 解決了傳統軟體管理的痛點，例如：當**環境被搞壞（如忘記密碼）時，可以輕易地刪除並重建容器，無需重裝整個作業系統**；同時，它也能讓開發者在同一台電腦上快速啟動並運行多個使用不同軟體版本的獨立專案環境。
此外，Docker 也能克服**協作者之間的作業系統不同的問題**，因為 Docker 透過封裝一個標準化的環境來解決此問題。所以，團隊可以協議使用同一個基礎映像檔，確保每個人開發時所用的作業系統、Python 版本和相依套件都完全一致，從而消除因本機環境差異導致的「在我的電腦上可以跑」的問題。

# 什麼時候會用到 Docker
 沙盒、前端應用至後端資料庫都可以。

# Docker 這套平台工具的主要元素

## Image 與 Container
- Image 是一個唯讀的檔案，定義了一台虛擬主機（容器）應有的配置，包括其作業系統、預先安裝好的軟體和相關設定。Image 是建立 Container 的藍圖，而我們在 shell 透過指令或是在 Docker Desktop ==**啟動了 Image**== 的時候，就是指==**建立/啟動一個 Container**==，所以 Container 是由 Image 啟動後的一個正在運行的實例 (Instance)，可以被視為一台輕量級的獨立虛擬主機。一個 Image 可以用來創建多個相同的 Containers。
- 比喻：某廠牌型號的速食麵調理包就好比 Image，每次開啟都是一個幾乎一樣口味的一碗麵，每碗麵就相當於 每個 Containers。

## Dockerfile
- 一份純文字檔，描述 Image 的架構，好比速食麵調理包的食譜。
- 透過 Dockerfile ，可以清楚自行建置或是看到別人的 Image 內容物，包含：
	- 此 Dockerfile 要產生的 Image ，應該基於哪個 基底 Image 開始建。
		- 例如：在 Dockerfile中會看到 `FROM...` 這行。
	- container 啟動後的工作區目錄名稱。
		- 例如：`WORKDIR /workspace`
	- 需要更新哪些安裝工具 (aptget)?
		- 例如：`RUN apt-get update -y`
	- 需要複製 (copy) 哪些腳本或文件?
		- 例如：`COPY . /workspace`、`COPY ./src ./src`、`COPY pyproject.toml poetry.lock ./`等。
	- 要從本地哪裡注入哪些環境變數?
		- 例如：`ENV TZ=Asia/Taipei`、`ENV FLASK_APP=app.py`
	- 要監聽哪個 IP 位址、開放容器的哪個端口允許 ingress?
		- 例如： `ENV FLASK_RUN_HOST=0.0.0.0`、`EXPOSE 5000`
	- 啟動後要執行哪個指令?
		- 例如： `CMD ["flask", "run"]`
## 補充 -  image 快取層
- Docker image 在建立的時候是一個 Layer based filesystem
	- RUN = commit 一層
	- Layer immutable
	- Cache 是逐層比對
	- 先裝「不常改」的東西

## 補充- 端口映射 (port mapping)
端口映射是將本機（主機）的一個端口連接到容器內部的一個端口的機制。由於容器本身是個隔離的環境，外部無法直接存取其內部的服務；透過端口映射，可以將容器內運行的服務（如網頁伺服器或資料庫）暴露給主機，讓使用者可以透過主機的 IP 和端口與之互動。

## Docker-compose.yml
- 一份 Dockerfile 只會規定一個容器的 Image，如果需要同時開啟多個容器，且這些容器會有互動，例如：前端網頁跑flask、網頁需要向 postgrel 資料庫索取資料，flask 與 postgrel 會有通訊，此時透過 Docker-compose.yml 就可以輕鬆一口氣啟動多個容器，同時規定容器之間的服務關係。
- Docker-compose.yml 不代表就一定不使用 Dockerfile，我們仍然可以用 Dockerfile 規定其中一個容器的 image，而在 docker-compose.yml 引用 Dockrefile 的路徑，Docker 根據 docker-compose.yml 啟動多個容器的時候會一併掃視 Dockerfile 建立 image 後啟動容器。當然，Docker-compose.yml 也可以指定現成的 Image。


## DockerHub
- Docker Hub 是一個公開的 Registry (平台)，用於存放與分享大量的 Docker Image Repositories (倉庫)。
- 存放 image 的就叫做 repository，存放 repository 的地方叫做平台 registry。我們可以透過在 Docker Hub 上搜尋關鍵字（如 python 或 mysql），進入官方 repository 或其他開發社群的 repository，然後再從內找到他們預打包好的 Image，並使用 `docker pull` 指令將 Image 下載到本地，快速建立所需的開發環境。

### Artifact Registry
- GCP 生態圈自己的 DockerHub，見[[20260125 GCP監控與維運服務 - Artifact Registry]]
