# Vue Workspace Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic workspace with accessible Vue components while preserving every approved source and target interaction.

**Architecture:** Move state and document operations into typed composables keyed by stable IDs, split the UI by responsibility, and consume one result contract for synchronous and asynchronous execution. Keep the existing workspace route operational while components are extracted incrementally.

**Tech Stack:** Vue 3.5, TypeScript 5.7, Vite 6, Vitest 3, Vue Test Utils, jsdom.

**Spec:** `docs/superpowers/specs/2026-08-30-translation-pre-checker-integration-design.md`

## Global Constraints

- Complete the canonical-model and unified-pipeline plans first.
- Preserve all approved input, configuration, review, editing, navigation,
  session, theme, privacy, progress, and export capabilities.
- Use stable `issue_id` values, never array indexes, for review state.
- Keep the application usable after each component extraction.
- Add explicit labels, keyboard support, focus management, and live regions.
- Do not introduce a new state-management dependency unless a separate design
  approves it.

---

### Task 1: Extract a stable-ID verification workspace composable

**Files:**
- Create: `apps/web/src/composables/useVerificationWorkspace.ts`
- Create: `apps/web/tests/useVerificationWorkspace.spec.ts`
- Modify: `apps/web/src/types/verification.ts`

**Interfaces:**
- Produces: `useVerificationWorkspace()`.
- Produces: `issueStates: Ref<Record<string, IssueState>>`.
- Produces: `acceptIssue(issueId)`, `rejectIssue(issueId)`, `undoIssue(issueId)`.
- Produces: `acceptIssues(issueIds)`, `rejectIssues(issueIds)`, `undoLastBatch()`.
- Produces: computed `modifiedText`, `visibleIssues`, and `summary`.

- [ ] **Step 1: Write failing composable tests**

```ts
it('keeps decisions attached to issue ids after issue reordering', () => {
  const workspace = useVerificationWorkspace()
  workspace.loadResult(buildResult([issueA, issueB]))
  workspace.acceptIssue(issueA.issue_id)
  workspace.loadResult(buildResult([issueB, issueA]))
  expect(workspace.issueStates.value[issueA.issue_id]).toBe('accepted')
})

it('applies deletion suggestions', () => {
  const workspace = useVerificationWorkspace()
  workspace.loadResult(buildResult([buildIssue({ suggestion: '' })]))
  workspace.acceptIssue(issueId)
  expect(workspace.modifiedText.value).toBe('保留文本')
})
```

- [ ] **Step 2: Run the composable tests**

Run:

```bash
cd apps/web
npm test -- useVerificationWorkspace.spec.ts
```

Expected: FAIL because the composable is missing.

- [ ] **Step 3: Implement immutable review actions**

Store issue state by `issue_id`. Apply accepted replacements from highest
offset to lowest and treat an empty suggestion as deletion. Record the previous
state of each batch so undo restores exact prior values.

- [ ] **Step 4: Run tests and build**

Run:

```bash
cd apps/web
npm test -- useVerificationWorkspace.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/composables apps/web/src/types/verification.ts apps/web/tests/useVerificationWorkspace.spec.ts
git commit -m "feat: add stable verification workspace state"
```

### Task 2: Extract input, settings, and terminology components

**Files:**
- Create: `apps/web/src/components/workspace/SourceInputPanel.vue`
- Create: `apps/web/src/components/workspace/VerificationSettings.vue`
- Create: `apps/web/src/components/workspace/TerminologyEditor.vue`
- Create: `apps/web/src/composables/useTerminology.ts`
- Create: `apps/web/tests/SourceInputPanel.spec.ts`
- Create: `apps/web/tests/VerificationSettings.spec.ts`
- Create: `apps/web/tests/TerminologyEditor.spec.ts`
- Modify: `apps/web/src/views/WorkspaceView.vue`

**Interfaces:**
- Produces: `submit-text`, `submit-file`, and `update:options` events.
- Produces: terminology import parsers for CSV, TXT, TSV, comma, tab, and `→`.

