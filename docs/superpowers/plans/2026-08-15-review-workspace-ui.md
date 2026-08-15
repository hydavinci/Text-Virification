# Review Workspace UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Vue application from upload/progress into a responsive three-column document review workspace with filtering, decisions, batch actions, and exports.

**Architecture:** A route-level workspace state composable coordinates typed API clients. Focused components render navigation, virtualized document blocks, issue cards, and export state; server data remains authoritative and optimistic decisions roll back on conflict.

**Tech Stack:** Vue 3.5, TypeScript 5.7, Vite 6, Vitest 3, Vue Test Utils, native CSS.

**Spec:** `docs/superpowers/specs/2026-08-15-document-review-workspace-design.md`

## Global Constraints

- Requires the core analysis, issue review, and export plans.
- The interface is consistently Simplified Chinese.
- Desktop uses the approved document-centered three-column layout.
- Narrow screens use “文档 / 问题” tabs instead of compressed columns.
- Severity is communicated by text and icon as well as color.
- All controls are keyboard accessible and preserve visible focus.
- Long documents load/render by block page; the app never renders the full document eagerly.
- No UI framework dependency is added.

---

### Task 1: Typed analysis, decision, and export API clients

**Files:**
- Modify: `apps/web/src/types/jobs.ts`
- Create: `apps/web/src/types/analysis.ts`
- Create: `apps/web/src/types/exports.ts`
- Modify: `apps/web/src/api/jobs.ts`
- Create: `apps/web/src/api/analysis.ts`
- Create: `apps/web/src/api/exports.ts`
- Modify: `apps/web/src/main.ts`
- Create: `apps/web/tests/analysisApi.spec.ts`
- Create: `apps/web/tests/exportsApi.spec.ts`

**Interfaces:**
- Produces: `AnalysisApi.getDocumentPage`, `getIssues`, `getSummary`, `putDecisions`.
- Produces: `ExportsApi.create`, `get`, `downloadUrl`.
- Extends: `JobsApi.createJob(file, options)`.

- [ ] **Step 1: Write failing upload-options and issue-query tests**

```ts
it('posts scenario and enabled categories with the upload', async () => {
  const fetchMock = vi.fn().mockResolvedValue(okJobResponse())
  const api = createJobsApi({ fetch: fetchMock })
  await api.createJob(file, {
    scenario: 'legal',
    enabledCategories: ['character', 'security']
  })
  const body = fetchMock.mock.calls[0][1].body as FormData
  expect(body.get('scenario')).toBe('legal')
  expect(body.getAll('enabled_categories')).toEqual(['character', 'security'])
})


it('encodes issue filters and cursor', async () => {
  const fetchMock = vi.fn().mockResolvedValue(okIssuePageResponse())
  await createAnalysisApi({ fetch: fetchMock }).getIssues('job-1', {
    category: 'security',
    decision: 'unreviewed',
    cursor: 'next',
    limit: 50
  })
  expect(fetchMock).toHaveBeenCalledWith(
    '/api/v1/jobs/job-1/issues?category=security&decision=unreviewed&cursor=next&limit=50'
  )
})
```

- [ ] **Step 2: Write failing decision and export tests**

```ts
it('returns every decision outcome', async () => {
  const api = createAnalysisApi({ fetch: vi.fn().mockResolvedValue(okMixedDecisionResponse()) })
  const result = await api.putDecisions('job-1', [acceptedDecision, staleDecision])
  expect(result.outcomes.map((item) => item.status)).toEqual(['applied', 'conflict'])
})


it('builds a same-origin export download URL', () => {
  expect(createExportsApi().downloadUrl('job 1', 'export/1')).toBe(
    '/api/v1/jobs/job%201/exports/export%2F1/download'
  )
})
```

- [ ] **Step 3: Run API tests and verify RED**

Run:

```powershell
Set-Location apps\web
npm test -- --run tests/analysisApi.spec.ts tests/exportsApi.spec.ts tests/jobsApi.spec.ts
```

Expected: FAIL because clients and option signatures are absent.

- [ ] **Step 4: Define exact wire types**

Create unions for scenario, category, severity, decision action/status, export type/status. Mirror every backend response field; do not use partial response mocks. Use a shared `requestJson` helper that binds `fetch` to `globalThis`, preserves structured backend errors, and validates `response.ok`.

- [ ] **Step 5: Implement clients and Vue injection keys**

Use `URLSearchParams` for filters. `putDecisions` sends at most 500 items. Register jobs, analysis, and exports clients in `main.ts`.

