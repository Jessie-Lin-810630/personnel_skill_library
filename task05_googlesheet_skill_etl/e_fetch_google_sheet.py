import pygsheets
from pygsheets.client import Client
import pandas as pd
import os
from loguru import logger


def get_google_sheet_client(CREDENTIAL_FILE_PATH: str) -> Client:
    """Get Google Sheets client via service account JSON KEY file."""
    with open(CREDENTIAL_FILE_PATH, "r") as f:
        service_account_json_str = f.read()  # 將鑰匙轉成字串
    return pygsheets.authorize(service_account_json=service_account_json_str)


def open_spreadsheet_get_worksheet(client: Client,
                                   spreadsheet_title: str,
                                   worksheet_title: str) -> pd.dataframe:
    """
    Access to Google spreadsheet and open one of worksheets 
    in the spreadsheet as a dataframe.
    """
    logger.info(f"Opening spreadsheet '{spreadsheet_title}'...")

    try:
        spdsheets = client.open(spreadsheet_title)
        worksheet = spdsheets.worksheet("title", worksheet_title)
    except pygsheets.SpreadsheetNotFound as e:
        logger.error(f"Failed to fetch the spreadsheet. Error msg: {e}")
        raise
    except pygsheets.WorksheetNotFound as e:
        logger.error(f"Failed to fetch the worksheet '{worksheet_title}'")
        raise
    else:
        df = worksheet.get_as_df(numeric=False)
        logger.success(
            f"Successfully opened the spreadsheet/worksheet '{spdsheets.title}/{worksheet_title}'")
        return df
