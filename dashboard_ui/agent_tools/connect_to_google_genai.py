"""建立指向 Vertex AI（location=us-central1）的 google-genai client，供 chat 類模型呼叫。

以 service account 憑證初始化 genai.Client；與 query_with_vector_search 的 embedding client（location=us）
分開，因兩者所在 region 不同。

Required .env keys:
    GCP_PROJECT_ID                    Vertex AI project id.
    AGENT_PLATFORM_USER_CREDENTIALS   Vertex AI service account JSON path.
"""

import os

from google import genai
from google.oauth2.service_account import Credentials


def _get_genai_client() -> genai.Client:
    """初始化指向 Vertex AI 的 google-genai client (限定給 location=us-central1，供 chat 模型用)。

    與 query_with_vector_search._get_embed_client 分開，因為該函式只調用在 us 的模型。

    Returns:
        指向 Vertex AI (location=us-central1) 的 google-genai Client 物件。

    Raises:
        EnvironmentError: 缺少 GCP_PROJECT_ID 或 AGENT_PLATFORM_USER_CREDENTIALS 時拋出。
    """
    json_path = os.getenv("AGENT_PLATFORM_USER_CREDENTIALS")
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    credentials = Credentials.from_service_account_file(json_path, scopes=scopes)

    project = os.getenv("GCP_PROJECT_ID")
    location = "us-central1"
    if not project or not credentials:
        raise EnvironmentError(
            "找不到 GCP_PROJECT_ID / AGENT_PLATFORM_USER_CREDENTIALS ，請確認已設定在 .env 或 secret managers 中。"
        )
    return genai.Client(vertexai=True, project=project, location=location, credentials=credentials)