- [ ] **Step 6: Run API tests and build**

Run:

```powershell
npm test -- --run tests/analysisApi.spec.ts tests/exportsApi.spec.ts tests/jobsApi.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
Set-Location ..\..
git add apps\web\src\types apps\web\src\api apps\web\src\main.ts apps\web\tests
git commit -m "feat: add typed review workspace clients" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Upload scenarios and checker category settings

**Files:**
- Create: `apps/web/src/components/CheckOptions.vue`
- Modify: `apps/web/src/components/UploadWorkspace.vue`
- Modify: `apps/web/src/views/WorkspaceView.vue`
- Modify: `apps/web/tests/WorkspaceView.spec.ts`

**Interfaces:**
- Produces: `upload: [file: File, options: CheckOptions]`.
- Consumes: six fixed scenarios and six fixed categories.

- [ ] **Step 1: Write failing option-selection test**

```ts
it('uploads with the selected scenario and categories', async () => {
  const wrapper = mountWorkspace()
  await wrapper.get('[aria-label="使用场景"]').setValue('legal')
  await wrapper.get('[name="category-discourse"]').setValue(false)
  await selectFile(wrapper, textFile)
  await flushPromises()
  expect(createJob).toHaveBeenCalledWith(textFile, {
    scenario: 'legal',
    enabledCategories: [
      'character',
      'vocabulary',
      'sentence',
      'format',
      'security'
    ]
  })
})
```

- [ ] **Step 2: Write failing zero-category validation test**

```ts
it('requires at least one check category', async () => {
  const wrapper = mountWorkspace()
  for (const input of wrapper.findAll('[name^="category-"]')) {
    await input.setValue(false)
  }
  await selectFile(wrapper, textFile)
  expect(createJob).not.toHaveBeenCalled()
  expect(wrapper.get('[role="alert"]').text()).toContain('至少选择一类检查')
})
```

- [ ] **Step 3: Run component tests and verify RED**

Run:

```powershell
npm test -- --run tests/WorkspaceView.spec.ts
```

Expected: FAIL because option controls and upload payload are absent.

- [ ] **Step 4: Implement `CheckOptions.vue`**

Render a labeled scenario select and six checkbox cards. Default to `general` and all categories. Display “共享规则由管理员维护” without exposing filesystem paths.

- [ ] **Step 5: Connect options to upload**

`UploadWorkspace` owns validation and emits an immutable options object. Preserve drag/drop, 25 MiB validation, busy state, and native file-input keyboard operation.

- [ ] **Step 6: Run component tests and commit**

Run:

```powershell
npm test -- --run tests/WorkspaceView.spec.ts
```

Expected: PASS.

```powershell
Set-Location ..\..
git add apps\web\src\components\CheckOptions.vue apps\web\src\components\UploadWorkspace.vue apps\web\src\views\WorkspaceView.vue apps\web\tests\WorkspaceView.spec.ts
git commit -m "feat: configure document checks before upload" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Review workspace state and three-column shell

**Files:**
- Create: `apps/web/src/composables/useReviewWorkspace.ts`
- Create: `apps/web/src/views/ReviewWorkspaceView.vue`
- Create: `apps/web/src/components/review/ReviewToolbar.vue`
- Create: `apps/web/src/components/review/ReviewNavigation.vue`
- Create: `apps/web/src/components/review/DocumentViewer.vue`
- Create: `apps/web/src/components/review/IssuePanel.vue`
- Modify: `apps/web/src/views/WorkspaceView.vue`
- Create: `apps/web/tests/ReviewWorkspace.spec.ts`

**Interfaces:**
- Produces: `useReviewWorkspace(jobId)` with summary, filters, blocks, issues, selected issue, page cursors, loading, and error.
- Produces synchronized `selectIssue(issueId)` and `selectHighlight(issueId)`.

- [ ] **Step 1: Write failing completed-job transition test**

```ts
it('opens the review workspace after analysis completes', async () => {
  const wrapper = mountWorkspaceWithCompletedEvent()
  await uploadAndComplete(wrapper)
  expect(wrapper.get('[aria-label="文档审阅工作台"]').exists()).toBe(true)
  expect(getDocumentPage).toHaveBeenCalledWith(jobId, { cursor: null, limit: 100 })
  expect(getIssues).toHaveBeenCalledWith(jobId, expect.objectContaining({ limit: 50 }))
})
```

- [ ] **Step 2: Write failing layout and synchronization test**

