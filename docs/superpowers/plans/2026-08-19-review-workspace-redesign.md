# Review Workspace Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the review screen as the approved C2 icon-and-label workspace while preserving every existing review, search, batch, and export workflow.

**Architecture:** `ReviewWorkspaceView` remains the composition root and owns only responsive/presentation state; `useReviewWorkspace` remains the sole owner of review business state and API calls. Focused shell components provide navigation, side-panel, tab, document-header, and dialog behavior, while existing feature components are restyled as content rather than nested cards.

**Tech Stack:** Vue 3.5, TypeScript 5.7, Vite 6, Vitest 3, Vue Test Utils 2, Playwright

**Spec:** `docs\superpowers\specs\2026-08-19-review-workspace-redesign-design.md`

## Global Constraints

- Do not modify backend APIs, data models, checker rules, issue categories, decision semantics, or job lifecycle.
- Do not rewrite `apps\web\src\composables\useReviewWorkspace.ts`; consume its existing `ReviewWorkspaceState` interface.
- Do not add a UI framework, icon package, dark theme, or unrelated refactor.
- Full four-region desktop mode starts at exactly `1280px`; `768–1279px` uses a single main panel with bottom navigation; `767px` and below uses the same navigation with issue details as a subview.
- Desktop uses one `100dvh` viewport with no browser-level scrolling; rail, side panel, document, and inspector own their overflow.
- The desktop rail is `64px`, the optional left panel is `280px`, and the inspector is `360px`; the document receives all remaining width and must be the largest content region at supported desktop viewports.
- Use one indigo accent, neutral gray/white surfaces, 4/8/12/16px spacing, 10–12px panel radii, 14px body text, 12px supporting text, and 16px panel titles.
- Every interactive control keeps a minimum `44×44px` target, visible focus, a non-color state indicator, and non-wrapping button text.
- Preserve issue pagination/filtering, highlight selection and overlap cycling, decision conflict/retry behavior, search navigation and replacement, batch decisions, export lifecycle, checker failures, and `aria-live` decision announcements.

---

## File Map

| File | Responsibility |
| --- | --- |
| `apps\web\src\components\review\workspaceLayout.ts` | Shared presentation-only unions for rail tools, inspector tabs, and compact views. |
| `apps\web\src\components\review\ToolRail.vue` | Desktop rail and compact bottom navigation, including keyboard navigation and export trigger focus. |
| `apps\web\src\components\review\WorkspaceSidePanel.vue` | Stable titled/closable container for issue and batch content. |
| `apps\web\src\components\review\ContextInspector.vue` | Accessible details/search tabs and independently scrolling tab panels. |
| `apps\web\src\components\review\DocumentHeader.vue` | Sticky file metadata, summary loading/error, issue count, and loaded paragraph count (only blocks whose `kind` is `paragraph`). |
| `apps\web\src\components\review\CheckerFailureNotice.vue` | Compact localized partial-checker warning used in the issue panel. |
| `apps\web\src\components\review\ReviewNavigation.vue` | Existing issue overview, filters, list, retry, and pagination content without outer-card styling. |
| `apps\web\src\components\review\BatchActions.vue` | Existing batch behavior restyled as side-panel content. |
| `apps\web\src\components\review\FindReplace.vue` | Existing search behavior restyled into a vertical inspector layout. |
| `apps\web\src\components\review\IssuePanel.vue` | Existing decision behavior restyled as inspector content. |
| `apps\web\src\components\review\ExportPanel.vue` | Existing export state plus accessible anchored-dialog behavior. |
| `apps\web\src\components\review\DocumentViewer.vue` | Existing document behavior plus `DocumentHeader`. |
| `apps\web\src\views\ReviewWorkspaceView.vue` | Presentation state machine, responsive composition, and feature event wiring. |
| `apps\web\src\components\review\ReviewToolbar.vue` | Deleted after all responsibilities move to focused components. |
| `apps\web\tests\reviewShellComponents.spec.ts` | Unit tests for new shell components. |
| `apps\web\tests\ReviewWorkspace.spec.ts` | Integration and preserved business-flow regression coverage. |
| `apps\web\tests\reviewAccessibility.spec.ts` | Semantic, focus, target-size, and CSS contract assertions. |
| `apps\web\tests\WorkspaceView.spec.ts` | Upload-to-review handoff and review-shell integration. |
| `apps\web\tests\fixtures\review-workspace.html` | Vite-served layout-test entry; never included in the production entry graph. |
| `apps\web\tests\fixtures\reviewWorkspaceHarness.ts` | Browser fixture that mounts `ReviewWorkspaceView` with deterministic injected API mocks. |
| `apps\web\tests\layout\reviewWorkspaceLayout.spec.ts` | Real-browser geometry assertions at all required viewport sizes. |
| `apps\web\playwright.config.ts` | Isolated Playwright web-server and layout-test configuration. |
| `apps\web\package.json` | `test:layout` script and Playwright development dependency. |

---

### Task 1: Shared Layout Types and Tool Navigation

**Files:**
- Create: `apps\web\src\components\review\workspaceLayout.ts`
- Create: `apps\web\src\components\review\ToolRail.vue`
- Create: `apps\web\tests\reviewShellComponents.spec.ts`

**Interfaces:**
- Produces: `WorkspaceTool = 'document' | 'issues' | 'search' | 'batch'`
- Produces: `RailTool = Exclude<WorkspaceTool, 'document'>`
- Produces: `SidePanelTool = 'issues' | 'batch'`
- Produces: `InspectorTab = 'details' | 'search'`
- Produces: `CompactWorkspaceView = WorkspaceTool`
- Produces: `ToolRail` props `{ mode: 'rail' | 'bottom'; activeTool: WorkspaceTool; sidePanelOpen: boolean; exportOpen: boolean }`
- Produces: `ToolRail` events `activate(tool: WorkspaceTool)` and `toggleExport()`
- Produces: exposed method `focusExportButton(): void`

- [ ] **Step 1: Write focused failing tests for both navigation modes**