- [ ] **Step 1: Write failing interaction tests**

```ts
it('submits text with Ctrl+Enter and Meta+Enter', async () => {
  const wrapper = mount(SourceInputPanel)
  await wrapper.get('textarea').setValue('检查文本')
  await wrapper.get('textarea').trigger('keydown', { key: 'Enter', ctrlKey: true })
  expect(wrapper.emitted('submit-text')?.[0]).toEqual(['检查文本'])
})

it('ignores comments and imports arrow-separated terminology', () => {
  expect(parseGlossary('# note\nAI → 人工智能')).toEqual([
    { original: 'AI', standard: '人工智能' }
  ])
})
```

- [ ] **Step 2: Run component tests**

Run:

```bash
cd apps/web
npm test -- SourceInputPanel.spec.ts VerificationSettings.spec.ts TerminologyEditor.spec.ts
```

Expected: FAIL because the components and parser are missing.

- [ ] **Step 3: Implement and wire components**

Keep seven-format upload, drag-and-drop, size validation, six scenarios, three
independent switches, manual terminology editing, import, deletion, and BOM CSV
example export. Use explicit labels and a keyboard-operable drop zone.

- [ ] **Step 4: Run component and existing workspace tests**

Run:

```bash
cd apps/web
npm test -- SourceInputPanel.spec.ts VerificationSettings.spec.ts TerminologyEditor.spec.ts WorkspaceView.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/workspace apps/web/src/composables/useTerminology.ts apps/web/src/views/WorkspaceView.vue apps/web/tests
git commit -m "refactor: split workspace input and settings"
```

### Task 3: Extract document and issue navigation views

**Files:**
- Create: `apps/web/src/components/workspace/DocumentViewer.vue`
- Create: `apps/web/src/components/workspace/IssueList.vue`
- Create: `apps/web/src/components/workspace/IssueDetails.vue`
- Create: `apps/web/src/composables/useIssueNavigation.ts`
- Create: `apps/web/tests/DocumentViewer.spec.ts`
- Create: `apps/web/tests/IssueNavigation.spec.ts`
- Modify: `apps/web/src/views/WorkspaceView.vue`

**Interfaces:**
- Produces: sentence and continuous view modes.
- Produces: `selectIssue(issueId)` and `selectOffset(offset)`.
- Produces: severity and layer filters.

- [ ] **Step 1: Write failing navigation tests**

```ts
it('selects an issue when its source highlight is activated', async () => {
  const wrapper = mount(DocumentViewer, { props: { result, selectedIssueId: null } })
  await wrapper.get(`[data-issue-id="${issue.issue_id}"]`).trigger('click')
  expect(wrapper.emitted('select-issue')?.[0]).toEqual([issue.issue_id])
})

it('shows alternatives and marks the first as recommended', () => {
  const wrapper = mount(IssueDetails, { props: { issue } })
  expect(wrapper.get('[data-recommended]').text()).toBe(issue.alternatives[0])
})
```

- [ ] **Step 2: Run view tests**

Run:

```bash
cd apps/web
npm test -- DocumentViewer.spec.ts IssueNavigation.spec.ts
```

Expected: FAIL because the components are missing.

- [ ] **Step 3: Implement safe highlighting and bidirectional selection**

Render text through Vue nodes rather than raw HTML. Split source text at sorted,
validated issue offsets. Add line numbers in sentence mode and retain continuous
mode. Scroll selected source and issue elements with `scrollIntoView`.

- [ ] **Step 4: Run tests and build**

Run:

```bash
cd apps/web
npm test -- DocumentViewer.spec.ts IssueNavigation.spec.ts WorkspaceView.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/workspace apps/web/src/composables/useIssueNavigation.ts apps/web/src/views/WorkspaceView.vue apps/web/tests
git commit -m "refactor: split document and issue views"
```

### Task 4: Implement complete review, search, replace, and free-edit workflows

