"""驗證使用者身分：以 dashboard 簽發的短效 JWT 判斷是誰對 Silver 或 Gold 下指令，此模組由兩個服務共用。

執行流程：
1. 主函式 verify_user 作為 FastAPI dependency，從 header X-User-Token 取出 JWT。
2. 以 dashboard runtime service account 的公開金鑰驗簽取得的 JWT，並檢查 payload 中的 issuer、audience 與到期時間。
3. JWT 驗簽通過後取出 email (也就是誰下指令的)，對照環境變數 USER_ALLOWLIST 推導出這個人的角色層級，回傳 UserIdentity。
4. 若缺 token、驗簽失敗或已過期一律回 401；不在 USER_ALLOWLIST 內或在其中被列為 Guest 回 403；
   連不上 Google 的公鑰端點則回 503，與 token 本身有問題分開。
5. 另外做一個函式 register_validation_error_handler 把 FastAPI 預設的 422 驗證失敗改回 400，
   讓 422 保留給端點既有的業務錯誤。

Required .env keys:
    USER_ALLOWLIST      JSON object mapping user email to role name.
    TOKEN_ISSUER_SA   Email of the dashboard runtime service account that signs the token.
"""

import json
import os
from typing import Annotated, NamedTuple

import jwt
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger

# dashboard 簽發 token 時要寫進 audience，這個值在簽發端和驗證端必須一致，值本身沒有對外意義
USER_TOKEN_AUDIENCE = "task07-user"

# 訪客角色名稱，與 dashboard_ui/utils/auth_gate.py 的 GUEST_ROLE 同值。
# dashboard 不 import task07_* 套件，所以兩邊各自宣告一份，改動時要一起改
GUEST_ROLE = "Guest"

# Google 為每個 service account 公開的 JWK 端點，用來取公鑰。公鑰可用於驗簽 JWT
_JWK_URL_TEMPLATE = "https://www.googleapis.com/service_accounts/v1/jwk/{service_account_email}"

_jwk_client: jwt.PyJWKClient | None = None


class UserIdentity(NamedTuple):
    """通過驗證的使用者之身分。

    Attributes:
        email: 經 Google 驗證、並由 dashboard 簽進 token 的使用者 email。
        role: 由 USER_ALLOWLIST 對照出來的角色名稱。
    """

    email: str
    role: str


def _load_allowlist() -> dict[str, str]:
    """讀取並解析 USER_ALLOWLIST，取得 email 對應角色的表。

    Returns:
        email 為鍵、角色名稱為值的 dict。環境變數 USER_ALLOWLIST 未設定或為空字串時回傳空 dict。

    Raises:
        RuntimeError: USER_ALLOWLIST 不是合法 JSON，或解析結果不是 object。
    """
    raw = os.getenv("USER_ALLOWLIST", "").strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"USER_ALLOWLIST 不是合法 JSON：{e}") from e

    if not isinstance(parsed, dict):
        raise RuntimeError(f"USER_ALLOWLIST 必須是 JSON object，實際為 {type(parsed).__name__}")

    return parsed


def _get_jwk_client() -> jwt.PyJWKClient:
    """取得驗簽金鑰的 client，首次呼叫才建立，之後重複使用同一個。

    Note:
        client 內部會快取取回的金鑰，因此不需要每個請求都重新抓一次 Google 的端點。

    Returns:
        指向簽發者 service account 的 PyJWKClient 物件。

    Raises:
        RuntimeError: 未設定 TOKEN_ISSUER_SA，無從得知該抓誰的金鑰。
    """
    global _jwk_client
    if _jwk_client is None:
        issuer = os.getenv("TOKEN_ISSUER_SA", "").strip()
        if not issuer:
            raise RuntimeError("TOKEN_ISSUER_SA 未設定，無法取得驗簽金鑰")
        _jwk_client = jwt.PyJWKClient(_JWK_URL_TEMPLATE.format(service_account_email=issuer))
    return _jwk_client


