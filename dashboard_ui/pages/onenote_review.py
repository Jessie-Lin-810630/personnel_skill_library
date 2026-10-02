"""OneNote 審查頁：登入 gate + 多版本對照 + on-demand Silver enrichment + Gold 歸檔/退件。

登入畫面與角色推導由 utils.auth_gate 提供；登入後採 task07 lazy_loading 變體的多版本審查。
執行流程：讀 onenote_note_metadata（唯讀）依 page_id 分組 → 三層下拉選頁 →
以 dt= 圓鈕切換同名筆記多版本 → 左渲染 bronze html、右渲染 silver md（皆自 gs:// URI）→
選到 md_path=null 版本時 POST 呼叫 Silver enrich 端點即時生成 md、已生成則直接讀 GCS（cache hit）。
含 regenerate（trigger=regenerate、受 quota）與 approve/reject（POST 呼叫 Gold archive 端點）。

Required .env keys:
    MONGO_ALTAS_URI        MongoDB Atlas connection URI.
    MONGO_DB_NAME          MongoDB database name.
    SILVER_ENDPOINT_URL    Silver enrich FastAPI endpoint URL (e.g. http://localhost:8002/enrich).
    GOLD_ENDPOINT_URL      Gold archive FastAPI endpoint URL (e.g. http://localhost:8003/archive).
    USER_ALLOWLIST         JSON object mapping user email to role name; the Guest role must be listed
                           explicitly. Emails not listed are denied access to this page.
    TOKEN_ISSUER_SA        Email of the dashboard runtime service account that signs the X-User-Token.

Login is handled by Streamlit's built-in OIDC (st.login) with Google as the provider.
Must store App's client id, client secret and cookie secret live in .streamlit/secrets.toml, not in .env.
"""

import os
import re

import google.auth.transport.requests
import google.oauth2.id_token
import markdown as md_lib
import requests
import streamlit as st
from dotenv import load_dotenv
from utils.auth_gate import GUEST_ROLE, render_logout_button, render_review_login_page, require_login
from utils.gcs_reader import read_image_base64_by_uri, read_text_by_uri
from utils.interact_with_mongodb import get_db_atlas, get_onenote_versioned_pages, to_tpe_time_text
from utils.ui_elements import color_map, render_side_bar
from utils.user_token_for_silver_and_gold import mint_user_token

load_dotenv()

PLACEHOLDER = "請選擇"
SILVER_URL = os.getenv("SILVER_ENDPOINT_URL", "")
GOLD_URL = os.getenv("GOLD_ENDPOINT_URL", "")

# Guest 為示範角色：僅能瀏覽下方預設的筆記本與章節，且 approve/reject 只呈現表象、後端沒有實際寫入動作
GUEST_ALLOWED_NOTEBOOK = "生物製藥相關"
GUEST_ALLOWED_SECTION = ["General technical knowledge", "法規"]

st.set_page_config(
    page_title="企業知識資料庫協作平台",
    page_icon="🗂️",
    layout="wide",
    initial_sidebar_state="expanded",
)
render_side_bar()


# ── 登入 gate ─────────────────────────────
# 未登入者與 USER_ALLOWLIST 外的帳號都在此停住；通過者取得 email 與 USER_ALLOWLIST 指定的角色
_user_email, _role = require_login(render_login_page=render_review_login_page)

