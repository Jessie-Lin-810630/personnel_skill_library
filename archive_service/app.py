import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from google.api_core.exceptions import DeadlineExceeded, GoogleAPICallError, ServiceUnavailable
from loguru import logger
from pymongo.errors import ConnectionFailure, NetworkTimeout, ServerSelectionTimeoutError

from archive_service.utils.gcs_archiver import archive_md, copy_images
from archive_service.utils.mongodb import get_db_altas

load_dotenv()


# 建立總機，所有路由從 app 為根開始
app = Flask(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# 當有使用者對 app/archive 這個網址發送 request.post() 請求時，會經過路由導到 archive() 這支函式
@app.route("/archive", methods=["POST"])
def archive():

    # 解析 request body 夾帶著的 json 引數，該引數正常來說應是 json 形式的字串。silent=True 代表如果不是 json 字串則回傳 None 不拋例外
    body = request.get_json(silent=True) or {}
    page_id = body.get("page_id")
    role = body.get("role")
    action = body.get("action")

    if not all([page_id, role, action]):
        return jsonify({"error": "Bad Request：'缺少必要欄位：page_id、role、action'"}), 400  # 400 = 錯誤請求

    if action not in ("approved", "rejected"):
        return jsonify({"error": f"Bad Request：'action 必須為 approved 或 rejected，收到：{action}'"}), 400

    # ── DB 連線 + 查詢頁面紀錄 ──────────────────────────────────────────
    try:
        db = get_db_altas()
        coll = db["onenote_page_metadata"]
        page_record = coll.find_one({"page_id": page_id})
    except (ServerSelectionTimeoutError, NetworkTimeout) as e:
        logger.exception(f"[DB] 連線逾時: page_id={page_id}")
        return jsonify({"error": f"[DB:timeout] {e}"}), 504
    except ConnectionFailure as e:
        logger.exception(f"[DB] 連線失敗: page_id={page_id}")
        return jsonify({"error": f"[DB:unavailable] {e}"}), 503
    except Exception as e:
        logger.exception(f"[DB] find_one 錯誤: page_id={page_id}")
        return jsonify({"error": f"[DB] {e}"}), 500

    if not page_record:
        return jsonify({"error": f"Not found：'找不到 page_id={page_id}'"}), 404

    now = _now_utc()

    # ── rejected 狀態寫入（rejected 路徑在此 return，不往下走）────────
    if action == "rejected":
        try:
            result = coll.update_one({"page_id": page_id},
                                     {"$set": {
                                         "status": "rejected",
                                         "review_result": "rejected",
                                         "reviewed_by_role": role,
                                         "reviewed_at": now,
                                     }},
                                     )
        except (ServerSelectionTimeoutError, NetworkTimeout) as e:
            logger.exception(f"[DB] rejected 寫入逾時: page_id={page_id}")
            return jsonify({"error": f"[DB:timeout] {e}"}), 504
        except ConnectionFailure as e:
            logger.exception(f"[DB] rejected 寫入連線失敗: page_id={page_id}")
            return jsonify({"error": f"[DB:unavailable] {e}"}), 503
        except Exception as e:
            logger.exception(f"[DB] rejected 寫入錯誤: page_id={page_id}")
            return jsonify({"error": f"[DB] {e}"}), 500

        if result.matched_count == 0:
            logger.warning(f"[DB] rejected 寫入時找不到資料(可能已被刪除): page_id={page_id}")
            return jsonify({"error": f"找不到 page_id={page_id}，資料可能已被移除"}), 404

        logger.info(f"Rejected: page_id={page_id}, role={role}")
        return jsonify({"status": "ok"}), 200

    # ── action == "approved" 狀態，複製圖片到 dest_bucket + 記錄 img_archive_path ───────────────
    try:
        img_archive_paths = copy_images(page_record)
        result = coll.update_one({"page_id": page_id},
                                 {"$set": {"img_archive_path": img_archive_paths}},
                                 )

    except (DeadlineExceeded, ServerSelectionTimeoutError, NetworkTimeout) as e:
        logger.exception(f"[GCS:images] 逾時: page_id={page_id}")
        return jsonify({"error": f"[GCS:images:timeout] {e}"}), 504
    except ServiceUnavailable as e:
        logger.exception(f"[GCS:images] 服務無法連線: page_id={page_id}")
        return jsonify({"error": f"[GCS:images:unavailable] {e}"}), 503
    except (GoogleAPICallError, ConnectionFailure) as e:
        logger.exception(f"[GCS:images] 上游回應錯誤: page_id={page_id}")
        return jsonify({"error": f"[GCS:images:bad-gateway] {e}"}), 502
    except Exception as e:
        logger.exception(f"[GCS:images] 圖片複製失敗: page_id={page_id}")
        return jsonify({"error": f"[GCS:images] {e}"}), 500

    if result.matched_count == 0:
        logger.warning(f"[DB] approved 後複製圖片時找不到 page_id (可能已被刪除): page_id={page_id}")
        return jsonify({"error": f"找不到 page_id={page_id}，資料可能已被移除"}), 404

    # ── 歸檔 MD 到 dest_bucket + 記錄 md_archive_path ────────────────
    try:
        md_archive_path = archive_md(page_record, img_archive_paths)
        result = coll.update_one({"page_id": page_id},
                                 {"$set": {"md_archive_path": md_archive_path}},
                                 )
    except (DeadlineExceeded, ServerSelectionTimeoutError, NetworkTimeout) as e:
        logger.exception(f"[GCS:md] 逾時: page_id={page_id}")
        return jsonify({"error": f"[GCS:md:timeout] {e}"}), 504
    except ServiceUnavailable as e:
        logger.exception(f"[GCS:md] 服務無法連線: page_id={page_id}")
        return jsonify({"error": f"[GCS:md:unavailable] {e}"}), 503
    except (GoogleAPICallError, ConnectionFailure) as e:
        logger.exception(f"[GCS:md] 上游回應錯誤: page_id={page_id}")
        return jsonify({"error": f"[GCS:md:bad-gateway] {e}"}), 502
    except Exception as e:
        logger.exception(f"[GCS:md] MD 歸檔失敗: page_id={page_id}")
        return jsonify({"error": f"[GCS:md] {e}"}), 500

    if result.matched_count == 0:
        logger.warning(f"[DB] approved 後歸檔 md 時找不到 page_id (可能已被刪除): page_id={page_id}")
        return jsonify({"error": f"找不到 page_id={page_id}，資料可能已被移除"}), 404

    # ── 寫入最終歸檔狀態 ──────────────────────────────────────────────
    try:
        result = coll.update_one({"page_id": page_id},
                                 {"$set": {
                                     "status": "archived",
                                     "review_result": "approved",
                                     "reviewed_by_role": role,
                                     "reviewed_at": now,
                                     "archived_at": now,
                                 }},
                                 )
    except (ServerSelectionTimeoutError, NetworkTimeout) as e:
        logger.exception(f"[DB:final] 最終狀態寫入逾時: page_id={page_id}")
        return jsonify({"error": f"[DB:final:timeout] {e}"}), 504
    except ConnectionFailure as e:
        logger.exception(f"[DB:final] 最終狀態寫入連線失敗: page_id={page_id}")
        return jsonify({"error": f"[DB:final:unavailable] {e}"}), 503
    except Exception as e:
        logger.exception(f"[DB:final] 最終狀態寫入錯誤: page_id={page_id}")
        return jsonify({"error": f"[DB:final] {e}"}), 500
    if result.matched_count == 0:
        logger.warning(f"[DB] 最終狀態寫入時，找不到 page_id (可能已被刪除): page_id={page_id}")
        return jsonify({"error": f"找不到 page_id={page_id}，資料可能已被移除"}), 404

    logger.info(f"Archived: page_id={page_id}, role={role}, md={md_archive_path}")
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    # localhost:8001
    app.run(port=8001, debug=True)
