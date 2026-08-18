# Task 6 Report

## Files

- `apps/web/src/components/review/ExportPanel.vue`
- `apps/web/src/components/review/ReviewToolbar.vue`
- `apps/web/src/views/ReviewWorkspaceView.vue`
- `apps/web/tests/ReviewWorkspace.spec.ts`

## Contract Choices

- Reused the existing `ExportsApi` client and `ExportCreateResponse` / `ExportResponse` contract from `apps/web/src/api/exports.ts` and `apps/web/src/types/exports.ts`.
- Reused backend-owned fields exactly: `warnings`, `confirm_warnings`, `dispatch_status`, `status`, `error_code`, `error_message`, and `expires_at`.
- Used `ExportsApi.get(jobId, exportId)` for lightweight status polling.
- Enforced source restrictions from the established contract: TXT/DOCX offer `modified_document`, `html_report`, `pdf_report`; PDF offers only `html_report` and `pdf_report`.
- Required explicit user confirmation for `export_confirmation_required` warnings before resubmitting `confirm_warnings: true`.

## RED

Command:

```powershell
Set-Location apps\web; npm test -- --run tests/ReviewWorkspace.spec.ts
```

Output:

```text
> text-verification-web@0.1.0 test
> vitest run --run tests/ReviewWorkspace.spec.ts

RUN  v3.2.7 C:/Work/text-verification/apps/web

❯ tests/ReviewWorkspace.spec.ts (38 tests | 5 failed)
× ReviewWorkspaceView > does not offer modified document export for PDF
  → Unable to get option[value="html_report"] ...
× ReviewWorkspaceView > creates, polls, and exposes a completed export download
  → Unable to get select[name="export-type"] ...
× ReviewWorkspaceView > surfaces terminal export failures and lets the user retry
  → Unable to get select[name="export-type"] ...
× ReviewWorkspaceView > stops export polling when the workspace unmounts
  → Unable to get select[name="export-type"] ...
```

## GREEN

Command:

```powershell
Set-Location apps\web; npm test -- --run tests/ReviewWorkspace.spec.ts
```

Output:

```text
> text-verification-web@0.1.0 test
> vitest run --run tests/ReviewWorkspace.spec.ts

RUN  v3.2.7 C:/Work/text-verification/apps/web

✓ tests/ReviewWorkspace.spec.ts (38 tests)

Test Files  1 passed (1)
     Tests  38 passed (38)
Duration  5.03s
```

## Build Verification

Command:

```powershell
Set-Location apps\web; npm run build
```

Output:

```text
> text-verification-web@0.1.0 build
> vue-tsc -b && vite build

vite v6.4.3 building for production...
✓ built in 1.35s
```

## Self-Review

- Kept Task 6 isolated to the review workspace export surface; did not touch `apps/web/src/App.vue` or `apps/web/src/components/JobProgress.vue`.
- Added focused TDD coverage for file-type restrictions, queued→processing→completed polling/download, failed retry, unmount polling cancellation, and structured warning confirmation.
- Polling runs on a 2-second timer for queued/processing exports, stops on terminal states and unmount, and exposes explicit retry/error states in Simplified Chinese.
- Warnings are shown before download, failed/expired exports do not render as successful downloads, and the new controls include visible focus styling.

## Concerns

- Expiry is derived from `expires_at` on the client and refreshed when the component rerenders or receives status updates; the server download endpoint remains the final authority for late expiry.
