"""以 inline style + base64 SVG 畫出 Tech Stack 的 13 層技術堆疊卡片。

移植自 Figma 設計匯出的 React 元件，只保留 13 層 layer 卡片（不含流程軌/header/footer），
配色改為深色系。每個 logo 為自包含 SVG（JSX camelCase 屬性已轉為合法 HTML SVG），
渲染時以 base64 data URI 包進 <img>，這是因為 st.html 的 DOMPurify（USE_PROFILES html-only）
會剝除裸 <svg>，但允許 <img> 與 data: 圖片。整體組成單一 HTML 字串交由 st.html() 一次渲染，無外部資源依賴。

對外只暴露 render_tech_stack_diagram()，回傳完整 HTML 字串。
"""

import base64

# ruff: noqa: E501 — 本檔為 inline SVG 字串常數集合，長行不可折（折斷會改變 path 內容）。

# ─── SVG Logos（key → inline SVG，屬性轉為 HTML 合法寫法）──────────────────────
_SVG_OPEN = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none">'

LOGOS: dict[str, str] = {
    # Layer 1 — Frontend
    "streamlit": _SVG_OPEN
    + '<path d="M8 2L15 13H1L8 2Z" fill="#FF4B4B"/>'
    + '<path d="M8 6.5L12.5 13H3.5L8 6.5Z" fill="#FF4B4B" opacity="0.4"/></svg>',
    "plotly": _SVG_OPEN
    + '<rect x="1.5" y="10" width="3" height="5" rx="1" fill="#3D9BF0"/>'
    + '<rect x="6" y="6.5" width="3" height="8.5" rx="1" fill="#3D9BF0"/>'
    + '<rect x="10.5" y="2.5" width="3" height="12.5" rx="1" fill="#3D9BF0"/></svg>',
    "pandas": _SVG_OPEN
    + '<ellipse cx="5.5" cy="3.8" rx="2" ry="2.5" fill="#130754"/>'
    + '<ellipse cx="10.5" cy="3.8" rx="2" ry="2.5" fill="#E70488"/>'
    + '<rect x="4" y="5.5" width="3" height="7" rx="1.5" fill="#130754"/>'
    + '<rect x="9" y="5.5" width="3" height="7" rx="1.5" fill="#E70488"/>'
    + '<rect x="5.5" y="7" width="5" height="2.5" rx="1" fill="#9CA3AF"/></svg>',
    # Layer 2 — APIs & Backend
    "fastapi": _SVG_OPEN
    + '<path d="M6 1.5V6.5L2.5 12.5C2 13.6 2.9 15 5 15H11C13.1 15 14 13.6 13.5 12.5L10 6.5V1.5" stroke="#1F2937" stroke-width="1.4" stroke-linejoin="round" fill="none"/>'
    + '<line x1="5" y1="3.5" x2="11" y2="3.5" stroke="#1F2937" stroke-width="1.4"/>'
    + '<circle cx="5.5" cy="12" r="1.2" fill="#22C55E"/>'
    + '<circle cx="9.5" cy="11" r="0.9" fill="#22C55E"/></svg>',
    "github": _SVG_OPEN
    + '<path fill-rule="evenodd" clip-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" fill="#1F2937"/></svg>',
    "leetcode": _SVG_OPEN
    + '<path d="M9.5 3L5.5 8L9.5 13" stroke="#FFA116" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
    + '<path d="M3 6.5H8.5" stroke="#FFA116" stroke-width="1.5" stroke-linecap="round"/>'
    + '<path d="M3 9.5H13" stroke="#B0B0B0" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "microsoft": _SVG_OPEN
    + '<rect x="1" y="1" width="6.5" height="6.5" fill="#F25022"/>'
    + '<rect x="8.5" y="1" width="6.5" height="6.5" fill="#7FBA00"/>'
    + '<rect x="1" y="8.5" width="6.5" height="6.5" fill="#00A4EF"/>'
    + '<rect x="8.5" y="8.5" width="6.5" height="6.5" fill="#FFB900"/></svg>',
    "google": _SVG_OPEN
    + '<path d="M15.36 8.18c0-.57-.05-1.11-.14-1.64H8v3.1h4.3a3.67 3.67 0 01-1.59 2.41v2h2.58C14.48 12.66 15.36 10.61 15.36 8.18z" fill="#4285F4"/>'
    + '<path d="M8 16c2.16 0 3.97-.72 5.29-1.95l-2.58-2a4.8 4.8 0 01-2.71.76 4.79 4.79 0 01-4.5-3.31H.83v2.07A7.998 7.998 0 008 16z" fill="#34A853"/>'
    + '<path d="M3.5 9.5a4.86 4.86 0 010-3L.83 4.43a8 8 0 000 7.14L3.5 9.5z" fill="#FBBC05"/>'
    + '<path d="M8 3.21a4.33 4.33 0 013.06 1.2l2.3-2.3A7.68 7.68 0 008 0a8 8 0 00-7.17 4.43L3.5 6.5A4.77 4.77 0 018 3.21z" fill="#EA4335"/></svg>',
    "bs4": _SVG_OPEN
    + '<path d="M3 8.5C3 5.5 5 3.5 8 3.5C11 3.5 13 5.5 13 8.5" stroke="#E97316" stroke-width="1.5" fill="none" stroke-linecap="round"/>'
    + '<path d="M1.5 8.5H14.5L13.5 13.5C13.2 14.3 12.7 15 12 15H4C3.3 15 2.8 14.3 2.5 13.5L1.5 8.5Z" fill="#FED7AA" stroke="#E97316" stroke-width="1"/>'
    + '<circle cx="5.5" cy="11.5" r="1" fill="#E97316"/>'
    + '<circle cx="8" cy="12.2" r="1" fill="#F97316"/>'
    + '<circle cx="10.5" cy="11.5" r="1" fill="#EA580C"/></svg>',
    "requests": _SVG_OPEN
    + '<path d="M2.5 8H13.5" stroke="#3B82F6" stroke-width="2" stroke-linecap="round"/>'
    + '<path d="M10 4.5L13.5 8L10 11.5" stroke="#3B82F6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    # Layer 3 — Database & Storage
    "mongodb": _SVG_OPEN
    + '<path d="M8 1C8 1 4.5 5.5 4.5 9.5C4.5 11.43 6.07 13 8 13C9.93 13 11.5 11.43 11.5 9.5C11.5 5.5 8 1 8 1Z" fill="#00ED64"/>'
    + '<rect x="7.3" y="12.5" width="1.4" height="2.5" rx="0.7" fill="#00ED64"/></svg>',
    "gcs": _SVG_OPEN
    + '<path d="M5 12.5H3.5A3.5 3.5 0 013.5 5.5h.1A4 4 0 0112.2 6.5a3 3 0 01-.2 6H5Z" fill="#4285F4"/>'
    + '<path d="M5 12.5H3.5A3.5 3.5 0 013.5 5.5h.1A4 4 0 0112.2 6.5a3 3 0 01-.2 6H5Z" fill="white" opacity="0.2"/></svg>',
    "pymongo": _SVG_OPEN
    + '<path d="M8 2C6.5 2 5.5 3 5.5 4.5V7.5C5.5 8.33 4.83 9 4 9H3.5V10.5H4C4.83 10.5 5.5 11.17 5.5 12V14" stroke="#3776AB" stroke-width="1.5" fill="none" stroke-linecap="round"/>'
    + '<path d="M8 2C9.5 2 10.5 3 10.5 4.5V7.5C10.5 8.33 11.17 9 12 9H12.5V10.5H12C11.17 10.5 10.5 11.17 10.5 12V14" stroke="#FFD43B" stroke-width="1.5" fill="none" stroke-linecap="round"/>'
    + '<circle cx="8" cy="2.8" r="1" fill="#3776AB"/>'
    + '<circle cx="8" cy="13.2" r="1" fill="#FFD43B"/></svg>',
    # Layer 4 — Auth & Permissions
    "gcp_workload": _SVG_OPEN
    + '<path d="M8 1.5L14 5V11L8 14.5L2 11V5L8 1.5Z" stroke="#4285F4" stroke-width="1.4" fill="none"/>'
    + '<path d="M8 4.5L11.5 6.5V10.5L8 12.5L4.5 10.5V6.5L8 4.5Z" fill="#4285F4" opacity="0.25"/>'
    + '<circle cx="8" cy="8.5" r="1.5" fill="#4285F4"/></svg>',
    "gcp_sa": _SVG_OPEN
    + '<circle cx="8" cy="5.5" r="2.5" stroke="#34A853" stroke-width="1.4" fill="none"/>'
    + '<path d="M2.5 14.5C2.5 11.46 5 9 8 9C11 9 13.5 11.46 13.5 14.5" stroke="#34A853" stroke-width="1.4" fill="none" stroke-linecap="round"/>'
    + '<rect x="11" y="10" width="4" height="3" rx="0.8" fill="#34A853" opacity="0.3"/>'
    + '<path d="M12 10V9.2A1 1 0 0114 9.2V10" stroke="#34A853" stroke-width="1.2" fill="none"/></svg>',
    "msal": _SVG_OPEN
    + '<rect x="1" y="1" width="6.5" height="6.5" fill="#0078D4"/>'
    + '<rect x="8.5" y="1" width="6.5" height="6.5" fill="#0078D4" opacity="0.6"/>'
    + '<rect x="1" y="8.5" width="6.5" height="6.5" fill="#0078D4" opacity="0.6"/>'
    + '<rect x="8.5" y="8.5" width="6.5" height="6.5" fill="#0078D4" opacity="0.3"/>'
    + '<text x="3" y="11" font-size="5.5" fill="white" font-weight="700" font-family="DM Sans, sans-serif">Az</text></svg>',
    "google_oidc": _SVG_OPEN
    + '<path d="M15.36 8.18c0-.57-.05-1.11-.14-1.64H8v3.1h4.3a3.67 3.67 0 01-1.59 2.41v2h2.58C14.48 12.66 15.36 10.61 15.36 8.18z" fill="#4285F4"/>'
    + '<path d="M8 16c2.16 0 3.97-.72 5.29-1.95l-2.58-2a4.8 4.8 0 01-2.71.76 4.79 4.79 0 01-4.5-3.31H.83v2.07A7.998 7.998 0 008 16z" fill="#34A853"/>'
    + '<path d="M3.5 9.5a4.86 4.86 0 010-3L.83 4.43a8 8 0 000 7.14L3.5 9.5z" fill="#FBBC05"/>'
    + '<path d="M8 3.21a4.33 4.33 0 013.06 1.2l2.3-2.3A7.68 7.68 0 008 0a8 8 0 00-7.17 4.43L3.5 6.5A4.77 4.77 0 018 3.21z" fill="#EA4335"/></svg>',
    "github_pat": _SVG_OPEN
    + '<path fill-rule="evenodd" clip-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" fill="#1F2937"/></svg>',
    "streamlit_oidc": _SVG_OPEN
    + '<circle cx="8" cy="8" r="6.5" fill="#D97706" opacity="0.2" stroke="#D97706" stroke-width="1.4"/>'
    + '<circle cx="5.5" cy="6.5" r="1" fill="#D97706"/>'
    + '<circle cx="9.5" cy="5.5" r="0.8" fill="#D97706"/>'
    + '<circle cx="10.5" cy="9.5" r="1.1" fill="#D97706"/>'
    + '<circle cx="6.5" cy="10.5" r="0.8" fill="#D97706"/>'
    + '<circle cx="8" cy="8" r="0.7" fill="#D97706"/></svg>',
    # Layer 5 — Hosting & Deployment
    "cloud_run": _SVG_OPEN
    + '<path d="M3 10.5L8 3L13 10.5H3Z" fill="#4285F4" opacity="0.85"/>'
    + '<path d="M5.5 10.5L8 7L10.5 10.5H5.5Z" fill="white" opacity="0.6"/>'
    + '<rect x="5.5" y="10.5" width="5" height="2" rx="1" fill="#4285F4" opacity="0.5"/></svg>',
    "cloud_run_job": _SVG_OPEN
    + '<path d="M3 10.5L8 3L13 10.5H3Z" fill="#1A73E8" opacity="0.7"/>'
    + '<path d="M5.5 10.5L8 7L10.5 10.5H5.5Z" fill="white" opacity="0.5"/>'
    + '<rect x="5.5" y="10.5" width="5" height="2" rx="1" fill="#1A73E8" opacity="0.5"/>'
    + '<circle cx="12.5" cy="4.5" r="2.5" fill="#34A853"/>'
    + '<path d="M11.5 4.5L12.2 5.2L13.5 3.8" stroke="white" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "artifact_registry": _SVG_OPEN
    + '<rect x="2" y="2" width="12" height="12" rx="2" stroke="#EA4335" stroke-width="1.4" fill="none"/>'
    + '<rect x="4.5" y="5" width="7" height="1.5" rx="0.75" fill="#EA4335"/>'
    + '<rect x="4.5" y="7.5" width="5" height="1.5" rx="0.75" fill="#EA4335" opacity="0.6"/>'
    + '<rect x="4.5" y="10" width="6" height="1.5" rx="0.75" fill="#EA4335" opacity="0.35"/></svg>',
    "docker": _SVG_OPEN
    + '<rect x="1" y="7" width="2.5" height="2.5" rx="0.4" fill="#2496ED"/>'
    + '<rect x="4" y="7" width="2.5" height="2.5" rx="0.4" fill="#2496ED"/>'
    + '<rect x="7" y="7" width="2.5" height="2.5" rx="0.4" fill="#2496ED"/>'
    + '<rect x="4" y="4" width="2.5" height="2.5" rx="0.4" fill="#2496ED"/>'
    + '<rect x="7" y="4" width="2.5" height="2.5" rx="0.4" fill="#2496ED"/>'
    + '<path d="M13.5 8.5C13.5 8.5 12.8 8 11.5 8.2C11.3 7.2 10.6 6.5 9.7 6.3L9.5 6.2L9.4 6.5C9.1 7.3 9.2 8.3 9.7 9C9 9.3 8 9.3 7 9.3H1.5C1.5 10.5 2 11.5 2.9 12.2C3.8 12.9 5 13.3 6.3 13.3C9.8 13.3 12.5 11.7 13.8 9C13.8 9 14.2 9 14.5 8.7L13.5 8.5Z" fill="#2496ED"/></svg>',
    # Layer 6 — Cloud & Compute (AI/ML)
    "vertex_ai": _SVG_OPEN
    + '<path d="M8 1.5L10.5 6L15 6.5L11.5 10L12.5 14.5L8 12L3.5 14.5L4.5 10L1 6.5L5.5 6L8 1.5Z" fill="#1A73E8" opacity="0.2" stroke="#1A73E8" stroke-width="1.3" stroke-linejoin="round"/>'
    + '<circle cx="8" cy="8" r="2" fill="#1A73E8"/></svg>',
    "gemini_embed": _SVG_OPEN
    + '<path d="M8 2C8 2 10.5 5 10.5 8C10.5 11 8 14 8 14C8 14 5.5 11 5.5 8C5.5 5 8 2 8 2Z" fill="#1A73E8" opacity="0.3"/>'
    + '<path d="M2 8C2 8 5 10.5 8 10.5C11 10.5 14 8 14 8C14 8 11 5.5 8 5.5C5 5.5 2 8 2 8Z" fill="#1A73E8" opacity="0.3"/>'
    + '<circle cx="8" cy="8" r="2" fill="#1A73E8"/>'
    + '<text x="10.5" y="14" font-size="4.5" fill="#1A73E8" font-weight="700" font-family="DM Sans, sans-serif">1536</text></svg>',
    "cohere": _SVG_OPEN
    + '<circle cx="8" cy="8" r="6.5" stroke="#D97070" stroke-width="1.4" fill="none"/>'
    + '<circle cx="8" cy="8" r="3.5" fill="#D97070" opacity="0.25"/>'
    + '<circle cx="8" cy="8" r="1.5" fill="#D97070"/>'
    + '<circle cx="11" cy="5" r="1" fill="#D97070" opacity="0.7"/></svg>',
    "langchain": _SVG_OPEN
    + '<path d="M3 8C3 8 5 6 8 6C11 6 13 8 13 8" stroke="#1C3D5A" stroke-width="1.5" stroke-linecap="round" fill="none"/>'
    + '<path d="M3 8C3 8 5 10 8 10C11 10 13 8 13 8" stroke="#1C3D5A" stroke-width="1.5" stroke-linecap="round" fill="none"/>'
    + '<circle cx="3" cy="8" r="1.5" fill="#1C3D5A"/>'
    + '<circle cx="13" cy="8" r="1.5" fill="#1C3D5A"/>'
    + '<circle cx="8" cy="8" r="1.2" fill="#1C3D5A" opacity="0.4"/></svg>',
    # Layer 7 — CI/CD & Version Control
    "git": _SVG_OPEN
    + '<circle cx="12" cy="4" r="2" stroke="#F05032" stroke-width="1.4" fill="none"/>'
    + '<circle cx="4" cy="12" r="2" stroke="#F05032" stroke-width="1.4" fill="none"/>'
    + '<circle cx="12" cy="12" r="2" stroke="#F05032" stroke-width="1.4" fill="none"/>'
    + '<path d="M10 4H7C5.9 4 5 4.9 5 6V10" stroke="#F05032" stroke-width="1.4" stroke-linecap="round" fill="none"/>'
    + '<path d="M4 10V10" stroke="#F05032" stroke-width="1.4" stroke-linecap="round"/>'
    + '<path d="M10 12H6" stroke="#F05032" stroke-width="1.4" stroke-linecap="round"/></svg>',
    "github_actions": _SVG_OPEN
    + '<path fill-rule="evenodd" clip-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" fill="#2088FF"/>'
    + '<circle cx="10.5" cy="10.5" r="4" fill="white"/>'
    + '<circle cx="10.5" cy="10.5" r="3" fill="#2088FF" opacity="0.15" stroke="#2088FF" stroke-width="1"/>'
    + '<path d="M9.5 10.5L10.3 11.3L12 9.5" stroke="#2088FF" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "poetry": _SVG_OPEN
    + '<path d="M2 12L8 2L14 12H2Z" fill="#60A5FA" opacity="0.2" stroke="#3B82F6" stroke-width="1.4" stroke-linejoin="round"/>'
    + '<path d="M5 12L8 6.5L11 12H5Z" fill="#3B82F6" opacity="0.4"/>'
    + '<rect x="4" y="12" width="8" height="2" rx="1" fill="#3B82F6" opacity="0.5"/></svg>',
    "pyenv": _SVG_OPEN
    + '<path d="M8 2C6.5 2 5.5 3 5.5 4.5V7.5C5.5 8.33 4.83 9 4 9H3.5V10.5H4C4.83 10.5 5.5 11.17 5.5 12V13" stroke="#3776AB" stroke-width="1.5" fill="none" stroke-linecap="round"/>'
    + '<path d="M8 2C9.5 2 10.5 3 10.5 4.5V7.5C10.5 8.33 11.17 9 12 9H12.5V10.5H12C11.17 10.5 10.5 11.17 10.5 12V13" stroke="#FFD43B" stroke-width="1.5" fill="none" stroke-linecap="round"/>'
    + '<circle cx="8" cy="2.8" r="1" fill="#3776AB"/></svg>',
    "ruff": _SVG_OPEN
    + '<rect x="1.5" y="1.5" width="13" height="13" rx="3" fill="#D946EF" opacity="0.12" stroke="#D946EF" stroke-width="1.3"/>'
    + '<path d="M4.5 5H8C9.1 5 10 5.9 10 7C10 8.1 9.1 9 8 9H4.5V5Z" stroke="#D946EF" stroke-width="1.3" fill="none"/>'
    + '<path d="M7.5 9L10.5 12" stroke="#D946EF" stroke-width="1.3" stroke-linecap="round"/>'
    + '<path d="M11 5H12.5" stroke="#D946EF" stroke-width="1.3" stroke-linecap="round"/>'
    + '<path d="M11 7H12.5" stroke="#D946EF" stroke-width="1.3" stroke-linecap="round"/></svg>',
    # Layer 8 — Security
    "secret_manager": _SVG_OPEN
    + '<rect x="3" y="7" width="10" height="8" rx="2" fill="#E11D48" opacity="0.15" stroke="#E11D48" stroke-width="1.4"/>'
    + '<path d="M5.5 7V5.5A2.5 2.5 0 0110.5 5.5V7" stroke="#E11D48" stroke-width="1.4" stroke-linecap="round" fill="none"/>'
    + '<circle cx="8" cy="11" r="1.5" fill="#E11D48"/>'
    + '<rect x="7.4" y="11" width="1.2" height="2" rx="0.6" fill="#E11D48"/></svg>',
    "precommit": _SVG_OPEN
    + '<circle cx="8" cy="8" r="3" stroke="#BE185D" stroke-width="1.4" fill="none"/>'
    + '<circle cx="8" cy="8" r="1.2" fill="#BE185D"/>'
    + '<line x1="8" y1="1" x2="8" y2="4.5" stroke="#BE185D" stroke-width="1.4" stroke-linecap="round"/>'
    + '<line x1="8" y1="11.5" x2="8" y2="15" stroke="#BE185D" stroke-width="1.4" stroke-linecap="round"/>'
    + '<line x1="1" y1="8" x2="4.5" y2="8" stroke="#BE185D" stroke-width="1.4" stroke-linecap="round"/>'
    + '<line x1="11.5" y1="8" x2="15" y2="8" stroke="#BE185D" stroke-width="1.4" stroke-linecap="round"/></svg>',
    "claude_hooks": _SVG_OPEN
    + '<circle cx="8" cy="8" r="6.5" fill="#D97706" opacity="0.15" stroke="#D97706" stroke-width="1.4"/>'
    + '<path d="M5.5 10.5C5.5 8.5 6.5 7 8 7C9.5 7 10.5 8.5 10.5 10.5" stroke="#D97706" stroke-width="1.4" stroke-linecap="round" fill="none"/>'
    + '<circle cx="8" cy="5.5" r="1.5" fill="#D97706"/>'
    + '<path d="M6 10.5H10" stroke="#D97706" stroke-width="1.4" stroke-linecap="round"/></svg>',
    # Layer 9 — Rate Limiting & Flow Control
    "circuit_breaker": _SVG_OPEN
    + '<path d="M2 8H5.5" stroke="#84CC16" stroke-width="1.5" stroke-linecap="round"/>'
    + '<path d="M10.5 8H14" stroke="#84CC16" stroke-width="1.5" stroke-linecap="round"/>'
    + '<circle cx="8" cy="8" r="2.5" stroke="#84CC16" stroke-width="1.4" fill="none"/>'
    + '<path d="M5.5 6L5.5 8" stroke="#84CC16" stroke-width="1.5" stroke-linecap="round"/>'
    + '<path d="M6.5 5.5L9.5 5.5" stroke="#84CC16" stroke-width="1.2" stroke-linecap="round" opacity="0.5"/>'
    + '<circle cx="8" cy="8" r="1" fill="#84CC16" opacity="0.5"/>'
    + '<path d="M8 5.5V3" stroke="#84CC16" stroke-width="1.2" stroke-linecap="round" stroke-dasharray="1 1"/></svg>',
    "cdc_gate": _SVG_OPEN
    + '<rect x="2" y="3.5" width="12" height="9" rx="2" stroke="#84CC16" stroke-width="1.4" fill="none"/>'
    + '<path d="M5 8H7.5L8.5 6L9.5 10L10.5 8H11" stroke="#84CC16" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>'
    + '<circle cx="4" cy="6" r="0.8" fill="#84CC16" opacity="0.5"/>'
    + '<circle cx="4" cy="8" r="0.8" fill="#84CC16" opacity="0.7"/>'
    + '<circle cx="4" cy="10" r="0.8" fill="#84CC16"/></svg>',
    "lazy_load": _SVG_OPEN
    + '<circle cx="8" cy="8" r="6.5" stroke="#84CC16" stroke-width="1.4" fill="none" stroke-dasharray="3 1.5"/>'
    + '<path d="M8 4V8L10.5 10.5" stroke="#84CC16" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
    + '<circle cx="8" cy="8" r="1" fill="#84CC16"/></svg>',
    # Layer 10 — Caching
    "st_cache": _SVG_OPEN
    + '<path d="M8 2L15 13H1L8 2Z" fill="#FF4B4B" opacity="0.7"/>'
    + '<rect x="4.5" y="9" width="7" height="4.5" rx="1" fill="#0EA5E9" opacity="0.3"/>'
    + '<path d="M6 11.5H10M6 10.5H8.5" stroke="#0EA5E9" stroke-width="1.2" stroke-linecap="round"/></svg>',
    # Layer 11 — Scaling
    "microservice_split": _SVG_OPEN
    + '<rect x="1" y="5.5" width="5" height="5" rx="1.5" stroke="#64748B" stroke-width="1.3" fill="none"/>'
    + '<rect x="10" y="2" width="5" height="5" rx="1.5" stroke="#64748B" stroke-width="1.3" fill="none"/>'
    + '<rect x="10" y="9" width="5" height="5" rx="1.5" stroke="#64748B" stroke-width="1.3" fill="none"/>'
    + '<path d="M6 8H8L8 4.5H10" stroke="#64748B" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
    + '<path d="M8 8V11.5H10" stroke="#64748B" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>',
    # Layer 12 — Error Tracking & Logs
    "loguru": _SVG_OPEN
    + '<rect x="2" y="2" width="12" height="12" rx="2.5" fill="#D946EF" opacity="0.12" stroke="#D946EF" stroke-width="1.3"/>'
    + '<rect x="4" y="5" width="8" height="1.5" rx="0.75" fill="#D946EF" opacity="0.8"/>'
    + '<rect x="4" y="7.5" width="6" height="1.5" rx="0.75" fill="#D946EF" opacity="0.5"/>'
    + '<rect x="4" y="10" width="7" height="1.5" rx="0.75" fill="#D946EF" opacity="0.3"/>'
    + '<circle cx="12" cy="4" r="2.5" fill="#EF4444"/>'
    + '<text x="10.8" y="5.5" font-size="4.5" fill="white" font-weight="800" font-family="DM Sans, sans-serif">!</text></svg>',
    "onenote_mongo": _SVG_OPEN
    + '<rect x="1" y="2" width="9" height="12" rx="2" fill="#7B2FBE" opacity="0.2" stroke="#7B2FBE" stroke-width="1.3"/>'
    + '<text x="2.5" y="11" font-size="7" fill="#7B2FBE" font-weight="800" font-family="DM Sans, sans-serif">ON</text>'
    + '<path d="M11 1.5C11 1.5 9 5 9 7.5C9 9 9.9 10 11 10C12.1 10 13 9 13 7.5C13 5 11 1.5 11 1.5Z" fill="#00ED64"/>'
    + '<rect x="10.4" y="9.8" width="1.2" height="2" rx="0.6" fill="#00ED64"/></svg>',
    "multimodal_llm": _SVG_OPEN
    + '<path d="M8 1.5L10.5 6L15 6.5L11.5 10L12.5 14.5L8 12L3.5 14.5L4.5 10L1 6.5L5.5 6L8 1.5Z" fill="#D946EF" opacity="0.15" stroke="#D946EF" stroke-width="1.2" stroke-linejoin="round"/>'
    + '<path d="M8 8.5C8 8.5 9 7 9 6.5C9 7 9 8.5 11 8.5C9 8.5 9 10 9 10.5C9 10 8 8.5 8 8.5Z" fill="#D946EF" opacity="0.6"/>'
    + '<path d="M6 1.5C6 1.5 7 3 7 4C7 3 6 1.5 6 1.5Z" stroke="#00ED64" stroke-width="1" stroke-linecap="round"/>'
    + '<path d="M11 1.5C11 1.5 10.4 4 10.4 5.5C10.4 4 11 1.5 11 1.5Z" fill="#00ED64" opacity="0.7"/>'
    + '<rect x="10.5" y="9.5" width="1.2" height="2" rx="0.6" fill="#00ED64"/></svg>',
    # Layer 13 — Availability & Recovery
    "soft_delete": _SVG_OPEN
    + '<rect x="2" y="4" width="12" height="9" rx="2" stroke="#10B981" stroke-width="1.3" fill="none"/>'
    + '<path d="M5 8H11" stroke="#10B981" stroke-width="1.5" stroke-linecap="round"/>'
    + '<path d="M5 10.5H8.5" stroke="#10B981" stroke-width="1.2" stroke-linecap="round" opacity="0.5"/>'
    + '<rect x="4" y="7" width="8" height="3" rx="1" fill="#10B981" opacity="0.12"/>'
    + '<text x="3.5" y="6.5" font-size="3.5" fill="#10B981" font-weight="700" font-family="DM Sans, sans-serif">deleted</text></svg>',
    "partition": _SVG_OPEN
    + '<rect x="1.5" y="2" width="13" height="3.5" rx="1" stroke="#10B981" stroke-width="1.3" fill="none"/>'
    + '<rect x="1.5" y="6.5" width="13" height="3.5" rx="1" stroke="#10B981" stroke-width="1.3" fill="#10B981" opacity="0.12"/>'
    + '<rect x="1.5" y="11" width="13" height="3" rx="1" stroke="#10B981" stroke-width="1.3" fill="none" opacity="0.5"/>'
    + '<text x="3" y="5" font-size="4" fill="#10B981" font-weight="700" font-family="DM Sans, sans-serif">dt=v1</text>'
    + '<text x="3" y="9.5" font-size="4" fill="#10B981" font-weight="700" font-family="DM Sans, sans-serif">dt=v2</text></svg>',
    "medallion": _SVG_OPEN
    + '<circle cx="8" cy="8" r="6.5" stroke="#10B981" stroke-width="1.3" fill="none"/>'
    + '<circle cx="8" cy="8" r="4.5" stroke="#10B981" stroke-width="1" fill="none" opacity="0.5"/>'
    + '<circle cx="8" cy="8" r="2.5" fill="#10B981" opacity="0.3"/>'
    + '<text x="4.5" y="9" font-size="4" fill="#10B981" font-weight="800" font-family="DM Sans, sans-serif">B/S/G</text></svg>',
}


