"""以 Streamlit 的 `st.login()` 導向至符合標準OIDC 的 IdP，核查哪個帳號可登入後，再判斷登入者的角色。

執行流程：
1. 登出：
    - 主函式 render_logout_button 提供登出按鈕，按下後清空本頁自訂的 session_state 並呼叫 st.logout。
2. 登入：
    - 主函式 require_login 使用 callback 函式 render_review_login_page 或 render_agent_login_page，
      渲染登入畫面，callback 函式會再呼叫私有函式 _render_login_button，做出登入按鈕。
    - 主函式 require_login 接著檢查 st.user.is_logged_in，未登入就渲染登入入口並停止整頁渲染。
    - 私有函式 _resolve_role 讀環境變數 USER_ALLOWLIST，以登入者 email 查出他屬於哪個角色，查無則回 None。
    - 主函式 require_login 接收 _resolve_role 回傳值，
      回傳值是 None，則調用私有函式 _render_unauthorized_page 渲染未授權畫面並停止整頁渲染；
      回傳值 Not None (=有角色) 則把 email 與角色寫進 session_state 供頁面後續使用。
    - 私有函式 _render_unauthorized_page 也會調用 render_logout_button 渲染登出按鈕。

Required .env keys:
    USER_ALLOWLIST  JSON object mapping user email to role name; the Guest role must be listed
                    explicitly. Emails not listed are denied access to both pages.
"""

import json
import os
from collections.abc import Callable

import streamlit as st
from loguru import logger
from utils.ui_elements import color_map

GUEST_ROLE = "Guest"

# 對應 .streamlit/secrets.toml 的 [auth.google] 區塊名稱
_OIDC_PROVIDER = "google"


def _resolve_role(email: str) -> str | None:
    """以 email 對照環境變數 USER_ALLOWLIST 解析登入者是哪個角色，不在其中則無角色。

    Note:
        USER_ALLOWLIST 未設定、不是合法 JSON，或解析結果不是 JSON object 時，一律記一筆警告
        並回 None，連原本列在其中的人也一併拒絕。訪客要有 Guest 角色，必須在 USER_ALLOWLIST
        裡明寫成 Guest，這支函式不會在查無結果時補上任何預設角色。

    Args:
        email: 經 Google 驗證的登入者 email。

    Returns:
        USER_ALLOWLIST 中對應的角色名稱；email 不在其中，或 USER_ALLOWLIST 未設定、
        無法解析時回 None。
    """
    raw = os.getenv("USER_ALLOWLIST", "").strip()
    if not raw:
        logger.warning("[auth_gate] USER_ALLOWLIST 未設定，所有帳號一律拒絕進入")
        return None

    try:
        USER_ALLOWLIST = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"[auth_gate] USER_ALLOWLIST 不是合法 JSON，所有帳號一律拒絕進入：{e}")
        return None

    if not isinstance(USER_ALLOWLIST, dict):
        logger.warning("[auth_gate] USER_ALLOWLIST 必須是 JSON object，所有帳號一律拒絕進入")
        return None

    return USER_ALLOWLIST.get(email)


def _render_login_button(label: str = "使用 Google 帳號登入") -> None:
    """渲染登入按鈕，按下後導向 Google 登入頁。

    Note:
        這支刻意獨立出來，讓每個登入畫面自己決定按鈕擺在版面的哪個位置，例如放進登入卡片的欄位內。
        由 render_review_login_page 與 render_agent_login_page 各自在適當位置呼叫，
        require_login 未收到登入畫面的 callback 時也會直接呼叫它。

    Args:
        label: 按鈕文字。

    Returns:
        None: 只輸出畫面元件，不回傳值。
    """
    if st.button(label, width="stretch", type="primary"):
        st.login(provider=_OIDC_PROVIDER)