```ts
// apps\web\tests\reviewShellComponents.spec.ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ToolRail from '../src/components/review/ToolRail.vue'

describe('ToolRail', () => {
  it('shows C2 labels, exposes selection, and toggles the active side tool', async () => {
    const wrapper = mount(ToolRail, {
      props: {
        mode: 'rail',
        activeTool: 'issues',
        sidePanelOpen: true,
        exportOpen: false
      }
    })

    expect(wrapper.get('nav').attributes('aria-label')).toBe('审阅工具')
    expect(wrapper.text()).toContain('问题')
    expect(wrapper.text()).toContain('查找')
    expect(wrapper.text()).toContain('批量')
    expect(wrapper.text()).toContain('导出')
    expect(wrapper.find('[data-tool="document"]').exists()).toBe(false)
    expect(wrapper.get('[data-tool="issues"]').attributes('aria-pressed')).toBe('true')

    await wrapper.get('[data-tool="issues"]').trigger('click')
    expect(wrapper.emitted('activate')).toEqual([['issues']])
  })

  it('adds document in bottom mode and supports roving keyboard focus', async () => {
    const wrapper = mount(ToolRail, {
      attachTo: document.body,
      props: {
        mode: 'bottom',
        activeTool: 'document',
        sidePanelOpen: false,
        exportOpen: false
      }
    })
    const documentButton = wrapper.get('[data-tool="document"]')

    await documentButton.trigger('keydown', { key: 'ArrowRight' })

    expect(document.activeElement).toBe(wrapper.get('[data-tool="issues"]').element)
    wrapper.unmount()
  })

  it('reports export state and exposes trigger focus', () => {
    const wrapper = mount(ToolRail, {
      attachTo: document.body,
      props: {
        mode: 'rail',
        activeTool: 'issues',
        sidePanelOpen: false,
        exportOpen: true
      }
    })

    expect(wrapper.get('[data-tool="export"]').attributes('aria-expanded')).toBe('true')
    ;(wrapper.vm as { focusExportButton(): void }).focusExportButton()
    expect(document.activeElement).toBe(wrapper.get('[data-tool="export"]').element)
    wrapper.unmount()
  })
})
```

- [ ] **Step 2: Run the component test and verify the missing component fails**

Run:

```powershell
Set-Location apps\web
npm test -- reviewShellComponents.spec.ts
```

Expected: FAIL because `ToolRail.vue` does not exist.

- [ ] **Step 3: Define the shared types and implement the rail with inline SVG**

```ts
// apps\web\src\components\review\workspaceLayout.ts
export type WorkspaceTool = 'document' | 'issues' | 'search' | 'batch'
export type RailTool = Exclude<WorkspaceTool, 'document'>
export type SidePanelTool = 'issues' | 'batch'
export type InspectorTab = 'details' | 'search'
export type CompactWorkspaceView = WorkspaceTool
```

```vue
<!-- apps\web\src\components\review\ToolRail.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import type { WorkspaceTool } from './workspaceLayout'

const props = defineProps<{
  mode: 'rail' | 'bottom'
  activeTool: WorkspaceTool
  sidePanelOpen: boolean
  exportOpen: boolean
}>()
const emit = defineEmits<{
  activate: [tool: WorkspaceTool]
  toggleExport: []
}>()

const exportButton = ref<HTMLButtonElement | null>(null)
const buttons = new Map<string, HTMLButtonElement>()
const tools: Array<{ id: WorkspaceTool; label: string }> = [
  { id: 'document', label: '文档' },
  { id: 'issues', label: '问题' },
  { id: 'search', label: '查找' },
  { id: 'batch', label: '批量' }
]

function visibleTools(): Array<{ id: WorkspaceTool; label: string }> {
  return props.mode === 'bottom' ? tools : tools.filter(({ id }) => id !== 'document')
}

function moveFocus(current: string, key: string): void {
  const order = [...visibleTools().map(({ id }) => id), 'export']
  const index = order.indexOf(current)
  const delta = key === 'ArrowLeft' || key === 'ArrowUp' ? -1 : 1
  buttons.get(order[(index + delta + order.length) % order.length] ?? order[0])?.focus()
}

function focusExportButton(): void {
  exportButton.value?.focus()
}

defineExpose({ focusExportButton })
</script>
```

Render a `nav` with `aria-label="审阅工具"` in rail mode and `aria-label="工作台视图"` in bottom mode. Each button must include a lightweight inline line SVG, visible Chinese label, `title`, `data-tool`, a 44px target, and an active class; use `aria-pressed` for issue/search/batch and `aria-current="page"` for the active compact view. Keep export last in bottom mode and pinned to the bottom in rail mode.

- [ ] **Step 4: Run the focused test and type-aware build**

Run:

```powershell
Set-Location apps\web
npm test -- reviewShellComponents.spec.ts
npm run build
```

Expected: both commands PASS.

- [ ] **Step 5: Commit the navigation primitive**

```powershell
git add apps\web\src\components\review\workspaceLayout.ts apps\web\src\components\review\ToolRail.vue apps\web\tests\reviewShellComponents.spec.ts
git commit -m "Add review workspace tool navigation" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Side Panel and Context Inspector Containers

**Files:**
- Create: `apps\web\src\components\review\WorkspaceSidePanel.vue`
- Create: `apps\web\src\components\review\ContextInspector.vue`
- Modify: `apps\web\tests\reviewShellComponents.spec.ts`

**Interfaces:**
- Consumes: `InspectorTab` from `workspaceLayout.ts`
- Produces: `WorkspaceSidePanel` props `{ open: boolean; title: string }`, event `close()`, and default slot
- Produces: `ContextInspector` prop `{ activeTab: InspectorTab }`, event `update:activeTab(tab: InspectorTab)`, and named slots `details`/`search`

- [ ] **Step 1: Add failing container and keyboard-model tests**

```ts
import ContextInspector from '../src/components/review/ContextInspector.vue'
import WorkspaceSidePanel from '../src/components/review/WorkspaceSidePanel.vue'

it('labels and closes the optional side panel', async () => {
  const wrapper = mount(WorkspaceSidePanel, {
    props: { open: true, title: '问题' },
    slots: { default: '<p>问题内容</p>' }
  })

  expect(wrapper.get('aside').attributes('aria-label')).toBe('问题')
  expect(wrapper.text()).toContain('问题内容')
  await wrapper.get('button[aria-label="关闭问题面板"]').trigger('click')
  expect(wrapper.emitted('close')).toHaveLength(1)
})

it('implements arrow, Home, and End tab navigation', async () => {
  const wrapper = mount(ContextInspector, {
    attachTo: document.body,
    props: { activeTab: 'details' },
    slots: { details: '详情内容', search: '查找内容' }
  })
  const detailsTab = wrapper.get('[role="tab"][data-tab="details"]')

  await detailsTab.trigger('keydown', { key: 'ArrowRight' })
  expect(wrapper.emitted('update:activeTab')).toEqual([['search']])
  await wrapper.setProps({ activeTab: 'search' })
  expect(document.activeElement).toBe(wrapper.get('[data-tab="search"]').element)

  await wrapper.get('[data-tab="search"]').trigger('keydown', { key: 'Home' })
  expect(wrapper.emitted('update:activeTab')?.at(-1)).toEqual(['details'])
  wrapper.unmount()
})
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```powershell
Set-Location apps\web
npm test -- reviewShellComponents.spec.ts
```