def verify_user(
    x_user_token: Annotated[str | None, Header(alias="X-User-Token")] = None,
) -> UserIdentity:
    """驗證 header `X-User-Token` 並推導 User 角色，供端點以 FastAPI dependency 掛載。

    Note:
        驗證未通過時以 HTTPException 中斷，Silver/Gold 端點本體完全不會被執行。

        角色為 Guest 時一併拒絕。Guest 明寫在 USER_ALLOWLIST 裡，查得到角色，
        不會被「不在 USER_ALLOWLIST 內」那一關擋下，需要單獨判斷。

    Args:
        x_user_token: header `X-User-Token` 的值，由 FastAPI 注入，未帶時為 None。

    Returns:
        通過驗證的 UserIdentity，含 email 與角色，角色必為 Guest 以外的審查角色。

    Raises:
        HTTPException: 缺 token、驗簽失敗或已過期回 401；不在 USER_ALLOWLIST 內或角色為 Guest 回 403；
            連不上 Google 的公鑰端點回 503。
    """
    if not x_user_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少 X-User-Token")

    # 從 header 清理出 token
    token = x_user_token.removeprefix("Bearer ").strip()

    try:
        # 去 Google 的公鑰清單找到並取得 dashboard SA 公鑰，找不到會被 PyJWTError 捕捉
        signing_key = _get_jwk_client().get_signing_key_from_jwt(token)

        # 驗簽五小關，任一失敗會被 PyJWTError 捕捉
        claims = jwt.decode(
            token,
            signing_key.key,  # 第一關: 公鑰驗證 token 的簽章是否確實由 signing_key.key 蓋上
            algorithms=["RS256"],  # 第二關: 此專案設定後端服務只接受 RS256 演算法
            audience=USER_TOKEN_AUDIENCE,  # 第三關: token payload 的 aud 是否為 USER_TOKEN_AUDIENCE
            issuer=os.getenv("TOKEN_ISSUER_SA", "").strip(),  # 第四關: token payload 的 iss 是否為 dashboard SA
        )  # 第五關 (不用特別寫): 檢查 token payload 的 exp 是否過期。
    except jwt.PyJWKClientConnectionError as e:
        # 取不到 Google 的公鑰清單，是本服務對外連線的問題，token 本身可能完全正常
        # 因為必須停在這層，故印 traceback
        logger.opt(exception=True).error("[auth] 取不到 dashboard SA 的公鑰清單，暫時無法驗證 X-User-Token")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="暫時無法取得驗簽金鑰，請稍後再試",
        ) from e
    except jwt.PyJWTError as e:
        logger.warning(f"[auth] X-User-Token 驗證失敗：{e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"token 驗證失敗：{e}") from e

    # claim 長相 claims = {"iss": "...", "aud": "...", "email": "xxx@gmail.com", ...}
    email = claims.get("email", "")
    if not email:
        logger.warning("[auth] X-User-Token 通過驗簽但缺少 email claim")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token 缺少 email")

    # 推導角色
    role = _load_allowlist().get(email)
    if role is None:
        logger.warning(f"[auth] {email} 不在 USER_ALLOWLIST 內，拒絕操作")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"{email} 不在 USER_ALLOWLIST 內")

    if role == GUEST_ROLE:
        logger.warning(f"[auth] {email} 的角色為 {GUEST_ROLE}，拒絕操作")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"{GUEST_ROLE} 不得執行此操作")

    return UserIdentity(email=email, role=role)


def register_validation_error_handler(app: FastAPI) -> None:
    """把 FastAPI 預設的請求驗證失敗回應從 422 改為 400。

    Note:
        由於 422 在 Gold 端點已用於設計「該版本文件尚未生成 md 或複製失敗」這類業務錯誤，
        若沿用預設值，呼叫端無法分辨是欄位寫錯還是業務條件不符。

    Args:
        app: 要註冊 handler 的 FastAPI 應用程式物件。

    Returns:
        None: 直接在傳入的 app 上註冊 handler，不回傳值。
    """

    @app.exception_handler(RequestValidationError)
    async def _handle(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # _request 是 FastAPI exception handler 的固定簽章要求，本 handler 用不到
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Bad Request：請求欄位不合法", "detail": exc.errors()},
        )
