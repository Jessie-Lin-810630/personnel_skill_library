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
    MONGO_ALTAS_URI                MongoDB Atlas connection URI.
    MONGO_DB_NAME                  MongoDB database name.
    AGENT_PLATFORM_USER_CREDENTIALS  Vertex AI Gemini service account JSON.
    GCP_PROJECT_ID                 GCP project ID for Vertex AI.

Optional .env keys:
    ONENOTE_GCS_BUCKET             GCS data lake bucket (defaults to onenote-vaults).
"""

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from loguru import logger

from task07_silver_service.t_enrich_html_to_markdown import t_enrich_html_to_markdown

load_dotenv()

app = Flask(__name__)


@app.route("/enrich", methods=["POST"])
def enrich():
    """接收 page_id + dt + trigger，呼叫 Silver 服務本體做 on-demand enrichment。

    回傳原樣 JSON 化的服務結果 dict (status、cache_hit、md_path、circuit_open、error)。
    HTTP 狀態碼：缺欄位 400、trigger 非法 400、查無版本 404、未預期例外 500、其餘 200
    (cache hit / pending_review / circuit_open / enrich_failed / quota 皆屬業務結果，回 200
    由呼叫端依 dict 欄位判讀)。
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

    logger.info(f"[silver] enrich: page_id={page_id}, dt={dt}, trigger={trigger} → {result.get('status')}")
    return jsonify(result), 200


if __name__ == "__main__":
    # localhost:8002（與 gold_service 8003 錯開）
    app.run(port=8002, debug=True)