```ts
it('selecting an issue highlights and scrolls its document block', async () => {
  const wrapper = mountReviewWorkspace()
  await wrapper.get('[data-issue-id="issue-2"]').trigger('click')
  expect(wrapper.get('[data-block-id="p-2"]').classes()).toContain('document-block--active')
  expect(wrapper.get('[data-highlight-issue-id="issue-2"]').attributes('aria-current')).toBe('true')
})
```

- [ ] **Step 3: Run review tests and verify RED**

Run:

```powershell
npm test -- --run tests/ReviewWorkspace.spec.ts tests/WorkspaceView.spec.ts
```

Expected: FAIL because review components and state are absent.

- [ ] **Step 4: Implement state composable**

Load summary, first block page, and first issue page in parallel. Use request generations so stale filter/page responses cannot replace newer state. Store blocks by ID and issues by ID plus ordered arrays. Expose explicit retry methods; do not silently replace failed calls with empty data.

- [ ] **Step 5: Implement semantic three-column shell**

Use `<nav aria-label="问题筛选">`, `<article aria-label="文档内容">`, and `<aside aria-label="问题详情">`. Render issue highlights by splitting block strings with a code-point-safe helper:

```ts
const points = Array.from(block.text)
return {
  before: points.slice(0, issue.start).join(''),
  match: points.slice(issue.start, issue.end).join(''),
  after: points.slice(issue.end).join('')
}
```

- [ ] **Step 6: Add paged block loading**

Use an IntersectionObserver sentinel to request the next block cursor. In tests, inject an observer factory and trigger it explicitly. Keep only server-loaded pages; do not fetch all pages recursively.

- [ ] **Step 7: Run tests and commit**

Run:

```powershell
npm test -- --run tests/ReviewWorkspace.spec.ts tests/WorkspaceView.spec.ts
```

Expected: PASS.

```powershell
Set-Location ..\..
git add apps\web\src\composables apps\web\src\views apps\web\src\components\review apps\web\tests
git commit -m "feat: add three-column document review workspace" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Filters, single decisions, custom replacements, and conflicts

**Files:**
- Modify: `apps/web/src/composables/useReviewWorkspace.ts`
- Modify: `apps/web/src/components/review/ReviewNavigation.vue`
- Modify: `apps/web/src/components/review/IssuePanel.vue`
- Modify: `apps/web/src/components/review/DocumentViewer.vue`
- Modify: `apps/web/tests/ReviewWorkspace.spec.ts`

**Interfaces:**
- Produces filter updates by category, severity, decision, and search.
- Produces `decide(issue, action, replacement?)`.

- [ ] **Step 1: Write failing filter race test**

```ts
it('keeps the newest issue filter response', async () => {
  const first = deferred<IssuePage>()
  const second = deferred<IssuePage>()
  getIssues.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
  const wrapper = mountReviewWorkspace()
  await setFilter(wrapper, 'category', 'security')
  await setFilter(wrapper, 'category', 'format')
  second.resolve(formatIssues)
  await flushPromises()
  first.resolve(securityIssues)
  await flushPromises()
  expect(wrapper.text()).toContain('格式规范')
  expect(wrapper.text()).not.toContain('敏感内容')
})
```

- [ ] **Step 2: Write failing custom and conflict tests**

```ts
it('saves a custom replacement and previews it', async () => {
  const wrapper = mountReviewWorkspace()
  await wrapper.get('[aria-label="自定义替换"]').setValue('专业')
  await wrapper.get('button[name="custom-decision"]').trigger('click')
  expect(putDecisions).toHaveBeenCalledWith(jobId, [
    expect.objectContaining({ action: 'custom', replacement: '专业' })
  ])
  expect(wrapper.get('[data-highlight-issue-id="issue-1"]').text()).toBe('专业')
})


it('restores server state and announces a stale decision conflict', async () => {
  putDecisions.mockResolvedValue(conflictOutcome)
  const wrapper = mountReviewWorkspace()
  await wrapper.get('button[name="accept"]').trigger('click')
  expect(wrapper.get('[role="alert"]').text()).toContain('结果已更新，请重新确认')
  expect(getIssues).toHaveBeenCalledTimes(2)
})
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
npm test -- --run tests/ReviewWorkspace.spec.ts
```

Expected: FAIL because filter/decision controls are absent.

- [ ] **Step 4: Implement debounced search and immediate categorical filters**

Debounce keyword search by 250 ms; category, severity, and decision filters apply immediately. Every filter change resets issue cursor and selection, then loads page one.

- [ ] **Step 5: Implement optimistic decisions with rollback**

Update the local issue decision immediately, call `putDecisions`, retain on `applied`, and reload affected page/summary on `conflict` or `invalid`. Announce the outcome through an `aria-live="polite"` region; infrastructure failures use `role="alert"` and retain a retry action.

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
npm test -- --run tests/ReviewWorkspace.spec.ts
```

