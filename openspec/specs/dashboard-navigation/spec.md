# dashboard-navigation Specification

## Purpose
TBD - normalized from legacy archived delta format.

## Requirements

### Requirement: OneNote Review sidebar link
`_render_side_bar()` SHALL 在 `knowledge factory` 連結之後新增「OneNote Review」的 `st.sidebar.page_link`，指向 `pages/onenote_review.py`。

#### Scenario: Review link appears in sidebar
- **WHEN** 使用者在任意 dashboard 頁面查看側邊欄
- **THEN** 可見「🔍 OneNote Review」連結，點擊後跳轉至審核頁面

### Requirement: AI Knowledge Agent sidebar link
`_render_side_bar()` SHALL 在「OneNote Review」連結之後新增「🤖 AI Knowledge Agent」的 `st.sidebar.page_link`，指向 `pages/ai_knowledge_agent.py`。

#### Scenario: AI agent link appears in sidebar
- **WHEN** 使用者在任意 dashboard 頁面查看側邊欄
- **THEN** 可見「🤖 AI Knowledge Agent」連結，點擊後跳轉至 Page 3
