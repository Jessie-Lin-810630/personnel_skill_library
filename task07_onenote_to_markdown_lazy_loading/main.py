"""Bronze 層 ETL 入口：每週腳本只做到 Bronze，完全不呼叫 LLM。

執行流程：
    1. 下載 OneNote 頁面 html，算出 hash 後與既有版本比對。
    2. 有變動才以 dt= 分區寫入 GCS。
    3. upsert to MongoDB onenote_note_metadata（status=bronze_stored）。

Silver enrichment 不在此執行，改由 UI on-demand 觸發（見 task07_silver_service）。

Usage:
    poetry run python -m task07_onenote_to_markdown_lazy_loading.main

Required .env keys:
    ONENOTE_CLIENT_ID      Azure App Registration Client ID (public client, Notes.Read scope).
    ONENOTE_GCS_BUCKET     GCS bucket serving as the data lake.
    ENVIRONMENT            Deploymeny environment. Either of local, dev or prod.
    GCS_USER_CREDENTIALS   GCS service account JSON.
"""

from dotenv import load_dotenv
from loguru import logger

from task07_common.gcs import get_client_on_premise

from .e_onenote_download import e_onenote_download

load_dotenv()


def run_task07_bronze_etl() -> None:
    """Bronze 層 ETL 入口，建立地端 GCS 連線後執行下載，並記錄本次新增的版本數。

    Note:
        這支入口只做到 Bronze，全程不呼叫 LLM；把 html 重整成 md 改由審查頁 on-demand 觸發 Silver 服務。
        因為授權採互動式裝置流程、需要人工在瀏覽器完成，所以這個 ETL 只在地端執行，不納入雲端部署。

    Returns:
        None: html 與圖片寫進 GCS，版本 metadata 寫進 MongoDB，新版本數只記進 log，不回傳值。
    """
    logger.info("=== Task07 v02 Bronze layer: ETL ===")
    get_client_on_premise()
    new_versions = e_onenote_download()
    logger.success(f"Bronze layer ETL 完成：{new_versions} 個新版本。Silver 由 UI on-demand 觸發。")


if __name__ == "__main__":
    run_task07_bronze_etl()