Expected: FAIL because both container components are missing.

- [ ] **Step 3: Implement the focused containers**

```vue
<!-- WorkspaceSidePanel.vue -->
<script setup lang="ts">
defineProps<{ open: boolean; title: string }>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <aside v-show="open" class="workspace-side-panel" :aria-label="title">
    <header class="workspace-side-panel__header">
      <h2>{{ title }}</h2>
      <button type="button" :aria-label="`关闭${title}面板`" @click="emit('close')">×</button>
    </header>
    <div class="workspace-side-panel__content"><slot /></div>
  </aside>
</template>
```

```vue
<!-- ContextInspector.vue -->
<script setup lang="ts">
import { nextTick, ref } from 'vue'
import type { InspectorTab } from './workspaceLayout'

const props = defineProps<{ activeTab: InspectorTab }>()
const emit = defineEmits<{ 'update:activeTab': [tab: InspectorTab] }>()
const tabButtons = ref<Record<InspectorTab, HTMLButtonElement | null>>({
  details: null,
  search: null
})

function activate(tab: InspectorTab, focus = false): void {
  emit('update:activeTab', tab)
  if (focus) void nextTick(() => tabButtons.value[tab]?.focus())
}
</script>
```

Render standard `tablist`, `tab`, and `tabpanel` relationships with stable IDs. Keep both panels mounted with `v-show` so typed search and decision input state survive tab changes. The header remains fixed while `.context-inspector__panel` owns scrolling.

- [ ] **Step 4: Run component tests and build**

Run:

```powershell
Set-Location apps\web
npm test -- reviewShellComponents.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit the workspace containers**

```powershell
git add apps\web\src\components\review\WorkspaceSidePanel.vue apps\web\src\components\review\ContextInspector.vue apps\web\tests\reviewShellComponents.spec.ts
git commit -m "Add review workspace panel containers" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Sticky Document Header

**Files:**
- Create: `apps\web\src\components\review\DocumentHeader.vue`
- Modify: `apps\web\src\components\review\DocumentViewer.vue`
- Modify: `apps\web\src\components\review\ReviewToolbar.vue`
- Modify: `apps\web\src\views\ReviewWorkspaceView.vue`
- Modify: `apps\web\tests\reviewShellComponents.spec.ts`
- Modify: `apps\web\tests\ReviewWorkspace.spec.ts`

**Interfaces:**
- Produces: `DocumentHeader` props `{ sourceName: string; fileType: FileType; loadedParagraphCount: number; totalIssues: number | null; loading: boolean; error: string | null }`
- Produces: `DocumentHeader` event `retry()`
- Extends: `DocumentViewer` props with `sourceName`, `fileType`, `totalIssues`, `summaryLoading`, and `summaryError`
- Extends: `DocumentViewer` events with `retrySummary()`

- [ ] **Step 1: Add failing metadata and summary-error tests**

```ts
import DocumentHeader from '../src/components/review/DocumentHeader.vue'

it('renders file metadata and retries a failed summary', async () => {
  const wrapper = mount(DocumentHeader, {
    props: {
      sourceName: 'contract.docx',
      fileType: 'docx',
      loadedParagraphCount: 42,
      totalIssues: 7,
      loading: false,
      error: '总览加载失败'
    }
  })

  expect(wrapper.text()).toContain('contract.docx')
  expect(wrapper.text()).toContain('DOCX')
  expect(wrapper.text()).toContain('42 个已加载段落')
  expect(wrapper.text()).toContain('7 个问题')
  expect(wrapper.get('[role="alert"]').text()).toContain('总览加载失败')
  await wrapper.get('button').trigger('click')
  expect(wrapper.emitted('retry')).toHaveLength(1)
})
```

Add an integration assertion to the existing “renders semantic columns…” test:

```ts
expect(wrapper.get('[data-testid="document-header"]').text()).toContain('sample.txt')
expect(wrapper.get('[data-testid="document-header"]').text()).toContain('2 个已加载段落')
expect(wrapper.get('[data-testid="document-header"]').text()).toContain('2 个问题')
```

- [ ] **Step 2: Run the focused tests and verify the missing header fails**

Run:

```powershell
Set-Location apps\web
npm test -- reviewShellComponents.spec.ts ReviewWorkspace.spec.ts
```

Expected: FAIL because `DocumentHeader.vue` and the new viewer props do not exist.

- [ ] **Step 3: Implement and embed `DocumentHeader`**

```vue
<!-- DocumentHeader.vue -->
<script setup lang="ts">
import type { FileType } from '../../types/review'
defineProps<{
  sourceName: string
  fileType: FileType
  loadedParagraphCount: number
  totalIssues: number | null
  loading: boolean
  error: string | null
}>()
const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <header class="document-header" data-testid="document-header">
    <div class="document-header__identity">
      <strong :title="sourceName">{{ sourceName }}</strong>
      <span>{{ fileType.toUpperCase() }}</span>
    </div>
    <p>{{ loadedParagraphCount }} 个已加载段落 · {{ totalIssues ?? '—' }} 个问题</p>
    <span v-if="loading" role="status">正在读取问题总览…</span>
    <div v-else-if="error" role="alert">
      <span>{{ error }}</span>
      <button type="button" @click="emit('retry')">重试总览</button>
    </div>
  </header>
</template>
```

Replace `DocumentViewer`’s current “文档内容” heading with `DocumentHeader`, passing `blocks.filter(({ kind }) => kind === 'paragraph').length`; do not label headings, table cells, headers, or footers as paragraphs. Keep the existing document error and retry inside the body because it belongs to document loading, not summary loading. Wire all new props and `retry-summary` in every desktop/compact viewer instance in `ReviewWorkspaceView`.

Shrink `ReviewToolbar` in the same commit: remove its file header, `sourceName`, `summary`, `loading`, `error`, and `retry` interface because `DocumentHeader` now owns those responsibilities. Keep only the not-yet-migrated export, batch, find, and checker-failure sections so no control is duplicated during the staged migration.

- [ ] **Step 4: Run component and integration tests**

Run:

