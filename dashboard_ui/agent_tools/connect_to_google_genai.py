from google import genai
from google.oauth2.service_account import Credentials
import os


def _get_genai_client() -> genai.Client:
    """
        初始化 google-genai client。
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
    return genai.Client(vertexai=True,
                        project=project,
                        location=location,
                        credentials=credentials)
