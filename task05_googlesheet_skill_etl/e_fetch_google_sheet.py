"""task05 Extract：以 service account 建立 Google Sheets client 並讀取指定工作表為 DataFrame。

1. 函式 get_google_sheet_client 以憑證檔路徑或環境變數中的憑證字串授權，回傳 Google Sheets client。
2. 函式 open_spreadsheet_get_worksheet 開啟指定試算表的某張工作表，回傳其內容為 pandas DataFrame。

Required .env keys:
    GOOGLE_SHEET_KEY   Decoded service account JSON string for Google Sheets access.
"""

import pandas as pd
import pygsheets
from loguru import logger
from pygsheets.client import Client


def get_google_sheet_client(
    *, CREDENTIAL_FILE_PATH: str | None = None, CREDENTAIL_JSONS_FROM_ENVAR: str | None = None
) -> Client:
    """以 service account 憑證授權並回傳 Google Sheets client。

    可傳入憑證檔路徑，或傳入存有 decode 後憑證字串的環境變數名稱，兩者擇一。

    Args:
        CREDENTIAL_FILE_PATH: service account JSON KEY 檔的路徑。
        CREDENTAIL_JSONS_FROM_ENVAR: 存有憑證 JSON 字串的環境變數名稱。

    Returns:
        已授權的 pygsheets Client。

    Raises:
        Exception: 兩個參數都未提供時拋出。
    """
    if CREDENTAIL_JSONS_FROM_ENVAR is None and CREDENTIAL_FILE_PATH:
        with open(CREDENTIAL_FILE_PATH, "r") as f:
            service_account_json_str = f.read()  # 將鑰匙轉成字串
        return pygsheets.authorize(service_account_json=service_account_json_str)
    elif CREDENTIAL_FILE_PATH is None and CREDENTAIL_JSONS_FROM_ENVAR:
        return pygsheets.authorize(service_account_env_var=CREDENTAIL_JSONS_FROM_ENVAR)
    else:
        logger.error("Your must pass either CREDENTAIL_JSONS_FROM_ENVAR or CREDENTAIL_KEY_FILE_PATH.")
        raise


def open_spreadsheet_get_worksheet(client: Client, spreadsheet_title: str, worksheet_title: str) -> pd.dataframe:
    """開啟指定 Google 試算表的某張工作表，回傳其內容為 pandas DataFrame。

    Args:
        client: 已授權的 pygsheets Client。
        spreadsheet_title: 試算表名稱。
        worksheet_title: 工作表名稱。

    Returns:
        該工作表內容組成的 pandas DataFrame。
    """
    logger.info(f"Opening spreadsheet '{spreadsheet_title}'...")

    try:
        spdsheets = client.open(spreadsheet_title)
        worksheet = spdsheets.worksheet("title", worksheet_title)
    except pygsheets.SpreadsheetNotFound as e:
        logger.error(f"Failed to fetch the spreadsheet. Error msg: {e}")
        raise
    except pygsheets.WorksheetNotFound as e:
        logger.error(f"Failed to fetch the worksheet '{worksheet_title}'. Error msg: {e}")
        raise
    else:
        df = worksheet.get_as_df(numeric=False)
        logger.success(f"Successfully opened the spreadsheet/worksheet '{spdsheets.title}/{worksheet_title}'")
        return df