```powershell
Set-Location apps\web
npm test -- reviewShellComponents.spec.ts ReviewWorkspace.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit the document header**

```powershell
git add apps\web\src\components\review\DocumentHeader.vue apps\web\src\components\review\DocumentViewer.vue apps\web\src\components\review\ReviewToolbar.vue apps\web\src\views\ReviewWorkspaceView.vue apps\web\tests\reviewShellComponents.spec.ts apps\web\tests\ReviewWorkspace.spec.ts
git commit -m "Move file metadata into document header" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Desktop Rail and Left Functional Panel

**Files:**
- Create: `apps\web\src\components\review\CheckerFailureNotice.vue`
- Modify: `apps\web\src\views\ReviewWorkspaceView.vue`
- Modify: `apps\web\src\components\review\ReviewToolbar.vue`
- Modify: `apps\web\src\components\review\ReviewNavigation.vue`
- Modify: `apps\web\src\components\review\BatchActions.vue`
- Modify: `apps\web\tests\ReviewWorkspace.spec.ts`
- Modify: `apps\web\tests\reviewAccessibility.spec.ts`

**Interfaces:**
- Consumes: `RailTool`, `ToolRail`, `WorkspaceSidePanel`, `ReviewNavigation`, `BatchActions`
- Produces in `ReviewWorkspaceView`: `activeRailTool: Ref<RailTool>`, `activeSidePanelTool: Ref<SidePanelTool>`, `isSidePanelOpen: Ref<boolean>`, `activeInspectorTab: Ref<InspectorTab>`
- Produces: `CheckerFailureNotice` prop `{ failures: CheckerFailureMap }`

- [ ] **Step 1: Add failing desktop state-transition tests**

```ts
it('toggles issues and batch content from the desktop C2 rail', async () => {
  const restoreViewport = mockViewportWidth(1440)
  try {
    const wrapper = mountReviewWorkspace()
    await flushPromises()

    expect(wrapper.get('[data-tool="issues"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('aside[aria-label="问题"]').isVisible()).toBe(true)

    await wrapper.get('[data-tool="issues"]').trigger('click')
    expect(wrapper.find('aside[aria-label="问题"]').isVisible()).toBe(false)

    await wrapper.get('[data-tool="batch"]').trigger('click')
    expect(wrapper.get('aside[aria-label="批量"]').isVisible()).toBe(true)
    expect(wrapper.get('aside[aria-label="批量"]').text()).toContain('批量处理当前筛选结果')
  } finally {
    restoreViewport()
  }
})

it('places partial checker failures at the top of the issues panel', async () => {
  const wrapper = mountReviewWorkspace(createAnalysisApiMock({
    getSummary: vi.fn().mockResolvedValue(buildSummary({
      checker_failures: {
        security: { code: 'checker_failed', message: '安全检查器启动失败' }
      }
    }))
  }))
  await flushPromises()

  const issuesPanel = wrapper.get('aside[aria-label="问题"]')
  expect(issuesPanel.get('.checker-failures__category').text()).toBe('安全')
})
```

Replace obsolete accessibility assertions about `display: contents` and old grid areas with:

```ts
expect(ReviewWorkspaceViewSource).toContain('@media (min-width: 1280px)')
expect(ReviewWorkspaceViewSource).toContain('64px')
expect(ReviewWorkspaceViewSource).toContain('280px')
expect(ReviewWorkspaceViewSource).not.toContain('display: contents')
```

- [ ] **Step 2: Run the integration/accessibility tests and verify they fail**

Run:

```powershell
Set-Location apps\web
npm test -- ReviewWorkspace.spec.ts reviewAccessibility.spec.ts
```

Expected: FAIL because the rail and side-panel state are not wired.

- [ ] **Step 3: Implement the desktop presentation state and left panel**

```ts
const activeRailTool = ref<RailTool>('issues')
const activeSidePanelTool = ref<SidePanelTool>('issues')
const isSidePanelOpen = ref(true)
const activeInspectorTab = ref<InspectorTab>('details')

function activateDesktopTool(tool: WorkspaceTool): void {
  if (tool === 'document') return
  if (tool === 'search') {
    activeRailTool.value = 'search'
    activeInspectorTab.value = 'search'
    return
  }
  if (
    activeRailTool.value === tool &&
    activeSidePanelTool.value === tool &&
    isSidePanelOpen.value
  ) {
    isSidePanelOpen.value = false
    return
  }
  activeRailTool.value = tool
  activeSidePanelTool.value = tool
  isSidePanelOpen.value = true
  if (tool === 'issues') activeInspectorTab.value = 'details'
}
```

Create the desktop shell in DOM order: `ToolRail`, `WorkspaceSidePanel`, `DocumentViewer`, inspector placeholder. Use `grid-template-columns: 64px 280px minmax(0, 1fr) 360px` when the side panel is open and `64px minmax(0, 1fr) 360px` when closed. Render left-panel content from `activeSidePanelTool`, not `activeRailTool`, so activating search retains the previous issue/batch panel. Put `CheckerFailureNotice` before `ReviewNavigation` in issue mode and `BatchActions` in batch mode.

Move the checker-failure computed mapping and markup from `ReviewToolbar` into `CheckerFailureNotice`. Move `BatchActions` out of `ReviewToolbar`, then remove its batch props/events/import so the transitional toolbar contains only export and find. Remove outer backgrounds, borders, shadows, and 981px compact overrides from `ReviewNavigation` and `BatchActions`; their container now provides the surface. Preserve all controls, warnings, retries, filters, debouncing, pagination, and confirmations unchanged.

- [ ] **Step 4: Run focused behavior and accessibility tests**

Run:

```powershell
Set-Location apps\web
npm test -- ReviewWorkspace.spec.ts reviewAccessibility.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit the desktop rail and left panel**

```powershell
git add apps\web\src\components\review\CheckerFailureNotice.vue apps\web\src\components\review\ReviewToolbar.vue apps\web\src\components\review\ReviewNavigation.vue apps\web\src\components\review\BatchActions.vue apps\web\src\views\ReviewWorkspaceView.vue apps\web\tests\ReviewWorkspace.spec.ts apps\web\tests\reviewAccessibility.spec.ts
git commit -m "Add desktop review rail and side panel" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Context Inspector and Selection Routing

**Files:**
- Modify: `apps\web\src\views\ReviewWorkspaceView.vue`
- Modify: `apps\web\src\components\review\ReviewToolbar.vue`
- Modify: `apps\web\src\components\review\FindReplace.vue`
- Modify: `apps\web\src\components\review\IssuePanel.vue`
- Modify: `apps\web\tests\ReviewWorkspace.spec.ts`
- Modify: `apps\web\tests\reviewAccessibility.spec.ts`