**Files:**
- Create: `apps/web/src/components/workspace/ReviewActions.vue`
- Create: `apps/web/src/components/workspace/SearchReplacePanel.vue`
- Create: `apps/web/src/components/workspace/EditPreview.vue`
- Create: `apps/web/src/composables/useSearchReplace.ts`
- Modify: `apps/web/src/composables/useVerificationWorkspace.ts`
- Create: `apps/web/tests/ReviewActions.spec.ts`
- Create: `apps/web/tests/SearchReplacePanel.spec.ts`
- Create: `apps/web/tests/EditPreview.spec.ts`
- Modify: `apps/web/src/views/WorkspaceView.vue`

**Interfaces:**
- Produces: individual and batch accept/reject/undo.
- Produces: case-sensitive search, cyclic navigation, replace-current, and
  replace-all.
- Produces: explicit document revisions for free edits.

- [ ] **Step 1: Write failing defect-regression tests**

```ts
it('undoes a batch without referencing an undefined scope', async () => {
  const wrapper = mount(ReviewActions, { props: { selectedIds: [a, b] } })
  await wrapper.get('[data-action="accept-batch"]').trigger('click')
  await wrapper.get('[data-action="undo-batch"]').trigger('click')
  expect(wrapper.emitted('undo-batch')).toHaveLength(1)
})

it('creates an exportable revision from free edits', () => {
  const workspace = useVerificationWorkspace()
  workspace.saveManualEdit('手工修改后的全文')
  expect(workspace.currentRevision.value.text).toBe('手工修改后的全文')
  expect(workspace.currentRevision.value.revision_id).toBeTruthy()
})
```

- [ ] **Step 2: Run workflow tests**

Run:

```bash
cd apps/web
npm test -- ReviewActions.spec.ts SearchReplacePanel.spec.ts EditPreview.spec.ts
```

Expected: FAIL because the extracted workflows do not exist.

- [ ] **Step 3: Implement workflows**

Search matches use explicit start/end offsets and cycle at document boundaries.
Replacement creates a new revision and marks the result as requiring
re-verification. Free edit supports cancel, unchanged, and empty-content
validation. Review and manual edits share one revision model used by export.

- [ ] **Step 4: Run frontend workflow tests**

Run:

```bash
cd apps/web
npm test -- ReviewActions.spec.ts SearchReplacePanel.spec.ts EditPreview.spec.ts useVerificationWorkspace.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/workspace apps/web/src/composables apps/web/src/views/WorkspaceView.vue apps/web/tests
git commit -m "feat: complete document review workflows"
```

### Task 5: Unify synchronous and asynchronous result loading

**Files:**
- Modify: `apps/web/src/api/jobs.ts`
- Modify: `apps/web/src/api/verification.ts`
- Create: `apps/web/src/composables/useVerificationExecution.ts`
- Create: `apps/web/tests/useVerificationExecution.spec.ts`
- Modify: `apps/web/src/views/WorkspaceView.vue`
- Modify: `apps/web/tests/jobsApi.spec.ts`

**Interfaces:**
- Produces: `JobsApi.getResult(jobId) -> Promise<VerificationResult>`.
- Produces: one execution composable for direct results and SSE completion.

- [ ] **Step 1: Write failing execution tests**

```ts
it('loads the canonical result after the completed SSE event', async () => {
  const execution = useVerificationExecution({ jobsApi, verificationApi })
  await execution.analyzeFile(file, options)
  completeSubscription()
  await flushPromises()
  expect(jobsApi.getResult).toHaveBeenCalledWith(jobId)
  expect(execution.result.value?.document_id).toBe(documentId)
})
```

- [ ] **Step 2: Run execution tests**

Run:

```bash
cd apps/web
npm test -- useVerificationExecution.spec.ts jobsApi.spec.ts
```

Expected: FAIL because jobs cannot load verification results.

- [ ] **Step 3: Implement one execution state machine**

