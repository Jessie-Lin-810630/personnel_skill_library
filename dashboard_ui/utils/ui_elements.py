"""Dashboard 的 UI 元件與繪圖樣式：集中 Plotly 配色、共用 layout 與可重用的版面元件。

提供全站共用的 color_map 與 Plotly 基礎 layout，以及側邊欄、任務下拉選單、任務表格、
雷達圖等可重用的 Streamlit 元件函式，供 app.py 與各頁組裝畫面。
"""

import textwrap

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from utils.precomputing import normalize_radar_label

# ─────────────────────────────────────────
# Plotly 色條
# ─────────────────────────────────────────
color_map = dict(
    BG="#0d1526",
    CARD_BG="#55575AD8",
    GRAY="#7a9cc0",
    GREEN="#1baf7a",
    RED="#e34948",
    TEAL="#00d4c8",
    PURPLE="#9b6dff",
    PINK="#ff6dbd",
    ORANGE="#f97316",
    WHITE="#ffffff",
    LIGHTBLUE="#90c2ff",
    SKYBLUE="#2f8fca",
    FONT_CLR="#e0e8f8",
)

plotly_layout_base = dict(
    paper_bgcolor="rgba(0,0,0,0)",  # 代表完全透明 (Alpha = 0)
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=color_map["FONT_CLR"], family="sans-serif"),
    margin=dict(l=10, r=10, t=30, b=10),
)

# ─────────────────────────────────────────
# UI 元件定義
# ─────────────────────────────────────────


def render_side_bar():
    """渲染自訂的側邊欄導覽列，逐一列出各頁的連結與圖示。

    需先在 .streamlit/config.toml 關閉 showSidebarNavigation 停用內建導覽，這裡的自訂版面才會生效。

    Returns:
        None: 直接寫入 Streamlit 側邊欄，不回傳值。
    """
    st.sidebar.page_link("app.py", label="HOME - About Author", icon="🏠")
    with st.sidebar:
        st.divider()
        st.caption("作品區 - OneNote 文件串接 RAG 知識庫系統")
        st.sidebar.page_link(
            "pages/onenote_review.py", label="RAG pretreatment - OneNote Notes Review System", icon="🔍"
        )
        st.sidebar.page_link(
            "pages/ingestion_data_quality.py", label="Pipeline Monitor - Data Ingestion Quality", icon="📦"
        )
        st.sidebar.page_link("pages/ai_knowledge_agent.py", label="AI - Query and Answering", icon="🤖")
        st.sidebar.page_link(
            "pages/retrieval_search_quality.py", label="Retrieval Monitor - Retrieval Quality", icon="🎯"
        )
        st.caption("了解更多此網站的架構")
        st.sidebar.page_link("pages/knowledge_factory.py", label="Chasing Great Data Engineering", icon="🏭")
    return None


def _wrap_hover_text(text: str, width=27):
    """把過長的 hover 文字依指定寬度斷行，讓 Plotly 的提示框不會超出圖表範圍。

    先把原有換行改成空格再統一重排，斷行處插入 HTML 換行標記，因 Plotly 提示框以 HTML 渲染。

    Args:
        text: 要顯示在提示框內的原始文字。
        width (int): 每行最多幾個字元，預設 27。

    Returns:
        str: 以 HTML 換行標記串接各行的文字。
    """
    text = str(text).replace("\n", " ")
    return "<br>".join(
        textwrap.wrap(
            str(text),
            width=width,
            break_long_words=True,
            replace_whitespace=False,
        )
    )


def _radar_axis_options(labels):
    """把雷達軸標籤正規化成下拉選單的選項清單。

    Args:
        labels (list[str]): 雷達圖上的原始軸向標籤，可能含有排版用的換行標記。

    Returns:
        list[str]: 正規化後的軸名清單，與圖表點擊事件回傳的軸名格式一致。
    """
    return [normalize_radar_label(label) for label in labels]


def _task_dataframe(axis_key, tasks_dict):
    """取出指定軸向的經手任務，包成任務表格可直接渲染的 DataFrame。

    Args:
        axis_key (str): 正規化後的軸名。
        tasks_dict (dict): 鍵為軸名、值為經手任務清單的對照表。

    Returns:
        pandas.DataFrame: 只有經手任務一欄的 DataFrame；該軸向沒有任務時回傳同欄位的空 DataFrame。
    """
    task_list = tasks_dict.get(axis_key, [])
    if not task_list:
        return pd.DataFrame(columns=["經手任務"])
    return pd.DataFrame({"經手任務": task_list})


def _selected_axis_from_event(event):
    """從 Plotly 圖表的點擊事件解析出使用者選中的軸向。

    Streamlit 不同版本回傳的事件物件，可能是具屬性的物件也可能是巢狀 dict，
    因此逐層取值時兩種形式都試一次。軸名優先取自綁在資料點上的 customdata，缺值時退而取 theta。

    Args:
        event: st.plotly_chart 回傳的選取事件，未發生點擊時為 None 或空值。

    Returns:
        str: 正規化後的軸名；沒有點擊或解析不到資料點時回傳空字串。
    """
    if not event:
        return ""
    selection = getattr(event, "selection", None)
    if selection is None and isinstance(event, dict):
        selection = event.get("selection", {})

    points = getattr(selection, "points", None)
    if points is None and isinstance(selection, dict):
        points = selection.get("points", [])
    if not points:
        return ""

    point = points[0]
    customdata = point.get("customdata") if isinstance(point, dict) else getattr(point, "customdata", "")
    theta = point.get("theta") if isinstance(point, dict) else getattr(point, "theta", "")
    return normalize_radar_label(customdata or theta)


