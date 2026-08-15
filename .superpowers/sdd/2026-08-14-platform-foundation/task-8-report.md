# Task 8 Report

## RED / GREEN
- RED focused slice:
  - Command: `npm test -- WorkspaceView.spec.ts jobsApi.spec.ts`
  - Result: `2 failed suites, no tests collected`
  - Proven gaps:
    - `frontend/src/api/jobs.ts` did not exist.
    - `frontend/src/views/WorkspaceView.vue` and the Vue workspace slice did not exist.
- GREEN focused slice:
  - Same command now passes with `2 passed, 12 tests`.
- GREEN runnable frontend suite:
  - Command: `npm test`
  - Result: `2 passed, 12 tests`.
- GREEN build:
  - Command: `npm run build`
  - Result: `vite build` completed successfully after `vue-tsc -b`.

## npm install summary
- Command: `npm install`
- Result: `added 172 packages, and audited 173 packages in 1m`
- Warnings observed:
  - `whatwg-encoding@3.1.1` deprecated upstream
  - `glob@10.5.0` deprecated upstream
  - `esbuild@0.25.12` listed by `npm allow-scripts` as a pending postinstall approval note
- No vulnerabilities were reported.

## Implementation notes
- Added a Vue 3 + TypeScript + Vite frontend slice under `frontend/` with a relative `/api` base and Vite proxy to `http://localhost:8000`.
- Added a concrete `JobsApi` that uploads with `fetch`, parses shaped backend errors from `detail.message`, and subscribes with native `EventSource`.
- `EventSource` listeners now close on `done`, synthesize durable `expired` state on `expired`, and suppress late error noise after closure.
- `WorkspaceView` injects the API for tests, closes prior subscriptions before a new upload and on unmount, and preserves the last terminal state on screen.
- `UploadWorkspace` validates `.docx`, `.pdf`, `.txt`, and `<= 25 MiB` before any API call.

## Files
- `.superpowers/sdd/2026-08-14-platform-foundation/task-8-report.md`
- `frontend/index.html`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/tsconfig.json`
- `frontend/vite.config.ts`
- `frontend/src/App.vue`
- `frontend/src/main.ts`
- `frontend/src/vite-env.d.ts`
- `frontend/src/api/jobs.ts`
- `frontend/src/components/JobProgress.vue`
- `frontend/src/components/UploadWorkspace.vue`
- `frontend/src/types/jobs.ts`
- `frontend/src/views/WorkspaceView.vue`
- `frontend/tests/WorkspaceView.spec.ts`
- `frontend/tests/jobsApi.spec.ts`

## Self-review
- Confirmed the status union matches the backend exactly: `queued`, `upload_validated`, `parsing`, `checking_format`, `checking_sensitive`, `checking_chinese`, `checking_english`, `completed`, `partial`, `failed`, `expired`.
- Confirmed validation blocks unsupported extensions and files above exactly `25 * 1024 * 1024` bytes before `createJob`.
- Confirmed terminal `completed` state remains visible after SSE completion and ignores late subscription errors.
- Confirmed no server or document strings are rendered with `v-html` or `innerHTML`.
- Confirmed production wiring provides a concrete `JobsApi`, while tests inject fakes through Vue provide/inject.

## Concerns
- Full frontend verification passes, but there is not yet a browser E2E harness in this task to exercise the real FastAPI + SSE integration end-to-end.
- `npm install` emits upstream deprecation warnings for transient packages that were not introduced by custom dependency choices in this slice.
