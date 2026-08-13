"""Silver 層 enrich 端點：把 task07 lazy_loading 的 on-demand enrichment 服務本體端點化。

執行流程：
    1. 接收 POST /enrich 的 page_id + dt + trigger
    → 呼叫 t_enrich_html_to_markdown 對該版本做 on-demand enrichment，
    2. enrichment 內部流程為查快取 → 必要時打 LLM → 寫 md 到 GCS processed-notes
    → upsert Collection onenote_note_metadata → 把回傳 dict JSON 化。
    3. Streamlit 審查頁維持對 GCS 唯讀，無權呼叫 ETL 對 GCS 寫入，只能透過此端點觸發 enrich。

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

Optional .env keys:
    ONENOTE_GCS_BUCKET               GCS data lake bucket (defaults to onenote-vaults).
"""

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from loguru import logger

from task07_silver_service.t_enrich_html_to_markdown import t_enrich_html_to_markdown

load_dotenv()

app = Flask(__name__)


@app.route("/enrich", methods=["POST"])
def enrich():
    """接收頁面代號、版本分區與觸發來源，呼叫 Silver 服務本體做 on-demand enrichment。

    先驗證必要欄位與觸發來源是否合法，再把服務本體的結果原樣轉成 JSON 回覆。

    Note:
        只有查無版本與未預期例外會回非 200 的狀態碼。命中快取、進入待審、circuit breaker 冷卻中、
        生成失敗與配額用盡都算業務結果而非傳輸失敗，一律回 200，由呼叫端依回應內容判讀。

    Returns:
        Flask 回應物件與 HTTP 狀態碼組成的 tuple。缺欄位或觸發來源非法回 400，
        查無版本回 404，未預期例外回 500，其餘回 200。
    """
    # 解析 request body 夾帶著的 json 引數，該引數正常來說應是 json 形式的字串。
    # silent=True 代表如果不是 json 字串則回傳 None 不拋例外
    body = request.get_json(silent=True) or {}
    page_id = body.get("page_id")
    dt = body.get("dt")
    trigger = body.get("trigger", "on_demand")

    if not page_id or not dt:
        return jsonify({"error": "Bad Request：缺少必要欄位：page_id、dt"}), 400

    if trigger not in ("on_demand", "regenerate"):
        return jsonify({"error": f"Bad Request：trigger 必須為 on_demand 或 regenerate，收到：{trigger}"}), 400

    try:
        result = t_enrich_html_to_markdown(page_id=page_id, dt=dt, trigger=trigger)
    except Exception as e:
        logger.exception(f"[silver] enrich 未預期失敗: page_id={page_id}, dt={dt}")
        return jsonify({"error": f"[silver] {e}"}), 500

    if result.get("status") == "not_found":
        return jsonify(result), 404

    logger.info(f"[silver] enrich: page_id={page_id}, dt={dt}, trigger={trigger}, status={result.get('status')}")
    return jsonify(result), 200


if __name__ == "__main__":
    # localhost:8002（與 gold_service 8003 錯開）
    app.run(port=8002, debug=True)
