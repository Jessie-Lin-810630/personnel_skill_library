"""Bronze 層 ETL 入口：每週腳本只做到 Bronze，完全不呼叫 LLM。

執行流程：下載 html → 算 hash → 比對 → 有變動才以 dt= 分區寫 GCS →
upsert C3（status=bronze_stored）。
Silver enrichment 不在此執行，改由 UI on-demand 觸發（見 t_html_to_markdown.enrich_page）。

Usage:
    poetry run python -m task07_onenote_to_markdown_lazy_loading.main
"""

from dotenv import load_dotenv
from loguru import logger

from .e_onenote_download import e_onenote_download

load_dotenv()


def run_task07_bronze_etl() -> None:
    """Bronze 層 ETL 入口：呼叫 e_onenote_download() 下載並記錄新版本數。Silver 由 UI on-demand 觸發。"""
    logger.info("=== Task07 v02 Bronze layer: ETL ===")
    new_versions = e_onenote_download()
    logger.success(f"Bronze layer ETL 完成：{new_versions} 個新版本。Silver 由 UI on-demand 觸發。")


if __name__ == "__main__":
    run_task07_bronze_etl()