# ─── Layer 資料（比照 App.tsx 的 LAYERS）─────────────────────────────────────────
LAYERS: list[dict] = [
    {
        "num": "01",
        "category": "Frontend",
        "cardBg": "#EFF6FF",
        "pillBg": "#DBEAFE",
        "pillText": "#1E3A8A",
        "pillBorder": "#BFDBFE",
        "accent": "#3B82F6",
        "techs": [
            ("Streamlit", "streamlit"),
            ("Plotly", "plotly"),
            ("Pandas", "pandas"),
        ],
    },
    {
        "num": "02",
        "category": "APIs & Backend Logic",
        "cardBg": "#F0FDF4",
        "pillBg": "#DCFCE7",
        "pillText": "#14532D",
        "pillBorder": "#86EFAC",
        "accent": "#22C55E",
        "techs": [
            ("FastAPI", "fastapi"),
            ("GitHub REST API", "github"),
            ("LeetCode GraphQL API", "leetcode"),
            ("Microsoft Graph API", "microsoft"),
            ("Google Sheets API", "google"),
            ("BeautifulSoup4", "bs4"),
            ("Requests", "requests"),
        ],
    },
    {
        "num": "03",
        "category": "Database & Storage",
        "cardBg": "#FAF5FF",
        "pillBg": "#EDE9FE",
        "pillText": "#3B0764",
        "pillBorder": "#C4B5FD",
        "accent": "#8B5CF6",
        "techs": [
            ("MongoDB Atlas", "mongodb"),
            ("Google Cloud Storage (GCS)", "gcs"),
            ("PyMongo", "pymongo"),
        ],
    },
    {
        "num": "04",
        "category": "Auth & Permissions",
        "cardBg": "#FFF7ED",
        "pillBg": "#FFEDD5",
        "pillText": "#7C2D12",
        "pillBorder": "#FDBA74",
        "accent": "#F97316",
        "techs": [
            ("GCP Workload Identity Federation", "gcp_workload"),
            ("GCP Service Account", "gcp_sa"),
            ("MSAL (Azure OAuth)", "msal"),
            ("Google OIDC Provider", "google_oidc"),
            ("GitHub PAT", "github_pat"),
            ("Streamlit OIDC", "streamlit_oidc"),
        ],
    },
    {
        "num": "05",
        "category": "Hosting & Deployment",
        "cardBg": "#FFFBEB",
        "pillBg": "#FEF3C7",
        "pillText": "#78350F",
        "pillBorder": "#FCD34D",
        "accent": "#F59E0B",
        "techs": [
            ("Cloud Run Service", "cloud_run"),
            ("Cloud Run Job", "cloud_run_job"),
            ("GCP Artifact Registry", "artifact_registry"),
            ("Docker", "docker"),
        ],
    },
    {
        "num": "06",
        "category": "Cloud & Compute (AI/ML)",
        "cardBg": "#F0FDFA",
        "pillBg": "#CCFBF1",
        "pillText": "#134E4A",
        "pillBorder": "#5EEAD4",
        "accent": "#14B8A6",
        "techs": [
            ("GCP Agent Platform / Vertex AI", "vertex_ai"),
            ("gemini-flash series multimodal models", "gemini_embed"),
            ("gemini-embedding-2 model", "gemini_embed"),
            ("Cohere", "cohere"),
            ("LangChain Text Splitters", "langchain"),
        ],
    },
    {
        "num": "07",
        "category": "CI/CD & Version Control",
        "cardBg": "#EEF2FF",
        "pillBg": "#E0E7FF",
        "pillText": "#1E1B4B",
        "pillBorder": "#A5B4FC",
        "accent": "#6366F1",
        "techs": [
            ("Git", "git"),
            ("GitHub Actions", "github_actions"),
            ("Poetry", "poetry"),
            ("pyenv", "pyenv"),
            ("Ruff", "ruff"),
        ],
    },
    {
        "num": "08",
        "category": "Security",
        "cardBg": "#FFF1F2",
        "pillBg": "#FFE4E6",
        "pillText": "#881337",
        "pillBorder": "#FDA4AF",
        "accent": "#F43F5E",
        "techs": [
            ("GCP Secret Manager", "secret_manager"),
            ("pre-commit Hooks", "precommit"),
            ("CLAUDE code hooks", "claude_hooks"),
        ],
    },
    {
        "num": "09",
        "category": "Rate Limiting & Flow Control",
        "cardBg": "#F7FEE7",
        "pillBg": "#ECFCCB",
        "pillText": "#365314",
        "pillBorder": "#BEF264",
        "accent": "#84CC16",
        "techs": [
            ("Circuit Breaker for LLM calls", "circuit_breaker"),
            ("Incremental Load by CDC", "cdc_gate"),
            ("FastAPI-POST", "lazy_load"),
        ],
    },
    {
        "num": "10",
        "category": "Caching",
        "cardBg": "#F0F9FF",
        "pillBg": "#E0F2FE",
        "pillText": "#0C4A6E",
        "pillBorder": "#7DD3FC",
        "accent": "#0EA5E9",
        "techs": [
            ("st.cache_resource", "st_cache"),
        ],
    },
    {
        "num": "11",
        "category": "Scaling",
        "cardBg": "#F8FAFC",
        "pillBg": "#F1F5F9",
        "pillText": "#1E293B",
        "pillBorder": "#CBD5E1",
        "accent": "#64748B",
        "techs": [
            ("Cloud Run Microservice", "microservice_split"),
        ],
    },
    {
        "num": "12",
        "category": "Error Tracking & Logs",
        "cardBg": "#FDF4FF",
        "pillBg": "#FAE8FF",
        "pillText": "#701A75",
        "pillBorder": "#E879F9",
        "accent": "#D946EF",
        "techs": [
            ("Loguru", "loguru"),
            ("onenote_graph_api_logs (MongoDB)", "onenote_mongo"),
            ("multimodal_llm_enrichment_logs (MongoDB)", "multimodal_llm"),
        ],
    },
    {
        "num": "13",
        "category": "Availability & Recovery",
        "cardBg": "#ECFDF5",
        "pillBg": "#D1FAE5",
        "pillText": "#064E3B",
        "pillBorder": "#6EE7B7",
        "accent": "#10B981",
        "techs": [
            ("Soft Delete (status=deleted)", "soft_delete"),
            ("dt= Partition Multi-version", "partition"),
            ("Medallion Architecture (Bronze / Silver / Gold)", "medallion"),
        ],
    },
]