def require_login(render_login_page: Callable[[], None] | None = None) -> tuple[str, str]:
    """擋下未登入者與 USER_ALLOWLIST 外的帳號，兩關都通過才回傳 email 與角色。

    Note:
        這支函式連續把關兩次。第一關讀 st.user.is_logged_in，未登入者渲染登入畫面後中止。
        第二關把第一關取得的 email 交給 _resolve_role 對照 USER_ALLOWLIST，查不到角色者
        渲染未授權畫面後中止。兩關都通過才拿到角色，頁面也才繼續往下渲染。

        兩關都以 st.stop 中止整頁，呼叫這支函式的腳本的後續程式碼完全不會被執行，
        因此這支必須放在讀取 MongoDB 或呼叫任何 endpoint 之前。

        被第二關擋下的人仍保有 Streamlit 的登入狀態，要按未授權畫面上的登出按鈕才會登出。

    Args:
        render_login_page: 未登入時用來渲染整個登入畫面的 callback，不收參數也不回傳值，
            由這支函式在判定未登入後呼叫。該 callback 需自行呼叫 _render_login_button
            決定按鈕在版面上的位置。傳 None 則只渲染一顆按鈕。

    Returns:
        (email, role) tuple。email 來自 st.user，role 由 USER_ALLOWLIST 推導，必為其中登記的值。
    """
    if not st.user.is_logged_in:
        if render_login_page is not None:
            render_login_page()
        else:
            _render_login_button()
        st.stop()

    email = st.user.email or ""
    role = _resolve_role(email)
    if role is None:
        logger.warning(f"[auth_gate] {email} 不在 USER_ALLOWLIST 內，拒絕進入頁面")
        _render_unauthorized_page()
        st.stop()

    # 存入 session_state，只有關閉瀏覽器標籤頁或是點選 log out 才會清掉 role & email
    st.session_state.role = role
    st.session_state.user_email = email
    return email, role


def _render_unauthorized_page() -> None:
    """渲染登入成功但不在 USER_ALLOWLIST 內時的拒絕畫面，附一顆登出按鈕讓對方換帳號。

    Note:
        這支只負責畫面，中止渲染由呼叫端 require_login 以 st.stop 執行。
        被拒絕者的 email 不顯示在畫面上，要查是哪個帳號被擋下，看 require_login 記的那筆警告。

    Returns:
        None: 只輸出畫面元件，不回傳值。
    """
    _, body_col, _ = st.columns([1, 2, 1])
    with body_col:
        st.markdown(
            f"""
<div style="
    background: rgba(200,100,0,0.03);
    border: 1px solid #2a3550;
    border-radius: 16px;
    padding: 2rem 2rem 1.5rem;
    text-align: center;
">
    <div style="font-size:2.4rem; margin-bottom:0.6rem;">🚫</div>
    <p style="color:{color_map["ORANGE"]}; font-weight:700; font-size:1.05rem; margin:0 0 1rem 0;">
        此帳號未取得存取權限
    </p>
    <p style="color:{color_map["FONT_CLR"]}; font-size:0.86rem; line-height:1.7; margin:0;">
        這個帳號不在本平台的授權名單內。<br>
        本平台僅供授權名單內的 Google 帳號使用，需要存取權請與平台管理者聯繫。
    </p>
</div>
""",
            unsafe_allow_html=True,
        )
        render_logout_button()


def render_logout_button(*clear_keys: str) -> None:
    """渲染登出按鈕，按下後會觸發清理 `clear_keys` 指定的 session_state keys 並登出。

    Args:
        *clear_keys: 登出時要一併清掉的 session_state 鍵，例如頁面自己的暫存狀態。

    Returns:
        None: 只更新畫面與登入狀態，不回傳值。
    """
    if st.button("登出", width="stretch"):
        for key in (*clear_keys, "role", "user_email"):
            st.session_state.pop(key, None)
        st.logout()  # 只是對前端發出「清掉身分 cookie 並轉址」的指令，函式外層的接續程式碼還是會被執行到


