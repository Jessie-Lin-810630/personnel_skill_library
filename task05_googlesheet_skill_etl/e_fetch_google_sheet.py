"""task05 Extract：以 service account 建立 Google Sheets client 並讀取指定工作表為 DataFrame。

1. 函式 get_google_sheet_client 以憑證檔路徑或環境變數中的憑證字串授權，回傳 Google Sheets client。
2. 函式 open_spreadsheet_get_worksheet 開啟指定試算表的某張工作表，回傳其內容為 pandas DataFrame。

Required .env keys:
    GOOGLE_SHEET_KEY   Service account credential for Google Sheets access; a path to the
                       JSON key file when running locally, or the decoded JSON string on GCP.
"""

import pandas as pd
import pygsheets
from loguru import logger
from pygsheets.client import Client


def get_google_sheet_client(
    *, CREDENTIAL_FILE_PATH: str | None = None, CREDENTAIL_JSONS_FROM_ENVAR: str | None = None
) -> Client:
    """以 service account 憑證授權並回傳 Google Sheets client。

    傳入憑證檔路徑時讀檔取得憑證內容，傳入環境變數名稱時改由該變數取得，兩者只能擇一。

    Note:
        - 兩種取得憑證的方式對應兩種執行環境：地端有金鑰檔可讀，雲端則把憑證內容放在環境變數裡。
        - 兩個參數同時給或同時不給都會拋錯，因為那代表呼叫端沒有想清楚要用哪一種，
          沉默地挑一個會讓憑證來源難以追查。

    Args:
        CREDENTIAL_FILE_PATH: service account JSON 金鑰檔的路徑。
        CREDENTAIL_JSONS_FROM_ENVAR: 存有憑證 JSON 字串的環境變數名稱。

    Returns:
        已授權的 pygsheets Client 物件。

    Raises:
        ValueError: 兩個參數同時給或同時未給時拋出。
        OSError: 憑證檔路徑不存在或無法讀取時拋出。
    """
    if CREDENTAIL_JSONS_FROM_ENVAR is None and CREDENTIAL_FILE_PATH:
        with open(CREDENTIAL_FILE_PATH, "r") as f:
            service_account_json_str = f.read()  # 將鑰匙轉成字串
        return pygsheets.authorize(service_account_json=service_account_json_str)
    elif CREDENTIAL_FILE_PATH is None and CREDENTAIL_JSONS_FROM_ENVAR:
        return pygsheets.authorize(service_account_env_var=CREDENTAIL_JSONS_FROM_ENVAR)
    else:
        # 兩參數皆缺或皆給時的參數驗證錯誤，拋明確的 ValueError
        # （此處 bare raise 無 active exception，會變成看不懂的 RuntimeError）
        msg = "You must pass exactly one of CREDENTIAL_FILE_PATH or CREDENTAIL_JSONS_FROM_ENVAR."
        logger.error(msg)
        raise ValueError(msg)


def open_spreadsheet_get_worksheet(client: Client, spreadsheet_title: str, worksheet_title: str) -> pd.DataFrame:
    """開啟指定 Google 試算表的某張工作表，回傳其內容為 pandas DataFrame。

    依名稱開啟試算表與其中一張工作表，再把整張工作表讀成 DataFrame。

    Note:
        - 讀取時不讓 pygsheets 自動判斷數值型別，所有儲存格一律當字串讀進來。
          因為評分欄位填的是 Y 或空白，交給後續 Transform 自行判讀，
          自動轉型反而會讓空白與 0 混淆。
        - 試算表與工作表都以名稱定位，兩者改名都會讓這裡找不到。

    Args:
        client: 已授權的 pygsheets Client 物件。
        spreadsheet_title: 試算表名稱。
        worksheet_title: 工作表名稱。

    Returns:
        該工作表內容組成的 pandas DataFrame，所有欄位皆為字串。

    Raises:
        pygsheets.SpreadsheetNotFound: 找不到指定名稱的試算表時拋出。
        pygsheets.WorksheetNotFound: 找不到指定名稱的工作表時拋出。
    """
    logger.info(f"Opening spreadsheet '{spreadsheet_title}'...")

    try:
        spdsheets = client.open(spreadsheet_title)
        worksheet = spdsheets.worksheet("title", worksheet_title)
    except pygsheets.SpreadsheetNotFound as e:
        logger.error(f"Failed to fetch the spreadsheet '{spreadsheet_title}'. Error msg: {e}")
        raise
    except pygsheets.WorksheetNotFound as e:
        logger.error(f"Failed to fetch the worksheet '{worksheet_title}'. Error msg: {e}")
        raise
    else:
        df = worksheet.get_as_df(numeric=False)
        logger.success(f"Successfully opened the spreadsheet/worksheet '{spdsheets.title}/{worksheet_title}'")
        return df