# ─────────────────────────────────────────
# 標題 + 角色 + 登出
# ─────────────────────────────────────────
st.markdown(
    f"""
<div style="
    background: linear-gradient(135deg, #0f2040 50%, #0d1526 0%, #0f2040 50%, #1a1040 100%);
    border-radius: 16px; padding: 2rem 3rem; margin-bottom: 1.2rem;
    border: 1px solid #2a3550; text-align: center;">
    <h1 style="color:{color_map["FONT_CLR"]}; font-size:2.2rem; margin:0 0 0.4rem 0; font-weight:800;">
        🗂️ 以生成式模型擴充 OneNote Notes 語意之結果審查系統
    </h1>
    <p style="color:{color_map["TEAL"]};text-align: left; font-size:0.9rem; margin:0; letter-spacing:1px;">
        步驟1: 從下拉式清單中依序選擇 筆記本 -> 章節 -> 頁面，以打開待審閱的筆記內容。<br>
        步驟2: 系統會自動跳出最新版本的筆記頁面，經由 LLM
        擴寫語意的結果，呈現於下方，左側為原始筆記、右側為語義擴充後新筆記。<br>
        步驟3: 若希望查看舊版的筆記內容，請於下方圓鈕切換版本，版本號以上傳 OneNote 到資料湖的日期為命名。<br>
        步驟4: 檢視右側筆記內容，評估模型生成之準確、可靠、隱私安全是否符合預期後，點選審查操作輸入您的審查結果。<br>
    </p>
    <p style="color:{color_map["PINK"]};text-align: center; font-size:0.9rem; margin:0; letter-spacing:1px;">
        💡 提醒: 生成式大語言模型的輸出帶有隨機性，若不滿意生成之內容，可點選「重新生成」，
        系統將以更強大的模型重新擴寫，<br>
        然而企業導入 AI 過程中，需紀錄與控管導入成本 (如: tokens)，每篇筆記最多重新生成 2 次為上限，敬請珍惜使用。<br>
        <br>
        🚄  受核可的筆記將推送到向量資料庫，作為知識庫檢索能力提升的泉源！
    </p>
</div>
""",
    unsafe_allow_html=True,
)

# 左側留白把「角色 + 登出」推到右上角並貼近，減少視覺跨度；vertical center 讓文字與按鈕同高
_spacer, role_col, logout_col = st.columns([7, 2, 1], vertical_alignment="center")
with role_col:
    st.markdown(
        f"<div style='text-align:right;'>{_user_email}<br>目前角色：<b>{_role}</b></div>",
        unsafe_allow_html=True,
    )
with logout_col:
    render_logout_button("guest_reviewed", "enrich_attempted")

st.divider()

# ─────────────────────────────────────────
# 載入多版本清單
# ─────────────────────────────────────────


@st.cache_data(ttl=60)
def _load_versions() -> list[dict]:
    """讀取所有待審閱的筆記版本並快取一分鐘，供三層下拉選單與版本切換使用。

    快取時間刻意設短，因為審查動作會即時改變版本的可審閱狀態；
    觸發生成或送出審核結果後也會主動清空快取，讓畫面立刻反映最新狀態。

    Returns:
        待審閱的筆記版本文件清單，依 html_downloaded_at 由新到舊排序；無資料時為空 list。
    """
    db = get_db_atlas()
    return get_onenote_versioned_pages(db)


versions_all = _load_versions()

# Guest 僅能看到指定筆記本／章節的筆記；過濾在此，下游三層下拉自然只呈現允許範圍
is_guest = st.session_state.get("role") == GUEST_ROLE
if is_guest:
    versions_all = [
        v
        for v in versions_all
        if v.get("notebook") == GUEST_ALLOWED_NOTEBOOK and v.get("section") in GUEST_ALLOWED_SECTION
    ]

if not versions_all:
    st.warning("尚無 Bronze 資料，請先執行 task07 lazy_loading Bronze ETL。")
    st.stop()

# ─────────────────────────────────────────
# 三層下拉選定一頁筆記（notebook → section → page_title）
# ─────────────────────────────────────────
notebooks_opts = [PLACEHOLDER] + sorted({v["notebook"] for v in versions_all if v.get("notebook")})
col_nb, col_sec, col_pg = st.columns(3)

with col_nb:
    selected_nb = st.selectbox(f"📓 筆記本 ({len(notebooks_opts) - 1}份待審中)", notebooks_opts, key="vr_notebook")

sections_raw = (
    sorted({v["section"] for v in versions_all if v.get("notebook") == selected_nb and v.get("section")})
    if selected_nb != PLACEHOLDER
    else []
)
with col_sec:
    selected_sec = st.selectbox(
        f"📂 章節 ({len(sections_raw)}篇待審中)", [PLACEHOLDER] + sections_raw, key=f"vr_section_{selected_nb}"
    )

titles_raw = (
    sorted(
        {
            v["page_title"]
            for v in versions_all
            if v.get("notebook") == selected_nb and v.get("section") == selected_sec and v.get("page_title")
        }
    )
    if selected_sec != PLACEHOLDER
    else []
)
with col_pg:
    selected_title = st.selectbox(
        f"📄 頁面 ({len(titles_raw)}頁待審中)",
        [PLACEHOLDER] + titles_raw,
        key=f"vr_page_{selected_nb}_{selected_sec}",
    )

