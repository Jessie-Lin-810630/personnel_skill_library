"""GCS data lake 讀寫工具：單一固定 bucket、以資料層＋user_id 組出三層 blob 路徑。

工具預設固定使用 bucket "onenote-vaults"，但可由環境變數 ONENOTE_GCS_BUCKET 覆寫。

預計透過工具可處理得到以下三層 blob 路徑:
    1. Bronze layer
        - raw-notes/<user_id>/<notebook>/<section>/dt=.../page.html
        - raw-notes/<user_id>/<notebook>/<section>/dt=.../_images/x.png
    2. Silver layer
        - processed-notes/<user_id>/<notebook>/<section>/dt=<bronze的dt>/page.md
    3. Gold layer
        - archived-notes/<user_id>/<notebook>/<section>/dt=<bronze的dt>/page.md
        - archived-notes/<user_id>/<notebook>/<section>/dt=<bronze的dt>/_images/x.png
"""

import os
from pathlib import PurePosixPath

from google.cloud import storage

_client: storage.Client | None = None

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
}


def _get_client() -> storage.Client:
    """取得 GCS client，首次呼叫才建立，之後重複使用同一個。

    憑證由應用程式預設憑證供給，適用於 Cloud Run 這類有 runtime service account 的環境。

    Returns:
        已建立的 google-cloud-storage Client 物件。
    """
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


def get_client_on_premise() -> storage.Client:
    """在地端取得 GCS client，改以 service account 金鑰檔建立憑證。

    首次呼叫才建立，之後重複使用同一個。

    Note:
        這支函式與 _get_client 共用同一個模組層變數，因此地端要在所有 GCS 操作之前先呼叫它，
        否則會先被 _get_client 以應用程式預設憑證建立好，之後再呼叫也不會改用金鑰檔。

    Returns:
        以 GCS_USER_CREDENTIALS 指定的金鑰檔建立的 Client 物件。

    Raises:
        TypeError: 環境變數 GCS_USER_CREDENTIALS 未設定時，由讀取金鑰檔的函式拋出。
        FileNotFoundError: 環境變數指向的金鑰檔不存在時拋出。
    """
    global _client
    if _client is None:
        # 地端執行才需要有 GCS_USER_CREDENTIALS
        from google.oauth2.service_account import Credentials

        json_path = os.getenv("GCS_USER_CREDENTIALS")
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        credentials = Credentials.from_service_account_file(json_path, scopes=scopes)
        _client = storage.Client(credentials=credentials)
    return _client


def get_bucket_name() -> str:
    """取得資料湖的 bucket 名稱。

    Returns:
        環境變數 ONENOTE_GCS_BUCKET 的值，未設定時回預設值 onenote-vaults。
    """
    return os.getenv("ONENOTE_GCS_BUCKET", "onenote-vaults").strip()


def gs_uri(blob_path: str) -> str:
    """把 bucket 相對路徑補上協定與 bucket 名稱，組成完整位址。

    Note:
        metadata 一律存完整位址而非相對路徑，這樣讀取端不需要另外知道 bucket 是哪一個。

    Args:
        blob_path: 不含協定與 bucket 名稱的相對路徑。

    Returns:
        gs 協定開頭的完整物件位址。
    """
    return f"gs://{get_bucket_name()}/{blob_path}"


def _split_uri(uri: str) -> tuple[str, str]:
    """把完整物件位址拆成 bucket 名稱與相對路徑兩段。

    Args:
        uri: gs 協定開頭的完整物件位址。

    Returns:
        bucket 名稱與相對路徑組成的 tuple。
    """
    bucket, _, key = uri[len("gs://") :].partition("/")
    return bucket, key


def raw_note_prefix(user_id: str, notebook: str, section: str, dt: str) -> str:
    """組出 Bronze 層的路徑前綴，html 與圖片都存放在這個前綴底下。

    Args:
        user_id: OneNote 使用者代號。
        notebook: OneNote 筆記本名稱。
        section: OneNote 章節名稱。
        dt: 版本分區字串，值為 Bronze 層下載這份筆記的日期。

    Returns:
        不含協定與 bucket 名稱的相對路徑前綴，
        例如 raw-notes/iamuser/生技製劑筆記本/general-technical/dt=2026-07-01。
    """
    return f"raw-notes/{user_id}/{notebook}/{section}/dt={dt}"


def processed_note_prefix(user_id: str, notebook: str, section: str, dt: str) -> str:
    """組出 Silver 層的路徑前綴，LLM 生成的 md 存放在這個前綴底下。

    Args:
        user_id: OneNote 使用者代號。
        notebook: OneNote 筆記本名稱。
        section: OneNote 章節名稱。
        dt: 版本分區字串，值沿用 Bronze 層下載這份筆記的日期。

    Returns:
        不含協定與 bucket 名稱的相對路徑前綴，
        例如 processed-notes/iamuser/生技筆記本/general-technical/dt=2026-07-01。
    """
    return f"processed-notes/{user_id}/{notebook}/{section}/dt={dt}"


