"""以 Streamlit 的 `st.login()` 導向至符合標準OIDC 的 IdP，核查哪個帳號可登入後，再判斷登入者的角色。

執行流程：
1. 函式 resolve_role 讀環境變數 USER_ALLOWLIST，以登入者 email 查出他屬於哪個角色，查無則回 Guest。
2. 函式 require_login 檢查 st.user.is_logged_in，未登入就渲染登入入口並停止整頁渲染。
3. 已登入者取得 email 與角色，寫進 session_state 供頁面後續使用。
4. 函式 render_logout_button 提供登出按鈕，按下後清空本頁自訂的 session_state 並呼叫 st.logout。
5. 函式 render_review_login_page 與 render_agent_login_page 各自渲染兩個頁面的登入畫面，
   由頁面以 callback 交給 require_login 呼叫，登入按鈕位置由各自的版面決定。

Required .env keys:
    USER_ALLOWLIST  JSON object mapping user email to role name; emails not listed fall back to Guest.
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


def resolve_role(email: str) -> str:
    """以 email 對照環境變數 USER_ALLOWIST 解析登入者是哪個角色，若不在清單內一律視為訪客。

    Note:
        清單解析失敗時只記一筆警告並讓所有人落到 Guest，不中斷頁面。Guest 不會呼叫任何端點，
        因此這個保守作法不會造成未授權的寫入；真正的把關在 Silver 與 Gold 端點，
        它們各自驗證 token 並重新查一次清單。

    Args:
        email: 經 Google 驗證的登入者 email。

    Returns:
        清單中對應的角色名稱，查無或清單無法解析時回 Guest。
    """
    raw = os.getenv("USER_ALLOWLIST", "").strip()
    if not raw:
        return GUEST_ROLE

    try:
        allowlist = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"[auth_gate] USER_ALLOWLIST 不是合法 JSON，所有登入者一律視為 Guest：{e}")
        return GUEST_ROLE

    if not isinstance(allowlist, dict):
        logger.warning("[auth_gate] USER_ALLOWLIST 必須是 JSON object，所有登入者一律視為 Guest")
        return GUEST_ROLE

    return allowlist.get(email, GUEST_ROLE)


def render_login_button(label: str = "使用 Google 帳號登入") -> None:
    """渲染登入按鈕，按下後導向 Google 登入頁。

    Note:
        這支刻意獨立出來，讓各頁面自己決定按鈕擺在版面的哪個位置，例如放進登入卡片的欄位內。
        由 require_login 傳入的 render_login_page 負責在適當位置呼叫它。

    Args:
        label: 按鈕文字。

    Returns:
        None: 只輸出畫面元件，不回傳值。
    """
    if st.button(label, width="stretch", type="primary"):
        st.login(provider=_OIDC_PROVIDER)


def require_login(render_login_page: Callable[[], None] | None = None) -> tuple[str, str]:
    """擋下未登入者，已登入則進一步回傳 email 與角色。

    Note:
        未登入時以 `st.stop` 中止整頁，呼叫這支函式的腳本的後續程式碼完全不會被執行，
        因此這支必須放在讀取 MongoDB 或呼叫任何 endpoint 之前。

    Args:
        render_login_page: 未登入時用來渲染整個登入畫面的 callback，不收參數也不回傳值，
            由這支函式在判定未登入後呼叫。該 callback 需自行呼叫 render_login_button
            決定按鈕在版面上的位置。傳 None 則只渲染一顆按鈕。

    Returns:
        (email, role) tuple。email 來自 st.user，role 由 USER_ALLOWLIST 推導。
    """
    if not st.user.is_logged_in:
        if render_login_page is not None:
            render_login_page()
        else:
            render_login_button()
        st.stop()

    email = st.user.email or ""
    role = resolve_role(email)
    # 存入 session_state，只有關閉瀏覽器標籤頁或是點選 log out 才會清掉 role & email
    st.session_state.role = role
    st.session_state.user_email = email
    return email, role


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
        st.logout()


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

        render_login_button()

        st.markdown(
            """
    <p style="color:#e0e8f8; font-size:0.78rem; text-align:center; margin-top:1rem;">
        此平台僅供被授權之 Google 帳號使用<br>登入即代表您同意以指定角色進行審核操作<br>
        未列入授權名單者可以訪客身分瀏覽，審查操作不會寫入系統
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

        render_login_button()

        st.markdown(
            """
    <p style="color:#e0e8f8; font-size:0.78rem; text-align:center; margin-top:1rem;">
        此平台僅供被授權之 Google 帳號使用<br>登入即代表您同意以指定角色進行操作<br>
        未列入授權名單者可以訪客身分瀏覽
    </p>
</div>
""",
            unsafe_allow_html=True,
        )
