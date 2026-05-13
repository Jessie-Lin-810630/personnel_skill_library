import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import textwrap
from utils.precomputing import (_normalize_radar_label)

# ─────────────────────────────────────────
# Plotly 色條
# ─────────────────────────────────────────
color_map = dict(BG="#0d1526",
                 CARD_BG="#55575AD8",
                 TEAL="#00d4c8",
                 PURPLE="#9b6dff",
                 PINK="#ff6dbd",
                 FONT_CLR="#e0e8f8",
                 ORANGE="#f97316",
                 WHITE="#ffffff",
                 LIGHTBLUE="#90c2ff")

plotly_layout_base = dict(
    paper_bgcolor="rgba(0,0,0,0)",  # 代表完全透明 (Alpha = 0)
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=color_map["FONT_CLR"], family="sans-serif"),
    margin=dict(l=10, r=10, t=30, b=10),
)

# ─────────────────────────────────────────
# UI 元件定義
# ─────────────────────────────────────────


def _render_side_bar():
    """Customize demonstrating style of the nevigation bar after switch off 
        `showSidebarNavigation` in .streamlit/config.toml.
    """
    st.sidebar.page_link("app.py", label="HOME", icon="🏠")
    st.sidebar.page_link("pages/knowledge_factory.py", label="knowledge factory", icon="🏭")
    return None


def _wrap_hover_text(text: str, width=27):
    """Wrap long hover lines so Plotly tooltip stays inside the chart area."""
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
    return [_normalize_radar_label(label) for label in labels]


def _task_dataframe(axis_key, tasks_dict):
    task_list = tasks_dict.get(axis_key, [])
    if not task_list:
        return pd.DataFrame(columns=["經手任務"])
    return pd.DataFrame({"經手任務": task_list})


def _selected_axis_from_event(event):
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
    return _normalize_radar_label(customdata or theta)


def _render_task_detail(title, labels, tasks_dict, chart_event, key_prefix):
    axis_options = _radar_axis_options(labels)
    selected_from_chart = _selected_axis_from_event(chart_event)
    default_axis = selected_from_chart if selected_from_chart in axis_options else axis_options[0]

    st.markdown(f"##### {title}")
    fallback_axis = st.selectbox(
        "點擊下拉式選單決定軸向：",
        options=axis_options,
        index=axis_options.index(default_axis),
        key=f"{key_prefix}_axis_select",
    )
    selected_axis = selected_from_chart if selected_from_chart in axis_options else fallback_axis
    task_df = _task_dataframe(selected_axis, tasks_dict)
    st.dataframe(
        task_df,
        use_container_width=True,
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
    """
    tasks_dict: { label_str: [task1, task2, ...] }
    Hover tooltip 顯示該軸向的代表任務清單。
    """
    # 組合 hover 文字（每個軸向）
    hover_texts = []
    customdata = []
    for lbl in labels:
        axis_key = _normalize_radar_label(lbl)
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
    fig.add_trace(go.Scatterpolar(
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
    ))
    radar_layout = {**plotly_layout_base, "margin": dict(l=70, r=70, t=30, b=20)}
    fig.update_layout(
        **radar_layout,
        title=dict(text=title, font=dict(size=15, color=color_map["FONT_CLR"]), x=0.5),
        polar=dict(
            domain=dict(x=[0.18, 0.82], y=[0.08, 0.95]),
            bgcolor="rgba(255,255,255,0.03)",
            radialaxis=dict(
                visible=True, range=[0, 5],
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
