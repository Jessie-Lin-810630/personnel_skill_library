"""建立指向 Agent Platform（location=us-central1）的 google-genai client，供 chat 類模型呼叫。

以 service account 憑證初始化 genai.Client；與 query_with_vector_search 的 embedding client（location=us）
分開，因兩者所在 region 不同。

Required .env keys:
    GCP_PROJECT_ID                    Agent Platform project id.
    AGENT_PLATFORM_USER_CREDENTIALS   (On-premise only) Agent Platform service account JSON path.
"""

import os

from google import genai


def get_genai_client() -> genai.Client:
    """初始化指向 Agent Platform 的 google-genai client，供 chat 類模型呼叫。

    這個 client 綁定 us-central1，與 query_with_vector_search 內建立 embedding client 的函式分開，
    因為 embedding 模型只在 us 提供服務，兩者所在 region 不同。
    雲端執行時憑證由 Cloud Run 的 runtime service account 以應用程式預設憑證供給，
    地端則需解除函式內的註解區塊，改以 service account 金鑰檔初始化。

    Returns:
        綁定 us-central1 的 google-genai Client 物件。

    Raises:
        EnvironmentError: 環境變數 GCP_PROJECT_ID 未設定時拋出。
    """
    # # 地端測試跑下面區塊：
    # # 先驗環境變數再建 Credentials，否則 json_path 為 None 會讓 Credentials 先拋 TypeError/FileNotFoundError
    # from google.oauth2.service_account import Credentials
    # json_path = os.getenv("AGENT_PLATFORM_USER_CREDENTIALS")
    # scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    # credentials = Credentials.from_service_account_file(json_path, scopes=scopes)

    # project = os.getenv("GCP_PROJECT_ID")
    # if not project or not credentials:
    #     raise EnvironmentError(
    #         "找不到 GCP_PROJECT_ID / AGENT_PLATFORM_USER_CREDENTIALS，請確認已設定在 .env 或 secret manager。"
    #     )
    # return genai.Client(vertexai=True, project=project, location="us-central1", credentials=credentials)

    # Cloud run 跑下面區塊：
    project = os.getenv("GCP_PROJECT_ID")
    if not project:
        raise EnvironmentError("找不到 GCP_PROJECT_ID，請確認已設定在 secret manager。")
    return genai.Client(vertexai=True, project=project, location="us-central1")