Expected: PASS.

```powershell
Set-Location ..\..
git add apps\web\src\composables\useReviewWorkspace.ts apps\web\src\components\review apps\web\tests\ReviewWorkspace.spec.ts
git commit -m "feat: review and filter document issues" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 5: Batch decisions and find/replace

**Files:**
- Create: `apps/web/src/components/review/BatchActions.vue`
- Create: `apps/web/src/components/review/FindReplace.vue`
- Modify: `apps/web/src/composables/useReviewWorkspace.ts`
- Modify: `apps/web/src/components/review/ReviewToolbar.vue`
- Modify: `apps/web/tests/ReviewWorkspace.spec.ts`

**Interfaces:**
- Produces: `decideVisible(action)` for the current filtered page.
- Produces local find navigation and server-backed custom decision creation for matched issues only.

- [ ] **Step 1: Write failing mixed batch outcome test**

```ts
it('applies successful batch items and marks conflicts', async () => {
  putDecisions.mockResolvedValue({
    outcomes: [
      { issueId: 'issue-1', status: 'applied', decision: accepted },
      { issueId: 'issue-2', status: 'conflict', code: 'stale_issue_version' }
    ]
  })
  const wrapper = mountReviewWorkspace()
  await wrapper.get('button[name="accept-visible"]').trigger('click')
  expect(wrapper.get('[data-issue-id="issue-1"]').text()).toContain('已接受')
  expect(wrapper.get('[data-issue-id="issue-2"]').text()).toContain('需重新确认')
})
```

- [ ] **Step 2: Write failing find navigation test**

```ts
it('navigates document matches without mutating decisions', async () => {
  const wrapper = mountReviewWorkspace()
  await wrapper.get('[aria-label="查找内容"]').setValue('项目')
  await wrapper.get('button[name="next-match"]').trigger('click')
  expect(wrapper.get('[role="status"]').text()).toContain('第 2 / 3 处')
  expect(putDecisions).not.toHaveBeenCalled()
})
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
npm test -- --run tests/ReviewWorkspace.spec.ts
```

Expected: FAIL because batch and find controls are absent.

- [ ] **Step 4: Implement bounded batch actions**

Batch only the currently loaded filtered issues, maximum 500. Require confirmation for accepting high-risk security issues. Apply per-item outcomes and announce counts: “成功 18 项，需重新确认 2 项”.

- [ ] **Step 5: Implement local find navigation**

Search loaded block pages with code-point-safe matching. “全部替换” is enabled only when every match corresponds exactly to one auto-fixable issue; it submits custom decisions for those issue IDs instead of editing raw document text.

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
npm test -- --run tests/ReviewWorkspace.spec.ts
```

Expected: PASS.

```powershell
Set-Location ..\..
git add apps\web\src\components\review apps\web\src\composables\useReviewWorkspace.ts apps\web\tests\ReviewWorkspace.spec.ts
git commit -m "feat: add batch review and document search" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 6: Export panel and download flow

**Files:**
- Create: `apps/web/src/components/review/ExportPanel.vue`
- Modify: `apps/web/src/components/review/ReviewToolbar.vue`
- Modify: `apps/web/src/views/ReviewWorkspaceView.vue`
- Modify: `apps/web/tests/ReviewWorkspace.spec.ts`

**Interfaces:**
- Produces export selection based on source type.
- Polls export status with condition-based waits and exposes explicit failures/warnings.

- [ ] **Step 1: Write failing source-type restriction test**

```ts
it('does not offer modified document export for PDF', () => {
  const wrapper = mountReviewWorkspace({ fileType: 'pdf' })
  expect(wrapper.find('[value="modified_document"]').exists()).toBe(false)
  expect(wrapper.get('[value="html_report"]').exists()).toBe(true)
  expect(wrapper.get('[value="pdf_report"]').exists()).toBe(true)
})
```

- [ ] **Step 2: Write failing completed export test**

```ts
it('creates, waits for, and exposes a completed export', async () => {
  createExport.mockResolvedValue(queuedExport)
  getExport.mockResolvedValueOnce(processingExport).mockResolvedValueOnce(completedExport)
  vi.useFakeTimers()
  const wrapper = mountReviewWorkspace()
  await wrapper.get('button[name="create-export"]').trigger('click')
  await vi.advanceTimersByTimeAsync(2000)
  await vi.advanceTimersByTimeAsync(2000)
  expect(wrapper.get('a[download]').attributes('href')).toBe(
    '/api/v1/jobs/job-1/exports/export-1/download'
  )
  vi.useRealTimers()
})
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
npm test -- --run tests/ReviewWorkspace.spec.ts
```

Expected: FAIL because export UI is absent.

- [ ] **Step 4: Implement export selection and status**

TXT/DOCX offer modified file plus both reports; PDF offers reports only. Poll every two seconds while processing, stop on terminal status/unmount, show warnings before download, and expose retry after failure.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
npm test -- --run tests/ReviewWorkspace.spec.ts
```