States are `idle`, `submitting`, `processing`, `completed`, `failed`, and
`expired`. Close old subscriptions before new work and on unmount. Ignore late
errors after terminal completion. Direct text sets the same canonical result
without SSE.

- [ ] **Step 4: Run API and workspace tests**

Run:

```bash
cd apps/web
npm test -- useVerificationExecution.spec.ts jobsApi.spec.ts verificationApi.spec.ts WorkspaceView.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/api apps/web/src/composables/useVerificationExecution.ts apps/web/src/views/WorkspaceView.vue apps/web/tests
git commit -m "feat: unify verification execution modes"
```

### Task 6: Complete export, session, theme, privacy, and accessibility coverage

**Files:**
- Create: `apps/web/src/components/workspace/ExportPanel.vue`
- Create: `apps/web/src/components/workspace/WorkspaceHeader.vue`
- Create: `apps/web/src/components/workspace/PrivacyDialog.vue`
- Create: `apps/web/src/composables/useWorkspaceSession.ts`
- Create: `apps/web/playwright.config.ts`
- Modify: `apps/web/package.json`
- Modify: `apps/web/package-lock.json`
- Modify: `apps/web/src/api/verification.ts`
- Modify: `apps/web/src/views/WorkspaceView.vue`
- Create: `apps/web/tests/ExportPanel.spec.ts`
- Create: `apps/web/tests/WorkspaceAccessibility.spec.ts`
- Create: `apps/web/tests/WorkspaceSession.spec.ts`
- Create: `apps/web/tests/e2e/workspace-lifecycle.spec.ts`

**Interfaces:**
- Produces: export requests keyed by document and revision IDs.
- Produces: versioned session payload with result, decisions, revision, options,
  terminology, filters, and view mode.

- [ ] **Step 1: Write failing session and accessibility tests**

```ts
it('restores terminology, filters, decisions, and the current revision', () => {
  saveWorkspaceSession(storage, state)
  expect(loadWorkspaceSession(storage)).toEqual(state)
})

it('announces progress and traps focus in the privacy dialog', async () => {
  const wrapper = mount(WorkspaceView, options)
  expect(wrapper.get('[role="status"]').attributes('aria-live')).toBe('polite')
  await wrapper.get('[data-open-privacy]').trigger('click')
  expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
})
```

- [ ] **Step 2: Run final component tests and confirm the E2E command is absent**

Run:

```bash
cd apps/web
npm test -- ExportPanel.spec.ts WorkspaceAccessibility.spec.ts WorkspaceSession.spec.ts
npm run test:e2e
```

Expected: component tests FAIL because the final components and versioned
session are absent; `npm run test:e2e` FAILS because the script is undefined.

- [ ] **Step 3: Implement final workspace surfaces and Playwright coverage**

Send document ID, source version, revision ID, replacements, edited text, and
track-change preference in export requests. Restore all approved session state.
Handle storage quota errors with a visible warning while retaining in-memory
state.

Implement theme persistence, privacy dialog focus trap and focus restoration,
keyboard-operable branding, labelled controls, and live announcements.

Install and configure the browser runner:

```bash
cd apps/web
npm install --save-dev @playwright/test@^1.55.0
npx playwright install chromium
```

Add scripts:

```json
{
  "scripts": {
    "test:e2e": "playwright test"
  }
}
```

Configure Playwright to run Chromium against Vite on `127.0.0.1:4173`, starting
the production preview with `npm run build && npm run preview -- --host
127.0.0.1`. In `workspace-lifecycle.spec.ts`, cover direct text analysis, file
job completion, issue acceptance, free editing, session reload, and export
request submission using deterministic API route fixtures.

- [ ] **Step 4: Run complete frontend verification**

Run:

```bash
cd apps/web
npm test
npm run build
npm run test:e2e
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src apps/web/tests apps/web/package.json apps/web/package-lock.json apps/web/playwright.config.ts
git commit -m "feat: complete redesigned verification workspace"
```
