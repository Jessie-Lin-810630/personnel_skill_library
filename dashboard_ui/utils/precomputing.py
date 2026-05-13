import streamlit as st
import pandas as pd


def _format_delta(value, suffix=""):
    return f"{value}{suffix}"


def _format_update_date(value):
    if value is None or pd.isna(value):
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _latest_date_from_df(df):
    for col in ["snapshot_date", "fetched_date", "fetched_at"]:
        if col in df.columns and not df[col].dropna().empty:
            return _format_update_date(df[col].dropna().iloc[0])
    return ""


def _show_updated_at(value):
    if value:
        st.caption(f"最近更新日期：{value}")


def _normalize_radar_label(label):
    return " ".join(str(label).replace("<br>", " ").split())


def _format_radar_label(label):
    label = str(label)
    if label == "製程技術 (細胞分注、反應器操作) 操作能力":
        return "製程技術<br>(細胞分注、反應器操作)<br>操作能力"
    elif label == "ETL/ELT pipeline 操作與維護":
        return "ETL/ELT pipeline <br>操作與維護"
    return label


def _radar_tasks_from_df(df: pd.DataFrame):
    tasks = {}
    for _, row in df.iterrows():
        axis = row.get("雷達軸")
        task = row.get("經手任務")
        if pd.isna(axis) or task is None:
            continue
        if not isinstance(task, list) and pd.isna(task):
            continue
        if isinstance(task, list):
            task_items = task
        else:
            task_items = [task]
        tasks.setdefault(_normalize_radar_label(axis), []).extend(
            str(item) for item in task_items if item
        )
    return tasks


def _github_repos_for_cards(repos):
    cards = []
    for repo in repos:
        cards.append({"name": repo.get("repo_name", ""),
                      "lang": repo.get("language") or "N/A",
                      "commits": repo.get("commit_counts", 0),
                      "pushed": str(repo.get("pushed_at", ""))[:10],
                      "readme_url": repo.get("readme_url") or "#",
                      })
    return cards


def _percent_to_counts(percent_by_topic, total, include=None, exclude=None):
    include = set(include or [])
    exclude = set(exclude or [])
    counts = {}
    for topic, percent in percent_by_topic.items():
        if include and topic not in include:
            continue
        if topic in exclude:
            continue
        count = round(float(percent) / 100 * total)
        if count > 0:
            counts[topic] = count
    return counts