def render_review_login_page() -> None:
    """渲染 OneNote 審查頁未登入時的 hero 版面、治理說明與登入卡片，登入按鈕置於卡片內。

    Returns:
        None: 只輸出畫面元件，不回傳值。
    """
    # ── Hero banner ──
    st.markdown(
        f"""
<div style="
    background: linear-gradient(135deg, #0f2040 50%, #0d1526 0%, #0f2040 50%, #1a1040 100%);
    border-radius: 16px;
    padding: 2rem 3rem;
    margin-bottom: 1.8rem;
    border: 1px solid #2a3550;
    text-align: center;
">
    <h1 style="color:{color_map["FONT_CLR"]}; font-size:2.2rem; font-weight:800;
        margin:0 0 0.6rem 0; line-height:1.1;">
        🧠 企業知識資料庫協作平台
    </h1>
    <p style="color:{color_map["TEAL"]}; font-size:1rem; margin:0; letter-spacing:0.5px; font-weight:500;">
        從日常工作筆記到企業智慧的關鍵一步
    </p>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── 引言（獨立一區，全寬）──
    st.markdown(
        f"""
<div style="color:{color_map["FONT_CLR"]}; line-height:1.85; font-size:0.95rem;">

<p style="color:{color_map["TEAL"]}; font-weight:700; font-size:1rem; margin:0 0 0.6rem 0;">
    這個頁面在做什麼？
</p>

<p>多數人在日常工作中會使用公司購買的企業版帳號，登入筆記簿來記載工作歷程、會議記錄、案例經驗，例如 Microsoft OneNote，
而這些經常蘊藏了部門歷經無數專案累積下來的珍貴實力之結晶，然而，
部分筆記軟體的存放文本與圖片的格式，並非對 AI 工具的模型友善，
<strong style="color:{color_map["ORANGE"]};">您或許不知道 OneNote 背後採用的是 HTML 標記式語言排版，
雖然對人類視覺上來說負擔較輕鬆，但對 AI 模型輸入時卻充滿「雜訊」。</strong>
直接倒入企業共用知識庫，讓模型去檢索時，可能產生誤解、遺漏甚至幻覺、雜訊也浪費上下文空間，推高組織的金錢成本。
或退一步來說，人類隨手記錄的文本也可能因為原始語意不全，而不適合直接餵給模型去檢索。<br><br>
<strong>—— 因此需要在整合 AI 工具、打破數據孤島前，透過一條穩健的數據管道來強壯您的資料，
不因資料的品質而衝擊未來對系統的信任度。</strong><br><br>
管道採用獎章架構（Medallion Architecture)，透過銅、銀、金三層：<br>
🥉 自動把筆記從 OneNote 萃取下來。<br>
🥈 擴寫語意，補強人類在忙碌之中來不及表達完善的上下文，讓原始資料要呈現的故事更健壯。<br>
<strong style="color:{color_map["ORANGE"]};">🏅 轉換為對模型負擔最小的的純文字結構 (Markdown)</strong>，
<strong>但 LLM 生成的內容不會直接進入企業知識庫，它必須先通過這裡的人工審核，核可後才會歸檔，
自動被引入企業檢索系統，成為系統背後的 Grounding Truth，
<strong style="color:{color_map["ORANGE"]};">以透明可見的 human-in-loop 協作，避免衍生對 AI 工具的不信任。</strong><br>
—— 這個頁面，就是負責把關的金牌閘門。</p>

</div>
""",
        unsafe_allow_html=True,
    )
    st.divider()
    # ── 兩欄：左下說明＋卡片 / 右下登入表單 ──
    content_col, form_col = st.columns([3, 2], gap="large")

    with content_col:
        st.markdown(
            f"""
<div style="color:{color_map["FONT_CLR"]}; line-height:1.85; font-size:0.95rem;">

<p style="color:{color_map["TEAL"]}; font-weight:700; font-size:1rem; margin:0 0 0.6rem 0;">
    登入後，您會做什麼？
</p>

<p>依序選擇 <strong>筆記本 → 章節 → 頁面</strong> 叫出待審筆記，左側是原始 OneNote 內容、右側是
LLM 擴寫後的版本，逐頁比對。滿意就點 <strong>核可（Approve）</strong> 送進知識庫；擴寫得不理想可點
<strong>重新生成（Regenerate）</strong> 讓模型再試一次（有次數上限）；內容不適合收錄則
<strong>退件（Reject）</strong>。同一頁的舊版本也可切換回看，方便追溯。</p>

<p style="color:{color_map["TEAL"]}; font-weight:700; font-size:1rem; margin-top:1.4rem;">
    審核時，建議守住這三條原則
</p>

<p>模型運算輸出高速，但不懂您部門的真實業務邏輯。與其擔心被 AI 取代，不如成為
<strong>「督導 AI 的決策者」</strong>—— 每次核可，都請對照以下三個眼光把關，這不只是形式，
而是知識庫品質與資訊安全的最後一道防線：</p>

</div>
""",
            unsafe_allow_html=True,
        )

        # 三個評估面向卡片
        c1, c2, c3 = st.columns(3)
        card_style = """
            border-radius:12px;
            padding:1rem 1rem 1.2rem;
            height:100%;
            border:1px solid {border};
            background:{bg};
        """
        with c1:
            st.markdown(
                f"""
<div style="{card_style.format(border=color_map["TEAL"], bg="rgba(0,212,200,0.07)")}">
    <div style="font-size:1.6rem; margin-bottom:0.4rem;">🎯</div>
    <div style="color:{color_map["TEAL"]}; font-weight:700; font-size:0.9rem; margin-bottom:0.5rem;">
        準確性 Accuracy
    </div>
    <div style="color:{color_map["FONT_CLR"]}; font-size:0.82rem; line-height:1.6;">
        AI 真的讀懂業務痛點了嗎？確認摘要是否精準捕捉核心重點，有無遺漏關鍵步驟或報錯邏輯。
    </div>
