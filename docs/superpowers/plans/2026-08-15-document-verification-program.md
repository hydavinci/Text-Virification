# Document Verification Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coordinate the four independently testable plans that deliver the approved document verification business loop.

**Architecture:** Work proceeds in dependency order: normalized analysis first, review decisions second, exports third, and the complete frontend workspace last. Each phase ends with passing tests and a review gate before the next phase starts.

**Tech Stack:** Python 3.12, FastAPI, PostgreSQL, Redis/Celery, Vue 3, TypeScript, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-15-document-review-workspace-design.md`

## Global Constraints

- Execute each linked plan with TDD and its own review gate.
- Do not begin a dependent phase while its prerequisite phase has failing tests.
- Preserve unrelated uncommitted working-tree changes.
- Use an isolated worktree at execution time.

---

### Task 1: Core analysis pipeline

**Files:**
- Plan: `docs/superpowers/plans/2026-08-15-core-analysis-pipeline.md`

**Interfaces:**
- Produces normalized document, issue, summary, and checker-failure APIs required by every later phase.

- [ ] Execute every task and phase-acceptance command in `2026-08-15-core-analysis-pipeline.md`.
- [ ] Request code review and resolve all Critical and Important findings.
- [ ] Confirm the backend suite, Ruff, and mypy pass before Task 2.

### Task 2: Issue review decisions

**Files:**
- Plan: `docs/superpowers/plans/2026-08-15-issue-review-decisions.md`

**Interfaces:**
- Consumes core issue persistence and APIs.
- Produces versioned decision and decision-aware summary APIs.

- [ ] Execute every task and phase-acceptance command in `2026-08-15-issue-review-decisions.md`.
- [ ] Request code review and resolve all Critical and Important findings.
- [ ] Confirm mixed batch outcomes and stale-version conflicts before Task 3.

### Task 3: Document exports

**Files:**
- Plan: `docs/superpowers/plans/2026-08-15-document-exports.md`

**Interfaces:**
- Consumes parsed documents, issues, and decisions.
- Produces modified TXT/DOCX files and HTML/PDF reports.

- [ ] Execute every task and phase-acceptance command in `2026-08-15-document-exports.md`.
- [ ] Request code review and resolve all Critical and Important findings.
- [ ] Confirm parser/export round trips and export warnings before Task 4.

### Task 4: Review workspace UI

**Files:**
- Plan: `docs/superpowers/plans/2026-08-15-review-workspace-ui.md`

**Interfaces:**
- Consumes all backend analysis, decision, and export APIs.
- Produces the approved responsive three-column user experience.

- [ ] Execute every task and phase-acceptance command in `2026-08-15-review-workspace-ui.md`.
- [ ] Request code review and resolve all Critical and Important findings.
- [ ] Run frontend tests/build, backend E2E, Compose health, and live workflow smoke tests.