def _dark(accent: str) -> dict[str, str]:
    """依該層主色推導出深色主題下的一整組配色，涵蓋卡片底色、邊框與標籤樣式。

    卡片底色由主色疊上透明度得到暗色調，色碼末兩碼即為十六進位的透明度；
    文字統一使用淺灰，確保在深色底上維持足夠對比。

    Args:
        accent: 該層主色的十六進位色碼。

    Returns:
        含 card、border、pill_bg、pill_border、text 五個 CSS 色值的 dict。
    """
    return {
        "card": f"linear-gradient({accent}24,{accent}24),#30394f",
        "border": f"{accent}5c",
        "pill_bg": "#3d4660",
        "pill_border": "#586274",
        "text": "#F0F3F7",
    }


def _pill(name: str, logo_key: str, colors: dict[str, str]) -> str:
    """組出單一技術標籤的 HTML 字串，內容為 logo 圖示加上技術名稱。

    logo 以 base64 data URI 包進 img 標籤呈現。st.html 會用 DOMPurify 消毒 HTML，
    在僅允許 HTML 的設定下裸露的 svg 標籤會被剝除，img 標籤與 data 協定的圖片則允許通過，
    因此改走 img 標籤才能正常顯示。

    Args:
        name: 技術名稱，顯示在 logo 之後。
        logo_key: 對應 LOGOS 的鍵，查不到時 logo 留空。
        colors: 由 _dark 產出的深色配色 dict。

    Returns:
        單一技術標籤的 HTML 字串。
    """
    svg = LOGOS.get(logo_key, "")
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    img = f'<img src="data:image/svg+xml;base64,{b64}" width="16" height="16" style="display:block;"/>'
    return (
        '<div style="display:inline-flex;align-items:center;gap:7px;'
        f"background:{colors['pill_bg']};border:1.5px solid {colors['pill_border']};"
        "border-radius:999px;padding:1px 14px 1px 10px;font-size:14px;font-weight:500;"
        f'color:{colors["text"]};line-height:1;letter-spacing:-0.01em;white-space:nowrap;">'
        '<span style="display:flex;align-items:center;flex-shrink:0;line-height:0;">'
        f"{img}</span>{name}</div>"
    )