all_selected = selected_nb != PLACEHOLDER and selected_sec != PLACEHOLDER and selected_title != PLACEHOLDER
if not all_selected:
    st.info("請由上方依序選擇筆記本 / 章節 / 頁面，以載入該頁的所有版本對照。")
    st.stop()

# ─────────────────────────────────────────
# 該頁的所有 dt= 版本（依 html_downloaded_at 由新到舊；圓鈕切換）
# ─────────────────────────────────────────
page_versions = [
    v
    for v in versions_all
    if v.get("notebook") == selected_nb and v.get("section") == selected_sec and v.get("page_title") == selected_title
]
page_versions.sort(key=lambda v: str(v.get("html_downloaded_at", "")), reverse=True)


def _version_label(v: dict) -> str:
    """組出版本切換選項的顯示文字，內容為版本日期加上生成狀態。

    Args:
        v: 單一筆記版本的 metadata 文件。

    Returns:
        str: 版本日期與生成狀態串接後的文字，尚未生成 Markdown 時另附觸發生成的提示。
    """
    dt = v.get("dt", "?")
    mark = "✅ 已生成，可審閱" if v.get("enriched_md_path") else "🟠 尚未生成，切換版本後觸發生成即可開始審閱"
    return f"{dt}　{mark}"


selected_idx = st.radio(
    "💡 切換查看之版本號 (版本號：即筆記上傳日期)：",
    options=list(range(len(page_versions))),
    format_func=lambda i: _version_label(page_versions[i]),
    key=f"vr_ver_{selected_nb}_{selected_sec}_{selected_title}",
)
version = page_versions[selected_idx]
page_id = version.get("page_id", "")
dt = version.get("dt", "")
html_uri = version.get("html_path", "")
md_uri = version.get("enriched_md_path")
status = version.get("status", "")

# 逐版本判斷：只有選中版本自己已歸檔時，該版唯讀、按鈕失效（不影響其他版本）。
# review_closed（rejected/overwritten）版本已由 get_onenote_versioned_pages 過濾掉、不會出現在此。
is_version_archived = status == "archived"
if is_version_archived:
    st.success(
        f"✅ 此版本已於 {to_tpe_time_text(version.get('archived_at', ''))} 歸檔"
        f"（{version.get('reviewed_by_role', '')}），唯讀。"
    )

st.divider()

# ─────────────────────────────────────────
# 呼叫端點：session 狀態、Silver enrich、Gold archive
#
# 三支函式放在一起，因為它們共用同一組前提（page_id、dt、is_guest）與同一套錯誤處理方式：
#   _call_silver → 送出 enrich 請求，把結果與錯誤訊息回傳給呼叫端
#   _trigger     → 包住 _call_silver，依結果決定記錯誤、顯示提示或清快取重載
#   _call_gold   → 送出 approve／reject 請求，Guest 走畫面假象不呼叫端點
# 函式只定義不執行。實際呼叫的地方在下方三處，各自以「觸發點一／二／三」標題標出。
# ─────────────────────────────────────────
if "enrich_attempted" not in st.session_state:
    st.session_state.enrich_attempted = {}  # {(page_id, dt): error_msg or None}

# Guest 於本 session 已操作過 approve/reject 的版本（(page_id, dt) 集合），用來禁用按鈕；
# 登出時由 render_logout_button 清空，下次登入即可再操作一次
if "guest_reviewed" not in st.session_state:
    st.session_state.guest_reviewed = set()


