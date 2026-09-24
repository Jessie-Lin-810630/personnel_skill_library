"""Silver 層 enrich 端點：把 on-demand enrichment 服務本體端點化。

執行流程：
    1. 接收 POST /enrich 的 page_id、dt 與 trigger，先驗證 X-User-Token 確認是誰下的指令，
       再呼叫 t_enrich_html_to_markdown 對該版本做 on-demand enrichment。
    2. enrichment 觸發後內部先從 Collection onenote_note_metadata 查快取，未命中快取才允許打 LLM。
    3. 接著 LLM 輸出的 enriched markdown 寫到 GCS processed-notes/。
    4. 再 upsert Collection onenote_note_metadata，最後回傳端點回應 (JSON 化的 python dict)。
    5. Streamlit 審查頁維持對 GCS 唯讀，無權呼叫 ETL 對 GCS 寫入，只能透過此端點觸發 enrich。

Usage:
    poetry run python -m task07_silver_service.app

Required .env keys:
    MONGO_ALTAS_URI                  MongoDB Atlas connection URI.
    MONGO_DB_NAME                    MongoDB database name.
    AGENT_PLATFORM_USER_CREDENTIALS  (On-premise only) Agent Platform Gemini service account JSON;
                                     uncomment the on-premise block in _get_genai_client() to use it.
    GCS_USER_CREDENTIALS             (On-premise only) GCS service account JSON; uncomment the
                                     on-premise block in t_enrich_html_to_markdown() to use it.
    GCP_PROJECT_ID                   GCP project ID for Agent Platform.
    ENVIRONMENT                      Deploymeny environment. Either of local, dev or prod.
    USER_ALLOWLIST                   JSON object mapping user email to role name.
    TOKEN_ISSUER_SA                  Email of the dashboard runtime service account that signs the token.

Optional .env keys:
    ONENOTE_GCS_BUCKET               GCS data lake bucket (default to onenote-vaults).
"""

from typing import Annotated, Literal

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel

from task07_common.auth import UserIdentity, register_validation_error_handler, verify_user
from task07_silver_service.t_enrich_html_to_markdown import t_enrich_html_to_markdown

load_dotenv()

app = FastAPI(title="task07 Silver enrich service")
register_validation_error_handler(app)


class EnrichRequest(BaseModel):
    """POST /enrich 的請求欄位。

    Attributes:
        page_id: OneNote 頁面代號。
        dt: 版本分區日期。
        trigger: 觸發來源，只接受 on_demand 與 regenerate，未提供時為 on_demand。
    """

    page_id: str
    dt: str
    trigger: Literal["on_demand", "regenerate"] = "on_demand"


@app.post("/enrich")
def enrich(body: EnrichRequest, user: Annotated[UserIdentity, Depends(verify_user)]) -> JSONResponse:
    """接收頁面代號、版本分區與觸發來源，呼叫 Silver 服務本體做 on-demand enrichment。

    request body 的欄位由 EnrichRequest 驗證；身分則由 verify_user 函式驗證，
    兩者都驗證通過才會打服務本體，服務本體的結果原樣轉成 JSON 回覆。

    Note:
        只有查無版本與未預期例外會回非 200 的狀態碼。命中快取、進入待審、circuit breaker 冷卻中、
        生成失敗與配額用盡都算業務結果而非傳輸失敗，一律回 200，由呼叫端依回應內容判讀。

        欄位不合法回 400 而非 FastAPI 預設的 422，此已由 module-level 的 register_validation_error_handler 改寫而成；
        身分驗證未通過則由 verity_user 函式拋出 401、403 或 503，並在此函式內部執行前拋出。

    Args:
        body: 通過驗證的請求欄位。
        user: 通過驗證的使用者身分，由 verify_user 注入。

    Returns:
        JSONResponse。查無版本回 404，未預期例外回 500，其餘回 200。

    Raises:
        HTTPException: 由 verify_user 拋出，缺 token 或驗簽失敗回 401、不在允許清單回 403、
            取不到驗簽金鑰回 503。
    """
    try:
        result = t_enrich_html_to_markdown(page_id=body.page_id, dt=body.dt, trigger=body.trigger)
    except Exception as e:
        logger.exception(f"[silver] enrich 未預期失敗: page_id={body.page_id}, dt={body.dt}")
        return JSONResponse(status_code=500, content={"error": f"[silver] {e}"})

    if result.get("status") == "not_found":
        return JSONResponse(status_code=404, content=result)

    logger.info(
        f"[silver] enrich: page_id={body.page_id}, dt={body.dt}, trigger={body.trigger}, "
        f"status={result.get('status')}, by={user.email}({user.role})"
    )
    return JSONResponse(status_code=200, content=result)


if __name__ == "__main__":
    # localhost:8002（與 gold_service 8003 錯開）
    uvicorn.run(app, host="127.0.0.1", port=8002)