def _layer_card(layer: dict) -> str:
    """組出單一技術層卡片的 HTML，由左側色條、分類標籤欄與技術標籤區三塊組成。

    Args:
        layer: LAYERS 中的一個元素，需含 accent、num、category、techs 四個鍵。

    Returns:
        單一技術層卡片的 HTML 字串。
    """
    accent = layer["accent"]
    colors = _dark(accent)
    pills = "".join(_pill(n, k, colors) for n, k in layer["techs"])
    return (
        f'<div style="background:{colors["card"]};border-radius:18px;'
        f'border:1.5px solid {colors["border"]};display:flex;overflow:hidden;">'
        # 左側 accent 色條
        f'<div style="width:5px;background:{accent};flex-shrink:0;"></div>'
        # 標籤欄
        '<div style="width:196px;min-width:196px;padding:5px 24px 26px 20px;display:flex;'
        "flex-direction:column;justify-content:center;gap:1px;"
        f'border-right:1.5px solid {colors["border"]};">'
        f'<div style="font-size:10.5px;font-weight:700;letter-spacing:0.2em;'
        f'text-transform:uppercase;color:{accent};">Layer {layer["num"]}</div>'
        f'<div style="font-size:14.5px;font-weight:700;color:{colors["text"]};'
        f'line-height:1.3;letter-spacing:-0.02em;">{layer["category"]}</div></div>'
        # pills 區
        '<div style="flex:1;padding:5px 22px 5px 28px;display:flex;flex-wrap:wrap;gap:15px;'
        f'align-content:center;">{pills}</div></div>'
    )


def render_tech_stack_diagram() -> str:
    """組出整份技術堆疊圖的 HTML 字串，供 st.html 一次渲染。

    Returns:
        由 LAYERS 各層卡片依序堆疊而成的 HTML 字串，外層以垂直排列的 flex 容器包裹。
    """
    cards = "".join(_layer_card(layer) for layer in LAYERS)
    return (
        f'<div style="font-family:sans-serif;display:flex;flex-direction:column;gap:10px;padding:2px 0;">{cards}</div>'
    )