def archived_note_prefix(user_id: str, notebook: str, section: str, dt: str) -> str:
    """組出 Gold 層的路徑前綴，人工核可後的 md 與圖片存放在這個前綴底下。

    Args:
        user_id: OneNote 使用者代號。
        notebook: OneNote 筆記本名稱。
        section: OneNote 章節名稱。
        dt: 版本分區字串，值沿用 Bronze 層下載這份筆記的日期。

    Returns:
        不含協定與 bucket 名稱的相對路徑前綴，
        例如 archived-notes/iamuser/生技筆記本/general-technical/dt=2026-07-01。
    """
    return f"archived-notes/{user_id}/{notebook}/{section}/dt={dt}"


def _content_type(blob_path: str) -> str | None:
    """依副檔名查出上傳時要標註的 Content-Type。

    Args:
        blob_path: 物件路徑，只取其副檔名參與判斷。

    Returns:
        對應的 Content-Type 字串；副檔名不在對照表內時回 None，此時上傳會交由 GCS 自行判定。
    """
    ext = PurePosixPath(blob_path).suffix.lower()
    return _CONTENT_TYPES.get(ext)


def upload_text(blob_path: str, text: str, bucket_name: str | None = None) -> str | None:
    """把字串上傳成 GCS 物件，適用於 html 與 md。

    Args:
        blob_path: 不含協定與 bucket 名稱的相對路徑。
        text: 要上傳的字串內容。
        bucket_name: 目的 bucket 名稱，省略時改讀環境變數 ONENOTE_GCS_BUCKET。

    Returns:
        上傳後該物件的 md5；GCS 未回傳雜湊值時為 None。
    """
    if bucket_name is None:
        bucket_name = get_bucket_name()
    blob = _get_client().bucket(bucket_name).blob(blob_path)
    blob.upload_from_string(text, content_type=_content_type(blob_path))
    return blob.md5_hash


def upload_bytes(blob_path: str, data: bytes, bucket_name: str | None = None) -> str | None:
    """把二進位內容上傳成 GCS 物件，適用於圖片。

    Args:
        blob_path: 不含協定與 bucket 名稱的相對路徑。
        data: 要上傳的二進位內容。
        bucket_name: 目的 bucket 名稱，省略時改讀環境變數 ONENOTE_GCS_BUCKET。

    Returns:
        上傳後該物件的 md5；GCS 未回傳雜湊值時為 None。
    """
    if bucket_name is None:
        bucket_name = get_bucket_name()
    blob = _get_client().bucket(bucket_name).blob(blob_path)
    blob.upload_from_string(data, content_type=_content_type(blob_path))
    return blob.md5_hash


def download_text(path: str) -> str:
    """讀取一個 GCS 文字物件，適用於 html 與 md。

    傳入完整位址時取其中的 bucket 名稱，傳入相對路徑時改讀環境變數 ONENOTE_GCS_BUCKET。

    Args:
        path: 完整物件位址或不含 bucket 名稱的相對路徑，兩種寫法都接受。

    Returns:
        以 UTF-8 解碼後的文字內容。
    """
    if path.startswith("gs://"):
        bucket_name, key = _split_uri(path)
    else:
        bucket_name, key = get_bucket_name(), path
    blob = _get_client().bucket(bucket_name).blob(key)
    return blob.download_as_text(encoding="utf-8")


def download_bytes(path: str) -> bytes:
    """讀取一個 GCS 二進位物件，適用於圖片。

    傳入完整位址時取其中的 bucket 名稱，傳入相對路徑時改讀環境變數 ONENOTE_GCS_BUCKET。

    Args:
        path: 完整物件位址或不含 bucket 名稱的相對路徑，兩種寫法都接受。

    Returns:
        該物件的二進位內容。
    """
    if path.startswith("gs://"):
        bucket_name, key = _split_uri(path)
    else:
        bucket_name, key = get_bucket_name(), path
    blob = _get_client().bucket(bucket_name).blob(key)
    return blob.download_as_bytes()


def copy_blob(src_uri: str, dst_blob: str) -> str | None:
    """把來源物件複製到預設 bucket 底下的指定路徑。

    複製由 GCS 在伺服器端完成，內容不經過本機，因此不產生下載與上傳流量；跨 bucket 的來源同樣支援。

    Args:
        src_uri: 來源物件的完整位址或不含 bucket 名稱的相對路徑，兩種寫法都接受。
        dst_blob: 目的物件的相對路徑，bucket 一律取自環境變數 ONENOTE_GCS_BUCKET。

    Returns:
        複製完成後目的物件的 md5；GCS 未回傳雜湊值時為 None。
    """
    if src_uri.startswith("gs://"):
        src_bucket_name, src_key = _split_uri(src_uri)
    else:
        src_bucket_name, src_key = get_bucket_name(), src_uri
    client = _get_client()
    src_bucket = client.bucket(src_bucket_name)
    src = src_bucket.blob(src_key)
    dst_bucket = client.bucket(get_bucket_name())
    copied = src_bucket.copy_blob(src, dst_bucket, dst_blob)
    return copied.md5_hash