def render_task_selectbox(labels, tasks_dict, chart_event, key_prefix):
    """渲染軸向下拉選單，並決定當前生效的軸向。

    圖表點擊與下拉選單兩種操作都能選軸，點擊結果優先；
    只有當點擊事件解析不到合法軸名時，才改用下拉選單的選擇值。

    Args:
        labels (list[str]): 雷達圖上的原始軸向標籤。
        tasks_dict (dict): 鍵為軸名、值為經手任務清單的對照表。
        chart_event: st.plotly_chart 回傳的選取事件。
        key_prefix (str): 元件 key 的前綴，用來區隔同一頁上的多張雷達圖。

    Returns:
        tuple: 當前生效的軸名與原樣傳回的任務對照表；兩種操作都沒有選擇時軸名為 None。
    """
    axis_options = _radar_axis_options(labels)
    selected_from_chart = _selected_axis_from_event(chart_event)

    fallback_axis = st.selectbox(
        "點擊下拉式選單決定軸向",
        options=axis_options,
        index=None,
        placeholder="點擊下拉式選單決定軸向",
        label_visibility="collapsed",
        key=f"{key_prefix}_axis_select",
    )
    selected_axis = selected_from_chart if selected_from_chart in axis_options else fallback_axis
    return selected_axis, tasks_dict


def render_task_table(selected_axis, tasks_dict):
    """在可收合的區塊內渲染指定軸向的經手任務表格。

    尚未選定軸向或該軸向沒有任務時，改顯示一則提示訊息，引導使用者先選軸。

    Args:
        selected_axis (str): 當前生效的軸名。
        tasks_dict (dict): 鍵為軸名、值為經手任務清單的對照表。

    Returns:
        None: 直接寫入 Streamlit 畫面，不回傳值。
    """
    task_df = _task_dataframe(selected_axis, tasks_dict)
    with st.expander("收合/展開", expanded=True, type="compact"):
        if task_df.empty:
            st.info("點擊上方的下拉式選單決定軸向")
        else:
            st.dataframe(
                task_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "經手任務": st.column_config.TextColumn(
                        "經手任務",
                        width="large",
                    )
                },
                row_height=80,
            )


def make_radar(labels, values, color, title, tasks_dict):
    """繪製一張技能雷達圖，並在滑鼠停留時顯示該軸向的經手任務筆數。

    Scatterpolar 需要首尾相接才能畫出封閉的多邊形，因此數值、標籤與提示文字都會把第一筆再補到最後。
    軸名同時寫進資料點的 customdata，讓點擊事件能回傳與下拉選單一致的軸名。

    Args:
        labels (list[str]): 雷達軸標籤，可含排版用的換行標記。
        values (list[float]): 各軸向的等級分數，順序需與標籤一一對應。
        color (str): 線條與填色的主色，需為 rgb 格式字串，填色會據此轉成半透明。
        title (str): 圖表標題。
        tasks_dict (dict): 鍵為正規化後的軸名、值為該軸向經手任務清單的對照表。

    Returns:
        plotly.graph_objects.Figure: 已套用全站配色與版面設定的雷達圖物件。
    """
    # 組合 hover 文字（每個軸向）
    hover_texts = []
    customdata = []
    for lbl in labels:
        axis_key = normalize_radar_label(lbl)
        customdata.append(axis_key)
        task_list = tasks_dict.get(axis_key, [])
        if task_list:
            hover_title = _wrap_hover_text(lbl.replace("<br>", " "), width=22)
            hover_texts.append(f"<b>{hover_title}</b><br>共 {len(task_list)} 項經手任務")
        else:
            hover_texts.append(lbl.replace("\n", " "))
    # 首尾閉合（Scatterpolar 需要）
    hover_texts_closed = hover_texts + [hover_texts[0]]
    customdata_closed = customdata + [customdata[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            mode="lines+markers",
            marker=dict(size=9, color=color),
            r=values + [values[0]],
            theta=labels + [labels[0]],
            fill="toself",
            fillcolor=color.replace(")", ", 0.25)").replace("rgb", "rgba"),
            line=dict(color=color, width=2.5),
            name=title,
            text=hover_texts_closed,
            customdata=customdata_closed,
            hovertemplate="%{text}<extra></extra>",
        )
    )
    radar_layout = {**plotly_layout_base, "margin": dict(l=70, r=70, t=30, b=20)}
    fig.update_layout(
        **radar_layout,
        title=dict(text=title, font=dict(size=15, color=color_map["FONT_CLR"]), x=0.5),
        polar=dict(
            domain=dict(x=[0.18, 0.82], y=[0.08, 0.95]),
            bgcolor="rgba(255,255,255,0.03)",
            radialaxis=dict(
                visible=True,
                range=[0, 5],
                tickvals=[1, 2, 3, 4, 5],
                ticktext=["Lv1", "Lv2", "Lv3", "Lv4", "Lv5"],
                tickfont=dict(size=10, color="#dfe1e6"),
                gridcolor="#dfe1e6",
                linecolor="#dfe1e6",
            ),
            angularaxis=dict(
                tickfont=dict(size=12, color=color_map["FONT_CLR"]),
                gridcolor="#dfe1e6",
                linecolor="#dfe1e6",
            ),
        ),
        hoverlabel=dict(
            bgcolor="#1a2235",
            bordercolor=color,
            font=dict(color="#e0e8f8", size=11),
            align="left",
        ),
        showlegend=False,
        height=400,
    )
    return fig
