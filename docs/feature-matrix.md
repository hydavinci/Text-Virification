# 功能基线矩阵

## 审阅闭环

| Reference behavior | Current implementation | Status | Evidence |
|---|---|---|---|
| 原文按段落编辑并重新检查 | Immutable child version from persisted draft | Equivalent, stronger persistence | `test_versioned_review_lifecycle_preserves_history_and_export_parity`, `test_reanalysis_success_activates_new_version_and_consumes_draft`, `reviewEditing.spec.ts` edits/reanalysis tests |
| 版本历史与当前版本切换 | Version list with active version pointer and read-only historical selection | Equivalent, stronger persistence | `test_list_versions_returns_ordered_versions_and_active_version`, `keeps review loop controls continuously usable` |
| 历史版本原文、问题和决定可复现 | Version-scoped document, issue, summary, history, and derived reads | Equivalent | `test_versioned_review_lifecycle_preserves_history_and_export_parity`, `test_history_returns_batches_newest_first_without_crossing_versions` |
| 修改后预览 | Canonical derived-content service shared with export | Stronger replacement | `test_versioned_review_lifecycle_preserves_history_and_export_parity`, `test_derived_endpoint_returns_modified_blocks_and_diff_segments`, `test_derived_document_uses_stored_final_replacement_not_suggestion` |
| 字符级差异视图 | Myers diff from the same derived-content service | Equivalent | `test_derived_endpoint_returns_modified_blocks_and_diff_segments`, `reviewAccessibility.spec.ts` semantic diff test |
| 多候选建议 | Stored suggestion rows with legacy single-suggestion compatibility | Equivalent | `test_accepts_decision_with_selected_suggestion`, `reviewEditing.spec.ts` candidate-selection tests |
| 自定义最终替换 | Accepted decisions persist user-entered final replacement | Equivalent | `test_derived_document_uses_stored_final_replacement_not_suggestion`, `reviewEditing.spec.ts` custom replacement tests |
| 忽略问题 | Ignored decision state without replacement text | Equivalent | `test_versioned_review_lifecycle_preserves_history_and_export_parity`, `test_unreviewed_deletes_through_recorded_operation_and_can_be_undone` |
| 单项与批量撤销 | 10-second shortcut plus persistent operation history | Stronger replacement | `test_undo_deletes_decision_when_original_before_snapshot_was_absent`, `test_long_term_undo_has_no_deadline`, `reviewEditing.spec.ts` undo/history tests |
| 批量处理事务回滚 | Server-side decision batch with optimistic locks and atomic rollback | Stronger replacement | `test_stale_revision_rolls_back_valid_sibling`, `test_unreviewed_without_existing_decision_is_atomic_conflict` |
| 操作历史面板 | Version-scoped operation batches with persistent whole-batch undo | Stronger replacement | `test_history_returns_batches_newest_first_without_crossing_versions`, `keeps review loop controls continuously usable` |
| 正则与大小写查找 | Draft-only safe replacement with regex validation | Equivalent | `reviewEditing.spec.ts` find/replace regex and case-sensitive tests |
| 替换当前与全部替换 | Local draft mutation only, saved through draft revision API | Equivalent, stronger persistence | `reviewEditing.spec.ts` replace current/all tests, `test_stale_draft_update_returns_current_revision_and_preserves_text` |
| 键盘查找导航 | Enter and Shift+Enter move between loaded matches | Equivalent | `reviewEditing.spec.ts` keyboard find navigation tests |
| 重新检查进度和失败恢复 | Reanalysis SSE stream, idempotency key, preserved draft on failure | Stronger replacement | `test_reanalysis_route_is_idempotent_and_replays_version_events`, `test_reanalysis_failure_keeps_parent_active_and_draft_editable` |
| 预览与导出一致 | Export snapshot stores version and decision hash from derived content | Stronger replacement | `test_versioned_review_lifecycle_preserves_history_and_export_parity`, `test_create_export_snapshot_v2_records_requested_version_and_decision_hash` |
| C2 单屏紧凑布局 | Four-region desktop shell and bottom-navigation compact shell without page scroll | Equivalent, stronger layout | `keeps review loop controls continuously usable`, `keeps desktop geometry stable`, `keeps compact search controls horizontal and export dialog in bounds` |
| 触控和键盘可访问控件 | New controls use accessible names, focus handling, and 44px hit targets | Equivalent | `reviewAccessibility.spec.ts` touch-target/focus tests, `keeps review loop controls continuously usable` |

## 后续子项目（未完成）

| Reference behavior | Current implementation | Status | Evidence |
|---|---|---|---|
| 25 类规则对齐、检查开关、自定义术语和禁用词 | Deferred to rules/configuration subproject | Not completed in this subproject | `docs/superpowers/specs/2026-08-21-versioned-review-loop-design.md` §3.2 |
| DOC、RTF、Markdown、CSV 输入和高级格式导出 | Deferred to format/export subproject | Not completed in this subproject | `docs/superpowers/specs/2026-08-21-versioned-review-loop-design.md` §3.2 |
| 跨会话恢复、LLM 语义复核和词典热加载 | Deferred to continuity/intelligent-review subproject | Not completed in this subproject | `docs/superpowers/specs/2026-08-21-versioned-review-loop-design.md` §3.2 |
