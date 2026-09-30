"""讓前端自行簽發一張包含使用者身分資訊的 token，並包成短效 JWT，再傳給 Silver 與 Gold endpoint 驗證。

執行流程：
1. 函式 mint_user_token 負責取出登入成功的使用者之 email，組出含 iss、aud、exp 的 payload。
2. 呼叫 GCP IAM Credentials 的 signJwt，請 Google 用 dashboard runtime service account 的私鑰做 signature，
   私鑰始終由 Google 保管，本服務拿不到也不需要保存。
3. 回傳簽好的 JWT 字串給呼叫 mint_user_token 的前端程式
4. 由前端負責把它放進 header X-User-Token，然後送出給後端。(不在此檔案範疇實作)
5. 每次呼叫後端前都要重新調用 mint_user_token 新簽一張短效 JWT，不存入快取。(不在此檔案範疇實作)

Note:
    JWT 的 signature 需要呼叫端的 service account 對「目標 service account」
    具備 roles/iam.serviceAccountTokenCreator。
    本專案兩者是同一個 dashboard runtime service account，等於自己授權給自己。

Required .env keys:
    TOKEN_ISSUER_SA               Email of the dashboard runtime service account that signs the token.

Optional .env keys:
    DASHBOARD_SIGNER_CREDENTIALS  (On-premise only) Path to the dashboard service account JSON key.
                                  Set it locally, otherwise google.auth.default() falls back to
                                  GOOGLE_APPLICATION_CREDENTIALS, which points at the read-only
                                  gcs-viewer key and has no serviceAccountTokenCreator permission.
                                  Leave it unset on Cloud Run so the runtime service account is used.
"""

import json
import os
from datetime import UTC, datetime, timedelta

import google.auth
import google.auth.transport.requests
from loguru import logger

# 與 task07_common/auth.py 的 USER_TOKEN_AUDIENCE 常數值相同。
# 由於 dashboard 跟 task07 後端服務是獨立部署，所以此常數兩邊各寫一份，但必須相同。
# 單元測試 tests/test_user_token_audience_matches.py 負責斷言兩邊值一致，避免部署失敗。
USER_TOKEN_AUDIENCE = "task07-user"

# token 有效期。需要夠短以減少外洩風險，需夠長以容納一次 LLM 生成的等待時間。
TOKEN_TTL_SECONDS = 300

_SIGN_JWT_URL = "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{sa}:signJwt"

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def _get_signer_credentials():
    """取得用來呼叫 signJwt 的 credentials，注意本專案的地端與雲端環境的 credentials 來源不同。

    Note:
        地端環境，請將 SA JSON KEY 指向環境變數 DASHBOARD_SIGNER_CREDENTIALS，
        雲端環境無需指向任何環境變數，用 Google ADC 機制預設的 GOOGLE_APPLICATION_CREDENTIALS，
        此外，SA 身分應該具備 Service Account Token Creator 角色。

    Returns:
        可呼叫 IAM Credentials 的憑證物件。

    Raises:
        FileNotFoundError: DASHBOARD_SIGNER_CREDENTIALS 指向的金鑰檔不存在時拋出。
    """
    json_path = os.getenv("DASHBOARD_SIGNER_CREDENTIALS", "").strip()
    if json_path:
        from google.oauth2.service_account import Credentials

        logger.debug(f"[user_token] 以金鑰檔簽發：{json_path}")
        return Credentials.from_service_account_file(json_path, scopes=[_CLOUD_PLATFORM_SCOPE])

    credentials, _ = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
    return credentials


def mint_user_token(email: str) -> str:
    """為登入成功的使用者簽一張短效 token，token 只夾帶使用者的 email。

    Note:
        這支每次呼叫都會對 IAM Credentials 發一次請求，不做快取。以審查頁的操作頻率
        （使用者按一次按鈕才呼叫一次）而言可以接受，換來的是有效期可以壓到五分鐘。

    Args:
        email: 經 Google 驗證的使用者 email，會寫進 token 的 email claim。

    Returns:
        簽好的 JWT 字串，供呼叫端放進 header X-User-Token。

    Raises:
        RuntimeError: 未設定 TOKEN_ISSUER_SA，或 signJwt 未回 200，或回 200 但缺少 signedJwt 欄位。
        FileNotFoundError: 地端設了 DASHBOARD_SIGNER_CREDENTIALS 但檔案不存在時，由讀取金鑰檔的函式拋出。
    """
    issuer = os.getenv("TOKEN_ISSUER_SA", "").strip()
    if not issuer:
        raise RuntimeError("TOKEN_ISSUER_SA 未設定，無法簽發 X-User-Token")

    now = datetime.now(UTC)
    payload = {
        "iss": issuer,  # 簽發者 (dashboard)
        "aud": USER_TOKEN_AUDIENCE,  # 指名簽給後端
        "email": email,  # 登入成功的使用者的 email；角色不簽進來，由端點自己查 USER_ALLOWLIST 推導
        "iat": int(now.timestamp()),  # 簽發時間戳
        "exp": int((now + timedelta(seconds=TOKEN_TTL_SECONDS)).timestamp()),  # 五分鐘後此 token 過期
    }

    # 請 Google 代為使用 issuer 的 SA 私鑰簽發，避免 issuer 要自行管理 SA 私鑰
    session = google.auth.transport.requests.AuthorizedSession(_get_signer_credentials())
    resp = session.post(
        _SIGN_JWT_URL.format(sa=issuer),
        json={"payload": json.dumps(payload)},
        timeout=10,
    )

    if resp.status_code != 200:
        logger.error(f"[user_token] signJwt 未回 200：{resp.status_code} {resp.text}")
        raise RuntimeError(f"簽發 X-User-Token 失敗，signJwt 回 {resp.status_code}")

    signed_jwt = resp.json().get("signedJwt")
    if not signed_jwt:
        logger.error(f"[user_token] signJwt 回 200 但沒有 signedJwt 欄位：{resp.text}")
        raise RuntimeError("簽發 X-User-Token 失敗，signJwt 回應缺少 signedJwt 欄位")
    return signed_jwt