**Interfaces:**
- Consumes: `InspectorTab`, `ContextInspector`, `IssuePanel`, `FindReplace`
- Consumes: `activeInspectorTab`, `activeRailTool`, and `activeSidePanelTool` created in Task 4
- Produces: `selectIssueAndShowDetails(issueId: string): void`
- Produces: `selectHighlightAndShowDetails(issueId: string): void`

- [ ] **Step 1: Add failing tab and selection-routing tests**

```ts
it('routes search to the inspector without changing the left panel', async () => {
  const wrapper = mountReviewWorkspace()
  await flushPromises()

  await wrapper.get('[data-tool="batch"]').trigger('click')
  await wrapper.get('[data-tool="search"]').trigger('click')

  expect(wrapper.get('[role="tab"][data-tab="search"]').attributes('aria-selected')).toBe('true')
  expect(wrapper.get('aside[aria-label="批量"]').isVisible()).toBe(true)
})

it('opens details for issue-card and highlight selection', async () => {
  const wrapper = mountReviewWorkspace()
  await flushPromises()

  await wrapper.get('[data-tool="search"]').trigger('click')
  await wrapper.get('[data-issue-id="issue-2"]').trigger('click')
  expect(wrapper.get('[data-tab="details"]').attributes('aria-selected')).toBe('true')

  await wrapper.get('[data-tool="search"]').trigger('click')
  await wrapper.get('[data-highlight-range-issue-ids~="issue-1"]').trigger('click')
  expect(wrapper.get('[data-tab="details"]').attributes('aria-selected')).toBe('true')
})

it('keeps search visible while navigating matches', async () => {
  const wrapper = mountReviewWorkspace()
  await flushPromises()
  await wrapper.get('[data-tool="search"]').trigger('click')
  await wrapper.get('[aria-label="查找内容"]').setValue('文')
  await wrapper.get('button[name="next-match"]').trigger('click')

  expect(wrapper.get('[data-tab="search"]').attributes('aria-selected')).toBe('true')
  expect(wrapper.get('[aria-label="查找内容"]').isVisible()).toBe(true)
})
```

- [ ] **Step 2: Run the focused integration tests and verify they fail**

Run:

```powershell
Set-Location apps\web
npm test -- ReviewWorkspace.spec.ts
```

Expected: FAIL because the inspector and routing wrappers are not connected.

- [ ] **Step 3: Wire the inspector and simplify its feature content**

```ts
function selectIssueAndShowDetails(issueId: string): void {
  selectIssue(issueId)
  activeRailTool.value = 'issues'
  activeInspectorTab.value = 'details'
}

function selectHighlightAndShowDetails(issueId: string): void {
  selectHighlight(issueId)
  activeRailTool.value = 'issues'
  activeInspectorTab.value = 'details'
}
```

Render:

```vue
<ContextInspector v-model:active-tab="activeInspectorTab">
  <template #details>
    <IssuePanel
      :issue="selectedIssue"
      :decision-error="decisionError"
      :can-retry-decision="canRetryDecision"
      @decide="decide"
      @retry-decision="retryDecision"
    />
  </template>
  <template #search>
    <FindReplace
      :query="findQuery"
      :replacement="replaceText"
      :status="findStatus"
      :can-navigate="canNavigateMatches"
      :can-replace-all="canReplaceAllMatches"
      :busy="bulkActionPending"
      :error="findReplaceError"
      @update-query="setFindQuery"
      @update-replacement="setReplaceText"
      @previous-match="goToPreviousMatch"
      @next-match="goToNextMatch"
      @replace-all="replaceAllMatches"
    />
  </template>
</ContextInspector>
```

Restyle `FindReplace` as a vertical flow: one-column fields, status, one non-wrapping action row, and no desktop horizontal toolbar media rule. Remove it and its props/events/import from the transitional `ReviewToolbar`, which must now contain only `ExportPanel`. Remove the outer card surface from `IssuePanel` and `FindReplace`; keep business controls and errors unchanged.

- [ ] **Step 4: Run search, selection, decision, and accessibility regressions**

Run:

```powershell
Set-Location apps\web
npm test -- ReviewWorkspace.spec.ts reviewAccessibility.spec.ts
npm run build
```

Expected: PASS, including the existing internal-viewer search scroll tests.

- [ ] **Step 5: Commit the inspector migration**

```powershell
git add apps\web\src\components\review\ReviewToolbar.vue apps\web\src\components\review\FindReplace.vue apps\web\src\components\review\IssuePanel.vue apps\web\src\views\ReviewWorkspaceView.vue apps\web\tests\ReviewWorkspace.spec.ts apps\web\tests\reviewAccessibility.spec.ts
git commit -m "Move details and search into context inspector" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Anchored Export Dialog and Toolbar Removal

**Files:**
- Modify: `apps\web\src\components\review\ExportPanel.vue`
- Modify: `apps\web\src\views\ReviewWorkspaceView.vue`
- Delete: `apps\web\src\components\review\ReviewToolbar.vue`
- Modify: `apps\web\tests\ReviewWorkspace.spec.ts`
- Modify: `apps\web\tests\reviewAccessibility.spec.ts`

**Interfaces:**
- Extends: `ExportPanel` props from `{ jobId; fileType }` to `{ jobId; fileType; open }`
- Produces: `ExportPanel` event `close()`
- Consumes: `ToolRail.focusExportButton()`
- Produces in `ReviewWorkspaceView`: `isExportOpen: Ref<boolean>`

- [ ] **Step 1: Add failing dialog, focus, and state-retention tests**

```ts
it('opens export as a modal dialog and restores trigger focus', async () => {
  const wrapper = mountReviewWorkspaceWithConfig({ attachTo: document.body })
  await flushPromises()
  const trigger = wrapper.get('[data-tool="export"]')

  await trigger.trigger('click')
  await flushPromises()
  const dialog = wrapper.get('[role="dialog"][aria-label="导出文件"]')
  expect(dialog.isVisible()).toBe(true)
  expect(dialog.element.contains(document.activeElement)).toBe(true)

  await dialog.trigger('keydown', { key: 'Escape' })
  await flushPromises()
  expect(dialog.isVisible()).toBe(false)
  expect(document.activeElement).toBe(trigger.element)
  wrapper.unmount()
})

it('retains completed export state after closing and reopening', async () => {
  const wrapper = mountReviewWorkspace()
  await flushPromises()
  await wrapper.get('[data-tool="export"]').trigger('click')
  await wrapper.get('button[name="create-export"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[data-testid="export-download-link"]').exists()).toBe(true)

  await wrapper.get('[aria-label="关闭导出"]').trigger('click')
  await wrapper.get('[data-tool="export"]').trigger('click')
  expect(wrapper.get('[data-testid="export-download-link"]').exists()).toBe(true)
})

