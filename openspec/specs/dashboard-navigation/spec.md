# dashboard-navigation Specification

## Purpose
規範 dashboard 側邊欄的頁面導覽連結與排列順序，讓使用者從任一頁面都能直接切換到 OneNote 審查頁與 AI 知識 Agent 頁。

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
