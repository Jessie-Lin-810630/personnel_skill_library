"""Dashboard 的資料預處理工具：把 MongoDB 查詢結果整理成繪圖前所需的格式。

集中日期格式化、雷達軸標籤正規化、百分比換算題數、GitHub 專案卡片整理等純函式，
供 app.py 與各頁在繪圖前呼叫，本身不涉及任何 I/O 或環境變數。
"""

import pandas as pd
import streamlit as st


def _format_delta(value, suffix=""):
    """把 KPI 卡的環比變化量接上單位字尾，轉成可直接顯示的字串。

    Args:
        value: 環比變化量，通常為 int 或 str。
        suffix (str): 接在數值後的單位字尾，例如 repos，預設為空字串。

    Returns:
        str: 數值與單位字尾串接後的字串。
    """
    return f"{value}{suffix}"


def _format_update_date(value):
    """把資料更新時間統一格式化成年月日字串。

    帶有 strftime 方法的時間物件依格式輸出，其餘型別一律取字串前十個字元，
    因來源欄位已是年月日開頭的時間字串。

    Args:
        value: 來源的時間值，可為 datetime、Timestamp、字串或 None。

    Returns:
        str: 年月日格式的日期字串；值為 None 或缺值時回傳空字串。
    """
    if value is None or pd.isna(value):
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _latest_date_from_df(df):
    """從 DataFrame 找出代表「最近更新日期」的欄位值。

    依序尋找 snapshot_date、fetched_date、fetched_at 三個欄位，取第一個有值的欄位的首列，
    因各 collection 記錄更新時間的欄位名稱不一致。

    Args:
        df (pandas.DataFrame): 已依時間由新到舊排序的查詢結果。

    Returns:
        str: 年月日格式的日期字串；三個欄位都沒有值時回傳空字串。
    """
    for col in ["snapshot_date", "fetched_date", "fetched_at"]:
        if col in df.columns and not df[col].dropna().empty:
            return _format_update_date(df[col].dropna().iloc[0])
    return ""


def _show_updated_at(value):
    """在畫面上以 caption 樣式顯示最近更新日期。

    值為空時不渲染任何元件，避免版面出現只有標籤沒有內容的空行。

    Args:
        value (str): 已格式化的日期字串。

    Returns:
        None: 直接寫入 Streamlit 畫面，不回傳值。
    """
    if value:
        st.caption(f"最近更新日期：{value}")


def normalize_radar_label(label):
    """把雷達軸標籤正規化成單行文字，做為跨元件比對用的鍵值。

    移除為了排版而插入的換行標記，並把連續空白收斂成單一空格，
    讓圖表點擊事件與下拉選單能以同一份標籤字串互相對應。

    Args:
        label: 原始雷達軸標籤，可能含有 HTML 換行標記。

    Returns:
        str: 單行、空白已收斂的標籤字串。
    """
    return " ".join(str(label).replace("<br>", " ").split())


def _format_radar_label(label):
    """把過長的雷達軸標籤插入換行標記，避免圖表邊緣的文字被截斷。

    只針對兩個已知過長的軸名做斷行，其餘標籤原樣回傳。

    Args:
        label: 原始雷達軸標籤。

    Returns:
        str: 已插入 HTML 換行標記的標籤字串，或原樣回傳的標籤字串。
    """
    label = str(label)
    if label == "製程技術 (細胞分注、反應器操作) 操作能力":
        return "製程技術<br>(細胞分注、反應器操作)<br>操作能力"
    elif label == "ETL/ELT pipeline 操作與維護":
        return "ETL/ELT pipeline <br>操作與維護"
    return label


def _radar_tasks_from_df(df: pd.DataFrame):
    """把雷達軸明細整理成「軸向對應經手任務清單」的字典，供圖表 hover 與任務表格取用。

    同一個軸向可能散落在多列，經手任務欄位可能是單一字串也可能是字串陣列，
    這裡一律攤平成字串清單並依正規化後的軸名合併。軸名或經手任務缺值的列直接略過。

    Args:
        df: 含雷達軸與經手任務兩個欄位的查詢結果。

    Returns:
        dict: 鍵為正規化後的軸名，值為該軸向的經手任務字串清單。
    """
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
        tasks.setdefault(normalize_radar_label(axis), []).extend(str(item) for item in task_items if item)
    return tasks


def _github_repos_for_cards(repos):
    """把 GitHub repo 查詢結果整理成專案卡片所需的欄位組合。

    只取卡片會顯示的欄位並補上預設值：語言缺值時顯示 N A，commit 數缺值時為 0，
    推送時間取年月日，README 連結缺值時指向錨點以免產生失效連結。

    Args:
        repos (list[dict]): github_repos collection 的查詢結果。

    Returns:
        list[dict]: 每筆含 name、lang、commits、pushed、readme_url 五個欄位。
    """
    cards = []
    for repo in repos:
        cards.append(
            {
                "name": repo.get("repo_name", ""),
                "lang": repo.get("language") or "N/A",
                "commits": repo.get("commit_counts", 0),
                "pushed": str(repo.get("pushed_at", ""))[:10],
                "readme_url": repo.get("readme_url") or "#",
            }
        )
    return cards


def _percent_to_counts(percent_by_topic, total, include=None, exclude=None):
    """把各主題的百分比佔比換算回題數，供 donut chart 顯示絕對數量。

    先套用白名單與黑名單篩掉不需要的主題，再以佔比乘上總題數四捨五入取整數，
    換算後為 0 的主題不納入結果，避免圖表出現無意義的零值扇形。

    Args:
        percent_by_topic (dict): 鍵為主題名稱，值為該主題佔全部題數的百分比。
        total (int): 該來源的總題數。
        include (list[str] | None): 白名單，只保留名單內的主題；預設不限制。
        exclude (list[str] | None): 黑名單，排除名單內的主題；預設不排除。

    Returns:
        dict: 鍵為主題名稱，值為換算後的題數，僅含題數大於 0 的主題。
    """
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