it('traps focus and closes when the backdrop is clicked', async () => {
  const wrapper = mountReviewWorkspaceWithConfig({ attachTo: document.body })
  await flushPromises()
  await wrapper.get('[data-tool="export"]').trigger('click')
  const dialog = wrapper.get('[role="dialog"][aria-label="导出文件"]')
  const close = wrapper.get('[aria-label="关闭导出"]')
  close.element.focus()
  await close.trigger('keydown', { key: 'Tab', shiftKey: true })
  expect(dialog.element.contains(document.activeElement)).toBe(true)

  await wrapper.get('[data-testid="export-backdrop"]').trigger('pointerdown')
  await flushPromises()
  expect(dialog.isVisible()).toBe(false)
  wrapper.unmount()
})
```

Update each existing export lifecycle test to open `[data-tool="export"]` before interacting with export controls.

- [ ] **Step 2: Run export tests and verify the dialog assertions fail**

Run:

```powershell
Set-Location apps\web
npm test -- ReviewWorkspace.spec.ts
```

Expected: FAIL because export is still always visible and has no dialog behavior.

- [ ] **Step 3: Add accessible dialog behavior without moving export business state**

```ts
const props = defineProps<{ jobId: string; fileType: FileType; open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLElement | null>(null)

function focusableElements(): HTMLElement[] {
  if (!dialog.value) return []
  return Array.from(
    dialog.value.querySelectorAll<HTMLElement>(
      'button:not(:disabled), select:not(:disabled), input:not(:disabled), a[href]'
    )
  )
}

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    await nextTick()
    focusableElements()[0]?.focus()
  }
)

function onDialogKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
    return
  }
  if (event.key !== 'Tab') return
  const focusable = focusableElements()
  const first = focusable[0]
  const last = focusable.at(-1)
  if (!first || !last) return
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}
```

Wrap the existing panel in a `v-show="open"` overlay with `data-testid="export-backdrop"`, `role="dialog"`, `aria-modal="true"`, `aria-label="导出文件"`, a close button, `@pointerdown.self="emit('close')"`, and `@keydown="onDialogKeydown"`. Position the desktop panel from the rail’s lower-left edge toward the upper-right, cap it at `360px`, and constrain height to the viewport. Do not conditionally unmount the component, cancel active polling, or reset `selectedType`, warnings, errors, or completed download state when it closes.

In `ReviewWorkspaceView`, toggle `isExportOpen`; after handling `close`, wait for `nextTick()` and call the mounted rail’s `focusExportButton()`. Remove the now-unused `ReviewToolbar` import/rendering and delete its file.

- [ ] **Step 4: Run all export and accessibility regressions**

Run:

```powershell
Set-Location apps\web
npm test -- ReviewWorkspace.spec.ts reviewAccessibility.spec.ts
npm run build
```

Expected: PASS, including polling cancellation on workspace unmount, warning confirmation, retry, expiration, and format-change tests.

- [ ] **Step 5: Commit the dialog and toolbar removal**

```powershell
git add apps\web\src\components\review\ExportPanel.vue apps\web\src\views\ReviewWorkspaceView.vue apps\web\tests\ReviewWorkspace.spec.ts apps\web\tests\reviewAccessibility.spec.ts
git rm apps\web\src\components\review\ReviewToolbar.vue
git commit -m "Move export into anchored workspace dialog" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Tablet and Phone Bottom Navigation

**Files:**
- Modify: `apps\web\src\views\ReviewWorkspaceView.vue`
- Modify: `apps\web\src\views\WorkspaceView.vue`
- Modify: `apps\web\src\components\review\ReviewNavigation.vue`
- Modify: `apps\web\tests\ReviewWorkspace.spec.ts`
- Modify: `apps\web\tests\WorkspaceView.spec.ts`
- Modify: `apps\web\tests\reviewAccessibility.spec.ts`

**Interfaces:**
- Consumes: `CompactWorkspaceView`, `ToolRail` in `bottom` mode
- Produces in `ReviewWorkspaceView`: `isCompact`, `isPhone`, `activeCompactView`, `phoneIssueSubview`
- Extends: `ReviewNavigation` event to `select(issueId: string, trigger: HTMLElement)`
- Produces: media queries `(max-width: 1279px)` and `(max-width: 767px)`

- [ ] **Step 1: Replace the old two-tab test with failing bottom-navigation tests**

```ts
it('uses five-entry bottom navigation at compact widths and preserves panel state', async () => {
  const restoreViewport = mockViewportWidth(1024)
  try {
    const wrapper = mountReviewWorkspaceWithConfig({ attachTo: document.body })
    await flushPromises()
    const nav = wrapper.get('nav[aria-label="工作台视图"]')

    expect(nav.findAll('button')).toHaveLength(5)
    await nav.get('[data-tool="search"]').trigger('click')
    await wrapper.get('[aria-label="查找内容"]').setValue('第一')
    await nav.get('[data-tool="document"]').trigger('click')
    await nav.get('[data-tool="search"]').trigger('click')

    expect((wrapper.get('[aria-label="查找内容"]').element as HTMLInputElement).value).toBe('第一')
  } finally {
    restoreViewport()
  }
})

it('uses a phone issue-detail subview and restores list focus on return', async () => {
  const restoreViewport = mockViewportWidth(390)
  try {
    const wrapper = mountReviewWorkspaceWithConfig({ attachTo: document.body })
    await flushPromises()
    await wrapper.get('[data-tool="issues"]').trigger('click')
    const issue = wrapper.get('[data-issue-id="issue-2"]')
    await issue.trigger('click')

    expect(wrapper.get('[data-testid="phone-issue-details"]').isVisible()).toBe(true)
    await wrapper.get('[aria-label="返回问题列表"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('nav[aria-label="问题筛选"]').isVisible()).toBe(true)
    expect(document.activeElement).toBe(issue.element)
  } finally {
    restoreViewport()
  }
})
```

Update `WorkspaceView.spec.ts` to assert that completed upload still opens the review workspace and that the new document header contains the source name.

- [ ] **Step 2: Run compact integration tests and verify they fail**

Run:

```powershell
Set-Location apps\web
npm test -- ReviewWorkspace.spec.ts WorkspaceView.spec.ts reviewAccessibility.spec.ts
```

Expected: FAIL because the old `文档/问题` tab flow and 1100px query remain.

- [ ] **Step 3: Implement responsive composition and focus restoration**