def _call_silver(trigger: str) -> tuple[dict | None, str | None]:
    """呼叫 Silver enrich 端點，為當前選定的版本生成語意增強後的 Markdown。

    請求會帶上 ID token，端點需驗證呼叫方身分。逾時上限設為 180 秒，因 LLM 生成耗時較長。
    各類錯誤一律轉成可直接顯示給使用者的訊息回傳，不向上拋出例外，避免整頁中斷。

    Args:
        trigger: 觸發來源，區分是首次進入該版本自動觸發，還是使用者手動要求重新生成。

    Returns:
        端點回應內容與錯誤訊息組成的 tuple。成功時錯誤訊息為 None，
        失敗時回應內容為 None、錯誤訊息說明失敗原因。
    """
    # Guest 不能呼叫 Silver
    # 上游已在自動觸發與重試按鈕兩處擋下，這裡再擋一次，避免日後新增觸發點時漏掉。
    if is_guest:
        return None, "訪客身分無法觸發語意擴充生成。"

    if not SILVER_URL:
        return None, "SILVER_ENDPOINT_URL 未設定，無法呼叫 Silver 端點。"

    # Cloud Run Service 相互溝通是透過在 request headers `Authorization` 夾帶 ID token 做身份驗證
    auth_req = google.auth.transport.requests.Request()
    token = google.oauth2.id_token.fetch_id_token(auth_req, SILVER_URL)

    try:
        # 把登入成功的使用者之 mail address 與角色包成一張短效 token。
        user_token = mint_user_token(_user_email)
    except Exception as e:  # noqa: BLE001
        return None, f"無法簽發身分憑證：{e}"

    try:
        # 隨前端發送請求給後端時，夾帶 token 在 header 'X-User-Token' 裡面
        resp = requests.post(
            SILVER_URL,
            json={"page_id": page_id, "dt": dt, "trigger": trigger},
            timeout=180,
            headers={
                # Cloud Run IAM 負責用這個檢查是「哪個服務」送出請求
                "Authorization": f"Bearer {token}",
                # 後端程式用這個檢查是「哪個使用者」下指令要送請求
                "X-User-Token": user_token,
            },
        )
    except requests.exceptions.ReadTimeout:
        return None, "端點回應逾時（LLM 生成耗時，請稍後重新整理確認）。"
    except requests.exceptions.ConnectionError:
        return None, "無法連線至端點，請確認服務是否啟動。"
    except Exception as e:  # noqa: BLE001
        return None, f"呼叫端點時發生錯誤：{e}"

    data = resp.json() if resp.content else {}
    if resp.status_code == 404:
        return None, data.get("error", f"查無版本 (page_id={page_id}, dt={dt})")
    if not resp.ok:
        return None, data.get("error", f"端點回應錯誤：{resp.status_code}")
    return data, None


def _trigger(trigger: str) -> None:
    """觸發 Silver 端點生成 Markdown，並依回應結果更新畫面狀態。

    三種失敗情形分別處理：呼叫失敗與 circuit breaker 冷卻中會把訊息記進 session state，
    讓同一個版本在本次 session 不再自動重試；超出重新生成次數上限則只提示，不記錄。
    生成成功時清空版本清單快取並重跑整頁，讓右側改為渲染新產出的 Markdown。

    Args:
        trigger: 觸發來源，區分是首次進入該版本自動觸發，還是使用者手動要求重新生成。

    Returns:
        None: 只更新畫面與 session state，不回傳值。
    """
    with st.spinner("重新生成中，請稍後，Document Enrichment 進行中..."):
        data, err = _call_silver(trigger)
    if err:
        st.session_state.enrich_attempted[(page_id, dt)] = err
        st.error(err)
        return
    if data.get("circuit_open"):
        msg = "LLM 連續失敗，服務已暫停，請稍後再試。"
        st.session_state.enrich_attempted[(page_id, dt)] = msg
        st.warning(msg)
        return
    if data.get("error"):  # 例如 regenerate quota exceeded
        st.warning(data["error"])
        return
    # 成功產出（cache hit / miss 皆有 md_path）→ 清快取重載，讓右側渲染新 md
    st.session_state.enrich_attempted.pop((page_id, dt), None)
    _load_versions.clear()
    st.rerun()