Expected: PASS.

```powershell
Set-Location ..\..
git add apps\web\src\components\review apps\web\src\views\ReviewWorkspaceView.vue apps\web\tests\ReviewWorkspace.spec.ts
git commit -m "feat: export reviewed documents and reports" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 7: Responsive tabs, accessibility, and end-to-end flow

**Files:**
- Modify: `apps/web/src/App.vue`
- Modify: `apps/web/src/views/ReviewWorkspaceView.vue`
- Modify: `apps/web/src/components/review/*.vue`
- Modify: `apps/web/tests/ReviewWorkspace.spec.ts`
- Create: `apps/web/tests/reviewAccessibility.spec.ts`
- Modify: `apps/api/tests/e2e/test_upload_lifecycle.py`

**Interfaces:**
- Produces desktop three-column layout and mobile document/issues tabs.
- Produces full upload-to-report browser/API contract coverage.

- [ ] **Step 1: Write failing mobile-tab and keyboard tests**

```ts
it('uses tabs on narrow screens and restores focus', async () => {
  const wrapper = mountReviewWorkspace({ viewportWidth: 480 })
  await wrapper.get('[role="tab"][name="issues"]').trigger('click')
  expect(wrapper.get('[role="tabpanel"][aria-label="问题"]').isVisible()).toBe(true)
  expect(document.activeElement).toBe(wrapper.get('[role="tab"][name="issues"]').element)
})


it('moves between issues with keyboard shortcuts', async () => {
  const wrapper = mountReviewWorkspace()
  await wrapper.trigger('keydown', { key: 'j' })
  expect(wrapper.get('[data-issue-id="issue-2"]').attributes('aria-current')).toBe('true')
  await wrapper.trigger('keydown', { key: 'k' })
  expect(wrapper.get('[data-issue-id="issue-1"]').attributes('aria-current')).toBe('true')
})
```

- [ ] **Step 2: Run accessibility tests and verify RED**

Run:

```powershell
npm test -- --run tests/reviewAccessibility.spec.ts tests/ReviewWorkspace.spec.ts
```

Expected: FAIL because tab and keyboard behavior are absent.

- [ ] **Step 3: Implement responsive and reduced-motion behavior**

At `max-width: 900px`, show an ARIA tablist and one panel at a time. Preserve desktop DOM reading order. Add visible `:focus-visible` rings, `prefers-reduced-motion` overrides, minimum 44 px primary touch targets, and text/icon severity labels.

- [ ] **Step 4: Extend live lifecycle coverage**

Add an E2E test that uploads TXT with options, waits for terminal analysis, retrieves blocks/issues, applies a decision, creates an HTML report, and verifies download content. Use condition polling against job/export status rather than fixed sleeps.

- [ ] **Step 5: Run complete frontend/backend verification**

Run:

```powershell
Set-Location apps\web
npm test
npm run build
Set-Location ..\..
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\e2e\test_upload_lifecycle.py -v
```

Expected: PASS.

- [ ] **Step 6: Rebuild and smoke test Compose**

Run:

```powershell
docker compose -f infra\compose.yaml up --build -d
docker compose -f infra\compose.yaml ps
curl.exe --fail http://127.0.0.1:8080/api/v1/health
```

Expected: API, worker, web, PostgreSQL, and Redis are healthy; health endpoint returns HTTP 200.

- [ ] **Step 7: Commit**

```powershell
git add apps\web apps\api\tests\e2e\test_upload_lifecycle.py
git commit -m "feat: complete responsive review workflow" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Phase Acceptance

Run all frontend tests/build and the live TXT/DOCX/PDF lifecycle tests. Expected: users configure checks, follow progress, review results in the three-column workspace, apply decisions, and download supported outputs on desktop and mobile.