```ts
const COMPACT_QUERY = '(max-width: 1279px)'
const PHONE_QUERY = '(max-width: 767px)'
const isCompact = ref(compactMediaQuery?.matches ?? false)
const isPhone = ref(phoneMediaQuery?.matches ?? false)
const activeCompactView = ref<CompactWorkspaceView>('document')
const phoneIssueSubview = ref<'list' | 'details'>('list')
const lastPhoneIssueTrigger = ref<HTMLElement | null>(null)

function activateCompactView(tool: WorkspaceTool): void {
  activeCompactView.value = tool
  if (tool === 'issues') phoneIssueSubview.value = 'list'
}

function openPhoneIssue(issueId: string, trigger: EventTarget | null): void {
  selectIssueAndShowDetails(issueId)
  if (!isPhone.value) return
  lastPhoneIssueTrigger.value = trigger instanceof HTMLElement ? trigger : null
  phoneIssueSubview.value = 'details'
}

function returnToPhoneIssueList(): void {
  phoneIssueSubview.value = 'list'
  void nextTick(() => lastPhoneIssueTrigger.value?.focus())
}
```

Add a small `ReviewNavigation` click handler that validates `event.currentTarget instanceof HTMLElement` and emits both the issue ID and triggering issue-card element. Desktop handlers may ignore the second argument; compact handlers pass it to `openPhoneIssue` so returning can restore real focus.

At `768–1279px`, show exactly one main view: document, issue workspace (list plus details), search, or batch. At `≤767px`, issue mode shows either the list or details with a 44px “返回问题列表” button. Render `CheckerFailureNotice` before `ReviewNavigation` in both compact issue layouts so partial checker failures remain visible after toolbar removal. Keep the `ToolRail` bottom navigation mounted and place export as its fifth action. Register and remove both modern and legacy `MediaQueryList` listeners on unmount.

Change `WorkspaceView.vue`’s review breakpoint from `1100px` to `1279px`; do not reintroduce an upload-page constraint into review mode. Ensure compact panel content leaves space for the bottom navigation and never hides the last control.

- [ ] **Step 4: Run compact, upload integration, and build checks**

Run:

```powershell
Set-Location apps\web
npm test -- ReviewWorkspace.spec.ts WorkspaceView.spec.ts reviewAccessibility.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit responsive navigation**

```powershell
git add apps\web\src\components\review\ReviewNavigation.vue apps\web\src\views\ReviewWorkspaceView.vue apps\web\src\views\WorkspaceView.vue apps\web\tests\ReviewWorkspace.spec.ts apps\web\tests\WorkspaceView.spec.ts apps\web\tests\reviewAccessibility.spec.ts
git commit -m "Add compact review workspace navigation" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 8: Browser Geometry Regression Suite

**Files:**
- Modify: `apps\web\package.json`
- Modify: `apps\web\package-lock.json`
- Create: `apps\web\playwright.config.ts`
- Create: `apps\web\tests\fixtures\review-workspace.html`
- Create: `apps\web\tests\fixtures\reviewWorkspaceHarness.ts`
- Create: `apps\web\tests\layout\reviewWorkspaceLayout.spec.ts`

**Interfaces:**
- Produces: `npm run test:layout`
- Produces: deterministic browser fixture at `/tests/fixtures/review-workspace.html`

- [ ] **Step 1: Add the Playwright script and dependency**

```json
{
  "scripts": {
    "test:layout": "playwright test --config playwright.config.ts"
  },
  "devDependencies": {
    "@playwright/test": "^1.54.0"
  }
}
```

Run:

```powershell
Set-Location apps\web
npm install
npx playwright install chromium
```

Expected: `package-lock.json` updates and Chromium installs successfully.

- [ ] **Step 2: Create a deterministic Vite-only review harness**

```html
<!-- apps\web\tests\fixtures\review-workspace.html -->
<!doctype html>
<html lang="zh-CN">
  <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
  <body><div id="app"></div><script type="module" src="./reviewWorkspaceHarness.ts"></script></body>
</html>
```

```ts
// apps\web\tests\fixtures\reviewWorkspaceHarness.ts
import { createApp } from 'vue'
import { analysisApiKey } from '../../src/api/analysis'
import { exportsApiKey } from '../../src/api/exports'
import ReviewWorkspaceView from '../../src/views/ReviewWorkspaceView.vue'

const app = createApp(ReviewWorkspaceView, {
  jobId: 'layout-job',
  sourceName: '翻译服务合同.docx',
  fileType: 'docx'
})
app.provide(analysisApiKey, {
  getSummary: async () => ({
    job_id: 'layout-job',
    status: 'completed',
    total_issues: 12,
    by_category: { character: 2, vocabulary: 2, sentence: 2, format: 2, discourse: 2, security: 2 },
    by_severity: { error: 2, warning: 8, info: 2 },
    by_decision: { accepted: 0, ignored: 0, custom: 0, unreviewed: 12 },
    checker_failures: {}
  }),
  getDocumentPage: async () => ({
    job_id: 'layout-job',
    status: 'completed',
    document_id: 'document-1',
    file_type: 'docx',
    source_name: '翻译服务合同.docx',
    version: 1,
    metadata: {},
    blocks: Array.from({ length: 30 }, (_, index) => ({
      block_id: `block-${index}`,
      kind: 'paragraph',
      text: `第 ${index + 1} 段合同内容与核验文本。`,
      page: null,
      paragraph_index: index,
      parent_id: null,
      style: {},
      source_locator: {}
    })),
    total_blocks: 30,
    next_cursor: null,
    checker_failures: {}
  }),
  getIssues: async () => ({ job_id: 'layout-job', status: 'completed', total: 0, items: [], next_cursor: null, checker_failures: {} }),
  putDecisions: async () => ({ outcomes: [] })
})
app.provide(exportsApiKey, {
  create: async () => { throw new Error('Not used in layout tests') },
  get: async () => { throw new Error('Not used in layout tests') },
  downloadUrl: () => ''
})
app.mount('#app')
```

Add minimal body reset styles in the fixture so the review component, rather than browser defaults, owns the viewport. Keep this test entry disconnected from `apps\web\src\main.ts` so production output cannot select fixture data.

- [ ] **Step 3: Write failing real-browser geometry assertions**