def _call_gold(action: str) -> None:
    """呼叫 Gold 端點送出審核結果，核可即歸檔，退件則標記為已退回。

    訪客帳號僅供展示，這裡直接以提示訊息呈現操作成功的樣子，完全不呼叫端點，資料庫也不做任何寫入。
    正式角色的請求會帶上 ID token 與當前登入角色，逾時上限設為 180 秒，因複製檔案到資料湖耗時較長。
    各類錯誤一律直接顯示給使用者，不向上拋出例外。成功時清空版本清單快取並重跑整頁，
    讓已處理的版本立即退出待審清單。

    Args:
        action: 審核結果，approved 代表核可歸檔，rejected 代表退件。

    Returns:
        None: 只更新畫面與遠端狀態，不回傳值。
    """
    # Guest 為示範帳號：只呈現操作成功的表象，完全不呼叫 Gold 端點、後端 MongoDB 不做任何寫入
    if is_guest:
        # 記住此版本已操作 → 下方按鈕禁用；toast 可跨 rerun 顯示成功假象
        st.session_state.guest_reviewed.add((page_id, dt))
        st.toast("✅ 歸檔成功" if action == "approved" else "✅ 退件成功", icon="✅")
        st.rerun()
        return
    if not GOLD_URL:
        st.error("找不到GOLD URL！")
        return
    with st.spinner(f"{action} 任務執行中..."):
        # Cloud Run Service 相互溝通是透過在 request headers `Authorization` 夾帶 ID token 做身份驗證
        auth_req = google.auth.transport.requests.Request()
        token = google.oauth2.id_token.fetch_id_token(auth_req, GOLD_URL)

        try:
            # 把登入成功的使用者之 mail address 與角色包成一張短效 token。
            user_token = mint_user_token(_user_email)
        except Exception as e:  # noqa: BLE001
            st.error(f"無法簽發身分憑證：{e}")
            return

        try:
            # role 不放進 body，端點一律採用 X-User-Token 驗證後推導的角色
            resp = requests.post(
                GOLD_URL,
                json={"page_id": page_id, "dt": dt, "action": action},
                timeout=180,
                headers={
                    # Cloud Run IAM 負責用這個檢查是「哪個服務」送出請求
                    "Authorization": f"Bearer {token}",
                    # 後端程式用這個檢查是「哪個使用者」下指令要送請求
                    "X-User-Token": user_token,
                },
            )
        except requests.exceptions.ReadTimeout:
            st.error("回應逾時 (GCS 複製耗時，請聯繫客服，重新整理確認是否已歸檔)。")
            return
        except requests.exceptions.ConnectionError:
            st.error("無法連線至端點，請確認服務是否啟動。")
            return
        except Exception as e:  # noqa: BLE001
            st.error(f"呼叫端點時發生錯誤：{e}")
            return

    data = resp.json() if resp.content else {}
    if not resp.ok:
        st.error(data.get("error", f"端點回應錯誤：{resp.status_code}"))
        return
    _load_versions.clear()
    st.rerun()


# ─────────────────────────────────────────
# 觸發點一：選定版本後自動觸發 Silver（另兩個觸發點在渲染區與頁尾，各自有同樣的標題）
# ─────────────────────────────────────────
# 由前端依登入者的角色決定他能不能看到「選到一個還沒生成 md 的版本」時，系統自動觸發 Silver 服務。
#
# Guest 視角：一律不觸發。選到還沒生成 md 的版本時走 if，只顯示提示要他改看已生成的版本；
# 選到已生成 md 的版本時，if 的 not md_uri 不成立、elif 的 not md_uri 也不成立，兩支都不進，
# 直接往下渲染既有的 md。所以 Guest 在任何情況下都到不了 _trigger。
# 後端 Silver 服務還會再檢查一次登入者角色，所以即使前端開放 Guest 送請求過去仍會被回 403。
#
# 非 Guest 視角：if 的 is_guest 不成立，判斷全靠 elif 三個條件上。
# 他看到的文件還沒生成 md、該文件版本自己尚未歸檔、且在本 session 還沒有任何觸發 Silver 失敗過的紀錄，
# 三者同時成立才自動觸發一次 Silver 服務；
# 已歸檔的版本不再燒觸發 Silver 服務；或是嘗試觸發過但是 Silver 失敗就記在 enrich_attempted 裡，
# 來避免同一版本又被自動觸發。
if is_guest and not md_uri:
    st.info("此版本尚未生成語意擴充後的筆記。訪客身分不觸發生成，請改看已生成的版本。")
elif not md_uri and not is_version_archived and (page_id, dt) not in st.session_state.enrich_attempted:
    _trigger("on_demand")