</div>
""",
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"""
<div style="{card_style.format(border=color_map["PURPLE"], bg="rgba(155,109,255,0.07)")}">
    <div style="font-size:1.6rem; margin-bottom:0.4rem;">⚖️</div>
    <div style="color:{color_map["PURPLE"]}; font-weight:700; font-size:0.9rem; margin-bottom:0.5rem;">
        可靠性 Reliability
    </div>
    <div style="color:{color_map["FONT_CLR"]}; font-size:0.82rem; line-height:1.6;">
        在雜訊中，AI 是否依然清醒？檢視它面對口語化文字與不完美輸入時，是否仍穩定輸出清晰結構。
    </div>
</div>
""",
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                f"""
<div style="{card_style.format(border=color_map["ORANGE"], bg="rgba(249,115,22,0.07)")}">
    <div style="font-size:1.6rem; margin-bottom:0.4rem;">🛡️</div>
    <div style="color:{color_map["ORANGE"]}; font-weight:700; font-size:0.9rem; margin-bottom:0.5rem;">
        隱私與資安 Privacy
    </div>
    <div style="color:{color_map["FONT_CLR"]}; font-size:0.82rem; line-height:1.6;">
        敏感資料是否被妥善阻擋？確認 AI 未外洩個資或客戶機密，且能防禦 Prompt Injection 攻擊。
    </div>
</div>
""",
                unsafe_allow_html=True,
            )

    with form_col:
        st.markdown(
            f"""
<div style="
    background: rgba(200,100,0,0.03);
    border: 1px solid #2a3550;
    border-radius: 16px;
    padding: 2rem 2rem 1.5rem;
">
    <p style="color:{color_map["TEAL"]}; font-weight:700; font-size:1rem; margin:0 0 1.2rem 0; text-align:center;">
        🔐 治理人員登入
    </p>
""",
            unsafe_allow_html=True,
        )

        _render_login_button()

        st.markdown(
            """
    <p style="color:#e0e8f8; font-size:0.78rem; text-align:center; margin-top:1rem;">
        此平台僅供被授權之 Google 帳號使用<br>登入即代表您同意以指定角色進行審核操作<br>
        未列入授權名單者無法進入本頁面
    </p>
</div>
""",
            unsafe_allow_html=True,
        )


def render_agent_login_page() -> None:
    """渲染 AI agent 頁未登入時的 hero 版面與登入卡片，登入按鈕置於卡片內。

    Returns:
        None: 只輸出畫面元件，不回傳值。
    """
    st.markdown(
        f"""
<div style="
    background: linear-gradient(135deg, #0f2040 50%, #0d1526 0%, #0f2040 50%, #1a1040 100%);
    border-radius: 16px;
    padding: 2rem 3rem;
    margin-bottom: 1.8rem;
    border: 1px solid #2a3550;
    text-align: center;
">
    <h1 style="color:{color_map["FONT_CLR"]}; font-size:2.2rem; margin:0 0 0.6rem 0; font-weight:800;">
        🤖 AI Knowledge Agent
    </h1>
    <p style="color:{color_map["TEAL"]}; font-size:1rem; margin:0; letter-spacing:1px;">
        筆記語意查詢 · 摘要
    </p>
</div>
""",
        unsafe_allow_html=True,
    )

    _, form_col, _ = st.columns([1, 2, 1])
    with form_col:
        st.markdown(
            f"""
<div style="
    background: rgba(200,100,0,0.03);
    border: 1px solid #2a3550;
    border-radius: 16px;
    padding: 2rem 2rem 1.5rem;
">
    <p style="color:{color_map["TEAL"]}; font-weight:700; font-size:1rem; margin:0 0 1.2rem 0; text-align:center;">
        🔐 授權人員登入
    </p>
""",
            unsafe_allow_html=True,
        )

        _render_login_button()

        st.markdown(
            """
    <p style="color:#e0e8f8; font-size:0.78rem; text-align:center; margin-top:1rem;">
        此平台僅供被授權之 Google 帳號使用<br>登入即代表您同意以指定角色進行操作<br>
        未列入授權名單者無法進入本頁面
    </p>
</div>
""",
            unsafe_allow_html=True,
        )
