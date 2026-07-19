"""Bronze 層 ETL 入口：每週腳本只做到 Bronze，完全不呼叫 LLM。

執行流程：下載 html → 算 hash → 比對 → 有變動才以 dt= 分區寫 GCS →
upsert to MongoDB onenote_note_metadata（status=bronze_stored）。
Silver enrichment 不在此執行，改由 UI on-demand 觸發（見 task07_silver_service)
Usage:
    poetry run python -m task07_onenote_to_markdown_lazy_loading.main

Required .env keys:
    ONENOTE_CLIENT_ID      Azure App Registration Client ID (public client, Notes.Read scope).
    ONENOTE_GCS_BUCKET     GCS bucket serving as the data lake.
    GCS_USER_CREDENTIALS   (On-premise only) GCS service account JSON.
"""

from dotenv import load_dotenv
from loguru import logger

from task07_common.gcs import _get_client_on_premise

from .e_onenote_download import e_onenote_download

load_dotenv()


def run_task07_bronze_etl() -> None:
    """Bronze 層 ETL 入口：呼叫 e_onenote_download() 下載並記錄新版本數。Silver 由 UI on-demand 觸發。"""
    logger.info("=== Task07 v02 Bronze layer: ETL ===")
    _get_client_on_premise()
    new_versions = e_onenote_download()
    logger.success(f"Bronze layer ETL 完成：{new_versions} 個新版本。Silver 由 UI on-demand 觸發。")


if __name__ == "__main__":
    run_task07_bronze_etl()
