## REMOVED Requirements

### Requirement: 多版本對照選擇
**Reason**: 併入 `onenote-review-page`——多版本審查不再是獨立頁，統一由合併後的 `onenote_review.py` 提供。
**Migration**: 使用 `onenote-review-page` 的「Three-level note selector」（含 `dt=` 多版本圓鈕）。

### Requirement: 左右對照渲染
**Reason**: 併入 `onenote-review-page`。
**Migration**: 使用 `onenote-review-page` 的「Side-by-side HTML and MD view」（gs:// URI 讀取）。

### Requirement: on-demand 觸發 Silver enrichment
**Reason**: 併入 `onenote-review-page`。
**Migration**: 使用 `onenote-review-page` 的「Side-by-side HTML and MD view」中 `md_path=null` 時的 on-demand 觸發。

### Requirement: 審查操作按鈕
**Reason**: 併入 `onenote-review-page`。
**Migration**: 使用 `onenote-review-page` 的「Approve and Reject buttons」（含 regenerate、approve/reject → Gold 端點）。
