"""Gold 層 Archive 端點：把 task07 lazy_loading 的核可後歸檔端點化。

執行流程：
    1. 接收 POST /archive 的 page_id + dt + role + action
    2. Action 為 "approved"，呼叫 archive_note，內部流程為:
    複製 md+png 到 archived-notes → upsert Collection onenote_note_metadata
    → 回讀 archived md，萃取 frontmatter → upsert onenote_note_metadata
    3. Action 為 "rejected"，呼叫 reject_note，內部流程為:
    upsert Collection onenote_note_metadata
    → 讀 rejected md，萃取 md_frontmatter → upsert onenote_note_metadata
    4. Streamlit 審查頁維持唯讀，只透過此端點觸發。

Usage:
    poetry run python -m task07_gold_service.app

Required .env keys:
    MONGO_ALTAS_URI     MongoDB Atlas connection URI.
    MONGO_DB_NAME       MongoDB database name.

Optional .env keys:
    ONENOTE_GCS_BUCKET  GCS data lake bucket (defaults to onenote-vaults).
"""

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from loguru import logger

from task07_gold_service.l_archive_note import archive_note, reject_note

load_dotenv()

app = Flask(__name__)


@app.route("/archive", methods=["POST"])
def archive():
    """接收 page_id + dt + role + action，approve 歸檔 / reject 標記 review_closed。

    HTTP 狀態碼：缺欄位或非法 action 400；查無版本 404；approve 遇同名衝突 409；
    未預期例外 500；其餘 200（回傳結果 dict 由呼叫端判讀）。
    """
    body = request.get_json(silent=True) or {}
    page_id = body.get("page_id")
    dt = body.get("dt")
    role = body.get("role")
    action = body.get("action")

    if not all([page_id, dt, role, action]):
        return jsonify({"error": "Bad Request：缺少必要欄位：page_id、dt、role、action"}), 400

    if action not in ("approved", "rejected"):
        return jsonify({"error": f"Bad Request：action 必須為 approved 或 rejected，收到：{action}"}), 400

    # ── rejected：呼叫 Gold 層 reject_note ─────────────────────
    if action == "rejected":
        try:
            result = reject_note(page_id=page_id, dt=dt, role=role)
        except Exception as e:
            logger.exception(f"[gold] reject 未預期失敗: page_id={page_id}, dt={dt}")
            return jsonify({"error": f"[gold:reject] {e}"}), 500
        if result.get("status") == "not_found":
            return jsonify(result), 404
        return jsonify(result), 200

    # ── approved：呼叫 Gold 層 archive note 做歸檔 ──────────────
    try:
        result = archive_note(page_id=page_id, dt=dt, role=role)
    except Exception as e:
        logger.exception(f"[gold] archive 未預期失敗: page_id={page_id}, dt={dt}")
        return jsonify({"error": f"[gold] {e}"}), 500

    status = result.get("status")
    if status == "not_found":
        return jsonify(result), 404
    if status == "archived_conflict":
        return jsonify(result), 409
    if status != "archived":  # md 未生成 / 複製失敗等業務錯誤
        return jsonify(result), 422

    logger.info(f"[gold] archived: page_id={page_id}, dt={dt}, role={role}")
    return jsonify(result), 200


if __name__ == "__main__":
    # localhost:8003（與 silver_service 8002 錯開）
    app.run(port=8003, debug=True)
