import os
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

from .e_onenote_download import e_onenote_download
from .t_html_to_markdown import t_html_to_markdown
from .l_save_markdown import l_save_markdown

load_dotenv()


def run_task07_onenote_etl():
    # Extract: download OneNote pages as HTML files
    # e_onenote_download()

    # Read pipeline config from env
    export_dir = Path(os.getenv("ONENOTE_OUTPUT_DIR", ""))
    if not export_dir.is_dir():
        raise EnvironmentError("ONENOTE_OUTPUT_DIR is not set or does not exist. "
                               "Please configure it in .env."
                               )

    selected_raw = os.getenv("ONENOTE_SELECTED_NOTEBOOKS", "").strip()
    if not selected_raw:
        candidates = [d.name for d in sorted(export_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]
        if not candidates:
            raise EnvironmentError(f"No subdirectories found in {export_dir}.")
        print("\nDownloaded notebooks in ONENOTE_OUTPUT_DIR:")
        for i, name in enumerate(candidates, 1):
            print(f"  [{i}] {name}")
        raw_input = input(
            "\nEnter the notebooks in which you want to transformed the pages. Enter the name(s), comma-separated (or numbers): ").strip()
        if not raw_input:
            logger.warning("No notebooks selected. Exiting.")
            return
        selected_notebooks = []
        for token in raw_input.split(","):
            token = token.strip()
            if token.isdigit() and 1 <= int(token) <= len(candidates):
                selected_notebooks.append(candidates[int(token) - 1])
            elif token:
                selected_notebooks.append(token)
    else:
        selected_notebooks = [s.strip() for s in selected_raw.split(",") if s.strip()]

    logger.info(f"Transform: processing {len(selected_notebooks)} notebook(s) from {export_dir}")

    # Transform: parse HTML → build markdown content + frontmatter
    pages = t_html_to_markdown(selected_notebooks, export_dir)

    # Load: write .md files to disk and update metadata CSV
    l_save_markdown(pages)


if __name__ == "__main__":
    run_task07_onenote_etl()