# ─────────────────────────────────────────
# 左右對照渲染（白底）
# ─────────────────────────────────────────
_WHITE_FRAME = """
<html><head><meta charset="utf-8">
<style>
  html, body {{ margin:0; min-height:100vh; box-sizing:border-box;
             background:#ffffff; color:#111; font-family:sans-serif;
             font-size:14px; line-height:1.6; padding:0.5rem; overflow-y:auto; }}
  img {{ max-width:100%; }}
  pre, code {{ background:#f3f4f6; border-radius:4px; padding:2px 6px; }}
  table {{ border-collapse:collapse; width:100%; }}
  th, td {{ border:1px solid #ccc; padding:0.4rem 0.6rem; }}
</style>
</head><body>{content}</body></html>
"""

# 圖片實體存在 bronze raw-notes 的 dt= 分區 _images/ 下；html 與 md 皆以此為準
img_prefix = html_uri.rsplit("/", 1)[0] if html_uri else ""


def _flatten_onenote_html(html: str) -> str:
    """取出 OneNote 匯出 HTML 的 body 內層，並移除絕對定位與固定寬度。

    OneNote 匯出的 HTML 會在 body 內層包一層絕對定位的區塊。
    絕對定位的元素脫離正常文件流，撐不開父層高度，導致白底區塊的高度忽長忽短。
    因此這裡改抽出 body 內層，並清掉絕對定位、位移座標與固定寬度三類樣式，讓內容回到正常文件流。

    Args:
        html: 已完成圖片內嵌的完整 HTML 文件字串。

    Returns:
        str: 可直接放進白底框架渲染的 HTML 片段；找不到 body 標籤時原樣回傳。
    """
    # 只取 body 內層
    m = re.search(r"<body[^>]*>(.*?)</body>", html, re.S | re.I)
    inner = m.group(1) if m else html

    # 移除絕對定位與固定寬度，讓內容回到正常流、能撐開高度
    inner = re.sub(r"position\s*:\s*absolute\s*;?", "", inner, flags=re.I)
    inner = re.sub(r"(left|top)\s*:\s*[\d.]+px\s*;?", "", inner, flags=re.I)
    inner = re.sub(r"width\s*:\s*1210px\s*;?", "", inner, flags=re.I)
    return inner


def _replace_images_in_html(html: str) -> str:
    """把 HTML 中指向圖片資料夾的相對路徑，替換成內嵌的 base64 圖片。

    圖片實體存放在資料湖中該版本分區底下的圖片資料夾，瀏覽器無法直接取用，
    因此逐一讀出並改以 data URI 內嵌。個別圖片讀取失敗時保留原始寫法，只讓該張圖顯示不出來。

    Args:
        html: 從資料湖讀出的原始 HTML 文件字串。

    Returns:
        str: 圖片來源已替換為 base64 data URI 的 HTML 字串。
    """

    def repl(m):
        """把單一個 HTML 圖片來源的比對結果，換成內嵌的 base64 圖片。

        Args:
            m: 正則的比對結果，第一組是圖片檔名。

        Returns:
            str: 改寫後的 src 屬性字串；該圖讀取失敗時原樣回傳比對到的內容。
        """
        data_uri = read_image_base64_by_uri(f"{img_prefix}/_images/{m.group(1)}")
        return f'src="{data_uri}"' if data_uri else m.group(0)

    return re.sub(r'src="_images/([^"]+)"', repl, html)


def _replace_images_in_md(md: str) -> str:
    """把 Markdown 中指向圖片資料夾的相對路徑，替換成內嵌的 base64 圖片。

    替換時保留原本的圖片替代文字。個別圖片讀取失敗時保留原始語法，只讓該張圖顯示不出來。

    Args:
        md: 從資料湖讀出的原始 Markdown 字串。

    Returns:
        str: 圖片來源已替換為 base64 data URI 的 Markdown 字串。
    """

    def repl(m):
        """把單一個 Markdown 圖片語法的比對結果，換成內嵌的 base64 圖片。

        Args:
            m: 正則的比對結果，第一組是替代文字、第二組是圖片檔名。

        Returns:
            str: 改寫後的 Markdown 圖片語法，替代文字保持不變；
                該圖讀取失敗時原樣回傳比對到的內容。
        """
        data_uri = read_image_base64_by_uri(f"{img_prefix}/_images/{m.group(2)}")
        return f"![{m.group(1)}]({data_uri})" if data_uri else m.group(0)

    return re.sub(r"!\[([^\]]*)\]\(_images/([^)]+)\)", repl, md)


