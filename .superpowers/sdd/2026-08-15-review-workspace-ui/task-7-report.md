# Task 7 report — responsive tabs, accessibility, and end-to-end flow

## Status

- Implemented Task 7 UI/workflow updates in the current workspace on `task-3-review-workspace`.
- Integrated the preserved baseline edits in `apps/web/src/App.vue` and `apps/web/src/components/JobProgress.vue` into Task 7 validation and commit scope.
- Kept desktop review DOM order `问题筛选 -> 文档内容 -> 问题详情` and added max-width 900px `文档 / 问题` tabs with focus preservation.
- Added keyboard `j`/`k` issue navigation guards for editable controls and preserved issue/highlight synchronization.
- Added explicit severity icon+text presentation, visible focus handling, 44px primary touch targets, and reduced-motion coverage.
- Extended TXT lifecycle E2E from upload options through review decision and HTML report download with condition polling.

## Files

- `apps/web/src/App.vue`
- `apps/web/src/components/JobProgress.vue`
- `apps/web/src/components/review/BatchActions.vue`
- `apps/web/src/components/review/DocumentViewer.vue`
- `apps/web/src/components/review/ExportPanel.vue`
- `apps/web/src/components/review/FindReplace.vue`
- `apps/web/src/components/review/IssuePanel.vue`
- `apps/web/src/components/review/ReviewNavigation.vue`
- `apps/web/src/components/review/ReviewToolbar.vue`
- `apps/web/src/components/review/severity.ts`
- `apps/web/src/views/ReviewWorkspaceView.vue`
- `apps/web/tests/ReviewWorkspace.spec.ts`
- `apps/web/tests/WorkspaceView.spec.ts`
- `apps/web/tests/reviewAccessibility.spec.ts`
- `apps/web/tsconfig.json`
- `apps/api/tests/e2e/test_upload_lifecycle.py`
- `.superpowers/sdd/2026-08-15-review-workspace-ui/task-7-report.md`

## RED evidence

Command:

```powershell
Set-Location C:\Work\text-verification\apps\web
npm test -- --run tests/reviewAccessibility.spec.ts tests/ReviewWorkspace.spec.ts
```

Observed product RED before production changes:

- `ReviewWorkspaceView > uses 文档/问题 tabs on narrow screens and preserves focus after switching`
  - `Unable to get [role="tab"][aria-controls="review-issues-panel"]`
- `ReviewWorkspaceView > moves between issues with j/k shortcuts and keeps selection synchronized`
  - `expected 'false' to be 'true' // Object.is equality`

Reason: mobile tabs/focus handling and keyboard navigation behavior required by Task 7 were absent.

## GREEN commands / results

### Focused Task 7 frontend specs

```powershell
Set-Location C:\Work\text-verification\apps\web
npm test -- --run tests/reviewAccessibility.spec.ts tests/ReviewWorkspace.spec.ts
```

Result: PASS — `2` files, `44` tests passed.

### Full frontend suite

```powershell
Set-Location C:\Work\text-verification\apps\web
npm test
```

Result: PASS — `6` files, `88` tests passed.

### Production build

```powershell
Set-Location C:\Work\text-verification\apps\web
npm run build
```

Result: PASS — `vue-tsc -b && vite build` succeeded; Vite emitted `dist/index.html`, `dist/assets/index-CwmoEJCA.css`, and `dist/assets/index-D2Rv8qQT.js`.

### Targeted backend E2E

Primary required Compose rebuild attempt was blocked externally (see blocker below), so I used a deterministic fallback: two temporary containers based on the already-available backend image, mounted to the current source tree, attached to the Compose network, and pointed at isolated Redis DB `1` plus a temporary shared storage path. That allowed validation of current source without downloading new packages.

Validation command:

```powershell
Set-Location C:\Work\text-verification
$env:LIVE_API_URL='http://127.0.0.1:8001'
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\e2e\test_upload_lifecycle.py -v
```

Result: PASS — `3` tests passed.

Validated flow in `test_txt_upload_options_review_and_html_report_download`:

- TXT upload with explicit `scenario` and `enabled_categories`
- condition-polling until terminal analysis completion
- summary retrieval
- document retrieval
- paged issue retrieval (`limit=1` plus follow-up cursor request)
- decision submission
- HTML export creation
- condition-polling until export completion
- download and content verification (`问题报告`, file name, enabled categories, issue content)

## Compose status / health evidence

### Rebuild/start command

```powershell
docker compose -f C:\Work\text-verification\infra\compose.yaml up --build -d
```

Result: BLOCKED by external network/package availability during image build.

Exact blocker evidence:

- backend build step `RUN python -m pip wheel --wheel-dir /wheels "./apps/api[dev]"`
- repeated TLS handshake failures fetching `setuptools-84.0.0` metadata from `files.pythonhosted.org`
- final error:

```text
ERROR: Could not install packages due to an OSError: HTTPSConnectionPool(host='files.pythonhosted.org', port=443): Max retries exceeded ... [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE]
```

### Existing Compose stack status after blocked rebuild

```powershell
docker compose -f C:\Work\text-verification\infra\compose.yaml ps
```

Observed services still running:

- `api` — `Up 25 hours (healthy)`
- `beat` — `Up 25 hours`
- `postgres` — `Up 2 days (healthy)`
- `redis` — `Up 2 days (healthy)`
- `web` — `Up 25 hours`
- `worker` — `Up 25 hours`

### Existing Compose health endpoint

```powershell
curl.exe --fail http://127.0.0.1:8080/api/v1/health
```

Result: PASS — `{"status":"ok","service":"text-verification-api","version":"0.1.0"}`.

## Integrated baseline

- Preserved and included the existing uncommitted visual baseline in `apps/web/src/App.vue` and `apps/web/src/components/JobProgress.vue`.
- Did not revert or overwrite those files.
- Validated them together with the Task 7 frontend suite/build and included them in final commit scope.

## Self-review

- Confirmed mobile tabs only appear at `max-width: 900px` and keep focus on the selected tab after switching.
- Confirmed desktop review layout still renders `nav`, `article`, `aside` in document-centered DOM order.
- Confirmed `j`/`k` navigation updates selected issue + highlight together and does not fire while typing in search/custom-replacement controls.
- Confirmed severity display now includes icon + text in both the issue list and detail panel.
- Confirmed reduced-motion and focus-visible coverage are exercised by dedicated accessibility specs.
- Confirmed TXT lifecycle E2E now covers options, analysis polling, blocks/issues, decision, HTML report creation, and downloaded report content.

## Concerns

- `docker compose up --build -d` did not complete because external package downloads from `files.pythonhosted.org` failed with TLS handshake errors. Current source was still validated deterministically via temporary source-mounted backend containers, but the long-running Compose services remain the pre-existing images rather than a fresh rebuild from this task's source.
