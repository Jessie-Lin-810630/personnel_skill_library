"""Gold 層 Archive 端點：把 task07 lazy_loading 的核可後歸檔端點化。

執行流程：
    1. 接收 POST /archive 的 page_id、dt 與 action，先驗證 X-User-Token 取得使用者身分與角色。
    2. Action 為 "approved" 時呼叫 archive_note，其內部先複製 md 與 png 到 archived-notes、
       upsert Collection onenote_note_metadata，最後回讀 archived md 萃取 frontmatter 後再次
       upsert onenote_note_metadata。
    3. Action 為 "rejected" 時呼叫 reject_note，其內部先 upsert Collection onenote_note_metadata，
       再讀 rejected md 萃取 md_frontmatter 後再次 upsert onenote_note_metadata。
    4. 寫入 reviewed_by_role 的角色一律取自 token，不採用 request body 帶來的值。
    5. Streamlit 審查頁維持唯讀，只透過此端點觸發。

Usage:
    poetry run python -m task07_gold_service.app

Required .env keys:
    MONGO_ALTAS_URI     MongoDB Atlas connection URI.
    MONGO_DB_NAME       MongoDB database name.
    USER_ALLOWLIST      JSON object mapping user email to role name.
    TOKEN_ISSUER_SA     Email of the dashboard runtime service account that signs the token.

Optional .env keys:
    ONENOTE_GCS_BUCKET  GCS data lake bucket (defaults to onenote-vaults).
"""

from typing import Annotated, Literal

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel

from task07_common.auth import UserIdentity, register_validation_error_handler, verify_user
from task07_gold_service.l_archive_note import archive_note, reject_note

load_dotenv()

app = FastAPI(title="task07 Gold archive service")
register_validation_error_handler(app)


class ArchiveRequest(BaseModel):
    """POST /archive 的請求欄位。

    Note:
        審核者角色不是請求欄位。呼叫端若在 body 帶 role，Pydantic 會直接忽略，
        端點一律採用 X-User-Token 驗證後推導的角色。

    Attributes:
        page_id: OneNote 頁面代號。
        dt: 版本分區日期。
        action: 審核結果，只接受 approved 與 rejected。
    """

    page_id: str
    dt: str
    action: Literal["approved", "rejected"]


@app.post("/archive")
def archive(body: ArchiveRequest, user: Annotated[UserIdentity, Depends(verify_user)]) -> JSONResponse:
    """接收頁面代號、版本分區與審核結果，依審核結果執行歸檔或退件。

    request body 欄位由 ArchiveRequest 驗證；user 身分由 verify_user 驗證，兩者都通過才分派給
    Gold 層的歸檔或退件函式。

    Note:
        歸檔比退件多兩種失敗狀態碼：已有較新版本歸檔時回 409，
        該版本尚未生成 md 或複製失敗這類業務錯誤回 422，兩者都不算傳輸失敗。

        欄位不合法回 400 而非 FastAPI 預設的 422，這點已由 register_validation_error_handler 改寫，
        改寫結果讓 422 維持只代表業務錯誤。
        身分驗證未通過則由 verity_user 函式拋出 401、403 或 503，並在此函式內部執行前拋出。

    Args:
        body: 通過驗證的請求欄位。
        user: 通過驗證的 user 身分，由 verify_user 注入。

    Returns:
        JSONResponse。當查無版本回 404；當歸檔遇較新版本回 409；當歸檔的其他業務錯誤回 422；
        當未預期例外回 500；當處理成功則回 200。

    Raises:
        HTTPException: 由 verify_user 拋出，缺 token 或驗簽失敗回 401、不在允許清單回 403、
            取不到驗簽金鑰回 503。
    """
    # ── rejected：呼叫 Gold 層 reject_note ─────────────────────
    if body.action == "rejected":
        try:
            result = reject_note(page_id=body.page_id, dt=body.dt, role=user.role)
        except Exception as e:
            logger.exception(f"[gold] reject 未預期失敗: page_id={body.page_id}, dt={body.dt}")
            return JSONResponse(status_code=500, content={"error": f"[gold:reject] {e}"})
        if result.get("status") == "not_found":
            return JSONResponse(status_code=404, content=result)
        logger.info(f"[gold] rejected: page_id={body.page_id}, dt={body.dt}, by={user.email}({user.role})")
        return JSONResponse(status_code=200, content=result)

    # ── approved：呼叫 Gold 層 archive note 做歸檔 ──────────────
    try:
        result = archive_note(page_id=body.page_id, dt=body.dt, role=user.role)
    except Exception as e:
        logger.exception(f"[gold] archive 未預期失敗: page_id={body.page_id}, dt={body.dt}")
        return JSONResponse(status_code=500, content={"error": f"[gold] {e}"})

    status_value = result.get("status")
    if status_value == "not_found":
        return JSONResponse(status_code=404, content=result)
    if status_value == "archived_conflict":
        return JSONResponse(status_code=409, content=result)
    if status_value != "archived":  # md 未生成 / 複製失敗等業務錯誤
        return JSONResponse(status_code=422, content=result)

    logger.info(f"[gold] archived: page_id={body.page_id}, dt={body.dt}, by={user.email}({user.role})")
    return JSONResponse(status_code=200, content=result)


if __name__ == "__main__":
    # localhost:8003（與 silver_service 8002 錯開）
    uvicorn.run(app, host="127.0.0.1", port=8003)