col_html, col_md = st.columns(2, gap="xsmall")

with col_html:
    st.markdown(f"#### 原始筆記\n筆記標題：`{selected_title}`")
    if html_uri:
        raw_html = read_text_by_uri(html_uri)
        if raw_html:
            inner = _flatten_onenote_html(_replace_images_in_html(raw_html))
            st.iframe(_WHITE_FRAME.format(content=inner), height=620)
        else:
            # 有路徑但讀不到
            st.warning("找不到原始筆記。")
    else:
        st.info("此版本沒有記錄對應的筆記路徑。")

with col_md:
    st.markdown(f"#### LLM 擴寫增強生成後\n筆記標題：`{selected_title}`")
    if md_uri:
        raw_md = read_text_by_uri(md_uri)
        if raw_md:
            md_as_html = md_lib.markdown(_replace_images_in_md(raw_md), extensions=["fenced_code", "tables", "nl2br"])
            st.iframe(_WHITE_FRAME.format(content=md_as_html), height=620)
        else:
            # 有路徑但讀不到
            st.warning("找不到擴寫版。")
    else:
        # ── 觸發點二：生成失敗時才出現的重試按鈕，手動觸發 Silver ──
        attempted_err = st.session_state.enrich_attempted.get((page_id, dt))
        if attempted_err:
            st.error(f"此版本尚未生成 LLM 擴寫版：{attempted_err}")
            # 這顆按鈕不直接呼叫 Silver，只負責清掉 session 中的 enrich_attempted 後重跑整頁，
            # 讓自動觸發那段（本檔呼叫 _trigger("on_demand") 的 elif）的條件重新成立。
            # 對 Guest 更是無感，因爲他在自動觸發那段被就會被擋下，無法觸發生成按鈕。
            if st.button(
                "🔄 重試生成",
                key="vr_retry",
                disabled=is_guest,
                help="訪客身分無法觸發生成" if is_guest else None,
            ):
                st.session_state.enrich_attempted.pop((page_id, dt), None)
                st.rerun()
        else:
            st.info("此版本沒有記錄對應的筆記路徑。")


# ─────────────────────────────────────────
# 觸發點三：審查按鈕列（🔁 重試生成打 Silver；✅ 核可與 ❌ 退件打 Gold）
# 函式本體在上方「呼叫端點」區塊，這裡只決定按鈕的停用條件與擺放位置。
# ─────────────────────────────────────────
st.markdown("#### 針對語義增強筆記 (右側筆記)，請點選審核結果：", text_alignment="center")
# 行為要求：
# 打 Silver 的按鈕（重試生成）：Guest 一律停用，按不下去。
# 打 Gold 的按鈕（核可、退件）：Guest 按得下去，但只更新畫面做示意，不送出真實請求。

# Guest 已經按過核可或退件鈕時，為 True (但登出會清空 guest_reviewed，再登入仍可按核可或退件)
_guest_done = is_guest and (page_id, dt) in st.session_state.guest_reviewed

# Guest 已經按過核可或退件鈕、非 Guest 已將文件觸發過歸檔或退件、文件未先經過 Silver 生成 md
# 三者之一符合就要 disable Gold 服務按鈕
_gold_btns_disabled = (not md_uri) or is_version_archived or _guest_done

# 沒有 md、該版本已歸檔、或使用者是 Guest
# 三者之一符合就要 disable Silver 服務按鈕
_silver_btn_disabled = _gold_btns_disabled or is_guest


_, b1, b2, b3, _ = st.columns([1, 2, 2, 2, 1])

with b1:
    if st.button(
        "重試生成 (Regenerate)",
        icon="🔁",
        width="stretch",
        disabled=_silver_btn_disabled,
        help="訪客身分無法重試生成" if is_guest else None,
    ):
        _trigger("regenerate")

with b2:
    if st.button("核可 (Approve)", icon="✅", width="stretch", disabled=_gold_btns_disabled):
        _call_gold("approved")

with b3:
    if st.button("退件 (Reject)", icon="❌", width="stretch", disabled=_gold_btns_disabled):
        _call_gold("rejected")