```ts
// apps\web\tests\layout\reviewWorkspaceLayout.spec.ts
import { expect, test } from '@playwright/test'

const desktopSizes = [
  { width: 1280, height: 800 },
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 }
]

for (const viewport of desktopSizes) {
  test(`desktop geometry ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await page.goto('/tests/fixtures/review-workspace.html')
    const rail = page.locator('[data-layout="rail"]')
    const document = page.locator('.document-viewer')
    const inspector = page.locator('.context-inspector')
    const [railBox, documentBox, inspectorBox] = await Promise.all([
      rail.boundingBox(), document.boundingBox(), inspector.boundingBox()
    ])

    expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true)
    expect(railBox?.width).toBe(64)
    expect(documentBox!.width).toBeGreaterThan(inspectorBox!.width)
    expect(documentBox!.x).toBeGreaterThan(railBox!.x + railBox!.width)
    expect(inspectorBox!.x).toBeGreaterThanOrEqual(documentBox!.x + documentBox!.width)
  })
}

test('switches exactly at the 1279/1280 boundary', async ({ page }) => {
  await page.setViewportSize({ width: 1279, height: 800 })
  await page.goto('/tests/fixtures/review-workspace.html')
  await expect(page.locator('[data-layout="bottom"]')).toBeVisible()
  await page.setViewportSize({ width: 1280, height: 800 })
  await expect(page.locator('[data-layout="rail"]')).toBeVisible()
})

test('keeps search controls horizontal and dialogs within compact viewports', async ({ page }) => {
  for (const viewport of [{ width: 768, height: 1024 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await page.goto('/tests/fixtures/review-workspace.html')
    await page.getByRole('button', { name: '查找' }).click()
    await expect(page.getByLabel('查找内容')).toBeInViewport()
    expect(await page.getByRole('button', { name: '下一处' }).evaluate(
      (node) => getComputedStyle(node).writingMode
    )).toBe('horizontal-tb')
    await page.getByRole('button', { name: '导出' }).click()
    await expect(page.getByRole('dialog', { name: '导出文件' })).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
})
```

- [ ] **Step 4: Configure and run the layout suite**

```ts
// apps\web\playwright.config.ts
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/layout',
  use: { baseURL: 'http://127.0.0.1:4173', ...devices['Desktop Chrome'] },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: false
  }
})
```

Run:

```powershell
Set-Location apps\web
npm run test:layout
```

Expected: all required viewport cases PASS with no overlap, clipping, outer desktop scroll, vertical button text, or out-of-viewport dialog.

- [ ] **Step 5: Commit browser layout coverage**

```powershell
git add apps\web\package.json apps\web\package-lock.json apps\web\playwright.config.ts apps\web\tests\fixtures\review-workspace.html apps\web\tests\fixtures\reviewWorkspaceHarness.ts apps\web\tests\layout\reviewWorkspaceLayout.spec.ts
git commit -m "Add browser layout tests for review workspace" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 9: Visual-System Cleanup and Full Regression

**Files:**
- Modify: `apps\web\src\views\ReviewWorkspaceView.vue`
- Modify: `apps\web\src\components\review\ToolRail.vue`
- Modify: `apps\web\src\components\review\WorkspaceSidePanel.vue`
- Modify: `apps\web\src\components\review\ContextInspector.vue`
- Modify: `apps\web\src\components\review\DocumentHeader.vue`
- Modify: `apps\web\src\components\review\CheckerFailureNotice.vue`
- Modify: `apps\web\src\components\review\ReviewNavigation.vue`
- Modify: `apps\web\src\components\review\BatchActions.vue`
- Modify: `apps\web\src\components\review\FindReplace.vue`
- Modify: `apps\web\src\components\review\IssuePanel.vue`
- Modify: `apps\web\src\components\review\ExportPanel.vue`
- Modify: `apps\web\src\components\review\DocumentViewer.vue`
- Modify: `apps\web\tests\reviewAccessibility.spec.ts`

**Interfaces:**
- No new interfaces; this task normalizes final CSS and verifies the complete approved behavior.

- [ ] **Step 1: Tighten CSS contract tests before cleanup**

```ts
it('uses one review visual system without nested card overrides', () => {
  expect(ReviewWorkspaceViewSource).toContain('--review-accent:')
  expect(ReviewWorkspaceViewSource).toContain('--review-space-4: 16px')
  expect(ReviewWorkspaceViewSource).toContain('--review-panel-radius:')
  expect(ReviewWorkspaceViewSource).toContain('white-space: nowrap')
  expect(ReviewWorkspaceViewSource).not.toContain(':has(')
  expect(ReviewWorkspaceViewSource).not.toContain('display: contents')
  expect(FindReplaceSource).not.toContain('@media (min-width: 981px)')
  expect(BatchActionsSource).not.toContain('@media (min-width: 981px)')
})
```

Also update the semantic DOM-order test to expect desktop order `审阅工具`, active left panel, `文档内容`, and `上下文工具`, and retain the existing visible severity text assertions.

- [ ] **Step 2: Run accessibility tests and verify stale styles are detected**

Run:

```powershell
Set-Location apps\web
npm test -- reviewAccessibility.spec.ts
```

Expected: FAIL until old colors, radii, media rules, and cross-component selectors are removed.

- [ ] **Step 3: Normalize the final visual system**

Define inherited custom properties on `.review-workspace`:

```css
.review-workspace {
  --review-accent: #4f5fd5;
  --review-accent-soft: #eef0ff;
  --review-surface: #ffffff;
  --review-canvas: #f3f5f8;
  --review-border: #dfe3ea;
  --review-text: #202939;
  --review-text-muted: #667085;
  --review-danger: #a53636;
  --review-space-1: 4px;
  --review-space-2: 8px;
  --review-space-3: 12px;
  --review-space-4: 16px;
  --review-panel-radius: 12px;
}
```

Replace duplicated component literals with these variables. Keep only one surface per major region, use separators/spacing inside regions, restrict severity colors to labels/highlights, and remove obsolete `1100px`, `1101px`, `980px`, and `981px` review-layout rules. Add `white-space: nowrap` to action buttons and labels where wrapping would break meaning. Preserve all existing highlight severity selectors and focus-visible styling.

- [ ] **Step 4: Run the complete frontend verification**

Run:

```powershell
Set-Location apps\web
npm test
npm run test:layout
npm run build
```

Expected: all Vitest tests PASS, all Playwright layout tests PASS, TypeScript compilation PASS, and the production Vite build completes.

- [ ] **Step 5: Check repository hygiene and commit the final cleanup**

Run:

```powershell
git -c core.whitespace=cr-at-eol diff --check
git --no-pager status --short
```

Expected: no whitespace errors; only the intended review-workspace files are modified, and `.superpowers\brainstorm` artifacts are absent from status.

```powershell
git add apps\web\src apps\web\tests\reviewAccessibility.spec.ts
git commit -m "Polish modern review workspace layout" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
