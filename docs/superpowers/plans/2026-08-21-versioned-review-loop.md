# Versioned Review Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persistent, versioned review loop with paragraph editing, reanalysis, multi-suggestion decisions, reversible batch history, enhanced draft-only replacement, and preview/export parity.

**Architecture:** Introduce immutable document versions beside the current job lifecycle, then migrate analysis reads and writes to version-scoped repositories without discarding historical data. Reanalysis uses a dedicated Celery task and version SSE stream; the Vue workspace composes focused version, draft, decision, preview, and search state modules while preserving the existing C2 single-screen shell.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL, Celery/Redis, Vue 3, TypeScript 5.7, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-21-versioned-review-loop-design.md`

## Global Constraints

- Successful document versions are immutable; editing and reanalysis always create a new version.
- Issues, suggestions, decisions, checker failures, and operation history are scoped to one document version.
- The active version changes only in the same transaction that marks a new analysis `succeeded`.
- Analysis failure keeps the prior active version and the server-side draft.
- Modified preview and modified-document export must use the same derived-content function and immutable decision snapshot hash.
- Accepted decisions store the final replacement text; no later code may reselect a preferred suggestion.
- Overlapping accepted replacements return an explicit `409`; no replacement is silently skipped or reordered.
- Decision batches are atomic. Any stale, missing, or overlapping item rolls back the complete batch.
- Draft updates use optimistic revision checks; stale writes return `409` without losing submitted text.
- Replacement is available only in draft editing mode. Review mode remains find-only.
- The C2 workspace remains one browser-height screen with independently scrolling panels at desktop, tablet, and phone breakpoints.
- Existing upload, initial analysis, export recovery, task expiry, focus restoration, and “处理其他文件” behavior must remain operational.
- Do not add a rich-text editor or a new JavaScript state-management dependency.
- Keep the existing limits of 500 decisions per batch and 10,000 Unicode code points per replacement.

---

## File Structure

### Backend files to create

- `apps/api/alembic/versions/0011_versioned_review_loop.py` — additive schema migration and legacy revision-1 backfill.
- `apps/api/src/text_verification/domain/revisions.py` — version and draft value objects.
- `apps/api/src/text_verification/domain/review_operations.py` — suggestions, decision commands, operation batches, and conflict types.
- `apps/api/src/text_verification/domain/derived_content.py` — replacement application, snapshot hashing, and character-level Myers diff.
- `apps/api/src/text_verification/infrastructure/revision_repository.py` — versions, draft persistence, activation, and version events.
- `apps/api/src/text_verification/infrastructure/review_operation_repository.py` — atomic decisions, overlap detection, history, and undo.
- `apps/api/src/text_verification/api/routes/versions.py` — version list, draft CRUD, reanalysis dispatch, derived views, and version SSE.
- `apps/api/src/text_verification/api/routes/review_history.py` — operation history and undo endpoints.
- `apps/api/src/text_verification/workers/reanalysis_tasks.py` — retry-safe draft reanalysis task.
- `apps/api/tests/unit/domain/test_derived_content.py` — replacement, hashing, overlap, and diff unit tests.
- `apps/api/tests/integration/test_revision_repository.py` — immutable version and optimistic draft repository tests.
- `apps/api/tests/integration/test_versions_api.py` — versions, drafts, derived views, and version SSE tests.
- `apps/api/tests/integration/test_review_history_api.py` — atomic decision history and undo tests.
- `apps/api/tests/integration/test_reanalysis_task.py` — worker success, failure, retry, and atomic activation tests.

### Backend files to modify

- `apps/api/src/text_verification/domain/issues.py` — final replacement and suggestion-aware decision shape.
- `apps/api/src/text_verification/domain/exports.py` — schema-v2 version and decision snapshot metadata.
- `apps/api/src/text_verification/infrastructure/orm.py` — new ORM rows and version foreign keys.
- `apps/api/src/text_verification/infrastructure/analysis_repositories.py` — version-scoped persistence and queries.
- `apps/api/src/text_verification/infrastructure/decision_repository.py` — replace non-atomic legacy writes with the operation repository facade.
- `apps/api/src/text_verification/api/dependencies.py` — revision and operation repository providers.
- `apps/api/src/text_verification/api/router.py` — register version and history routes.
- `apps/api/src/text_verification/api/routes/analysis.py` — accept optional `version_id` and return active version metadata.
- `apps/api/src/text_verification/api/routes/decisions.py` — atomic batch contract and operation batch ID.
- `apps/api/src/text_verification/api/routes/exports.py` — capture version ID and derived decision hash.
- `apps/api/src/text_verification/exporters/replacements.py` — consume stored final replacement text only.
- `apps/api/src/text_verification/workers/pipeline.py` — persist initial analysis as revision 1.
- `apps/api/src/text_verification/workers/tasks.py` — construct version-aware initial pipeline.
- Existing backend tests under `apps/api/tests/` — update fixtures and legacy expectations to version-scoped behavior.

### Frontend files to create

- `apps/web/src/types/revisions.ts` — version, draft, derived view, diff, and history DTOs.
- `apps/web/src/api/revisions.ts` — versions, drafts, derived views, events, history, and undo client.
- `apps/web/src/composables/useDocumentVersions.ts` — active/history selection and reanalysis progress.
- `apps/web/src/composables/useEditDraft.ts` — server draft, dirty state, optimistic save, and replacement.
- `apps/web/src/composables/useDerivedPreview.ts` — original/modified/diff mode and stale response guards.
- `apps/web/src/composables/useReviewHistory.ts` — batches, 10-second undo notice, and long-term undo.
- `apps/web/src/components/review/VersionToolbar.vue` — version selector, view modes, and edit entry.
- `apps/web/src/components/review/DocumentEditor.vue` — paragraph editor and draft actions.
- `apps/web/src/components/review/DocumentDiff.vue` — accessible diff segment renderer.
- `apps/web/src/components/review/OperationHistory.vue` — operation batch list and undo controls.
- `apps/web/src/components/review/UndoToast.vue` — 10-second live-region undo action.
- `apps/web/tests/revisionsApi.spec.ts` — revision API serialization tests.
- `apps/web/tests/reviewEditing.spec.ts` — version, edit, preview, suggestion, search, and history component tests.

### Frontend files to modify

- `apps/web/src/main.ts` — provide the revisions API.
- `apps/web/src/types/analysis.ts` — version IDs, suggestion DTOs, final replacement decisions, and atomic response shape.
- `apps/web/src/types/review.ts` — `history` workspace tool and document view mode.
- `apps/web/src/api/analysis.ts` — version query parameters and new decision request fields.
- `apps/web/src/composables/useReviewWorkspace.ts` — orchestrate extracted composables and version-scoped loading.
- `apps/web/src/components/review/DocumentHeader.vue` — host version toolbar actions.
- `apps/web/src/components/review/DocumentViewer.vue` — delegate original, modified, diff, and edit rendering.
- `apps/web/src/components/review/IssuePanel.vue` — candidate selection/editing and restore-to-unreviewed action.
- `apps/web/src/components/review/FindReplace.vue` — regex, case, replace-current, clear, and keyboard controls.
- `apps/web/src/components/review/ToolRail.vue` — history tool.
- `apps/web/src/components/review/workspaceLayout.ts` — history workspace types.
- `apps/web/src/views/ReviewWorkspaceView.vue` — wire modes, history panel, undo toast, and draft navigation guard.
- `apps/web/src/views/WorkspaceView.vue` — prevent file switching with unresolved local draft edits.
- Existing Vitest and Playwright tests under `apps/web/tests/` — preserve prior layout and accessibility contracts.

---

### Task 1: Add the versioned review schema and domain contracts

**Files:**
- Create: `apps/api/alembic/versions/0011_versioned_review_loop.py`
- Create: `apps/api/src/text_verification/domain/revisions.py`
- Create: `apps/api/src/text_verification/domain/review_operations.py`
- Modify: `apps/api/src/text_verification/domain/issues.py`
- Modify: `apps/api/src/text_verification/infrastructure/orm.py`
- Modify: `apps/api/tests/unit/domain/test_models.py`

**Interfaces:**
- Produces: `DocumentVersionStatus`, `DocumentVersionRead`, `EditDraftRead`, `DraftBlock`, `SuggestionSource`, `IssueSuggestion`, `ReviewOperationBatchRead`.
- Produces: `DecisionCommand(issue_id, issue_version, expected_revision, action, replacement, suggestion_id)`, where `unreviewed` is a deletion command rather than a persisted row.
- Produces tables and foreign keys consumed by all later backend tasks.

- [ ] **Step 1: Write failing domain model tests**

Add tests proving accepted decisions require a non-empty final replacement, ignored decisions reject replacement/suggestion IDs, draft blocks reject duplicate IDs, and version states enforce failure fields:

```python
def test_accepted_decision_requires_final_replacement() -> None:
    with pytest.raises(ValidationError):
        DecisionCommand(
            issue_id=uuid4(),
            issue_version=1,
            expected_revision=0,
            action=DecisionAction.ACCEPTED,
            replacement=None,
            suggestion_id=None,
        )


def test_draft_rejects_duplicate_block_ids() -> None:
    block = DraftBlock(block_id="p-1", text="正文")
    with pytest.raises(ValidationError):
        EditDraftRead(
            draft_id=uuid4(),
            job_id=uuid4(),
            base_version_id=uuid4(),
            revision=1,
            blocks=[block, block],
            created_at=NOW,
            updated_at=NOW,
        )
```

- [ ] **Step 2: Run the model tests and confirm the new imports fail**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\domain\test_models.py -q
```

Expected: FAIL because `domain.revisions`, `DraftBlock`, and the new decision fields do not exist.

- [ ] **Step 3: Define the exact domain contracts**

Implement these public shapes:

```python
class DocumentVersionStatus(StrEnum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DraftBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_id: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=1_000_000)


class DecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issue_id: UUID
    issue_version: int = Field(gt=0)
    expected_revision: int = Field(ge=0)
    action: DecisionAction
    replacement: CustomReplacement | None = None
    suggestion_id: UUID | None = None
```

Change the command enum to:

```python
class DecisionAction(StrEnum):
    ACCEPTED = "accepted"
    IGNORED = "ignored"
    UNREVIEWED = "unreviewed"
```

Use only `accepted` and `ignored` as persisted decision states. `unreviewed` is accepted only as a command that removes the current decision through an operation batch. The migration converts legacy `custom` rows to `accepted` while preserving their replacement.

- [ ] **Step 4: Add the additive migration and ORM rows**

Create:

- `document_versions` with unique `(job_id, revision_number)` and optional parent;
- `document_version_events` with unique `(version_id, sequence)`;
- `edit_drafts` with unique active `(job_id, base_version_id)` and JSONB ordered blocks;
- `issue_suggestions`;
- `review_operation_batches`;
- `review_operation_items`;
- `jobs.active_version_id`;
- version foreign keys on documents, blocks, issues, checker failures, decisions, and exports;
- `issue_decisions.revision`, `final_replacement`, `suggestion_id`, and `operation_batch_id`.

Backfill each existing document as a succeeded revision 1, assign all related rows, convert legacy decisions, populate suggestions from `suggestion` followed by unique `alternatives`, and set `jobs.active_version_id`. Rebuild document, block, and checker-failure primary keys so multiple versions can retain identical block IDs.

- [ ] **Step 5: Exercise upgrade and downgrade against the integration schema**

Run:

```powershell
Push-Location apps\api
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_job_repository.py tests\integration\test_analysis_repository.py -q
Pop-Location
```

Expected after the implementation: PASS, with Alembic upgrading through revision `0011_versioned_review_loop`.

- [ ] **Step 6: Commit the schema boundary**

```powershell
git add apps\api\alembic\versions\0011_versioned_review_loop.py apps\api\src\text_verification\domain apps\api\src\text_verification\infrastructure\orm.py apps\api\tests\unit\domain\test_models.py
git commit -m "Add versioned review domain schema" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Persist immutable analysis versions

**Files:**
- Create: `apps/api/src/text_verification/infrastructure/revision_repository.py`
- Create: `apps/api/tests/integration/test_revision_repository.py`
- Modify: `apps/api/src/text_verification/infrastructure/analysis_repositories.py`
- Modify: `apps/api/src/text_verification/infrastructure/repositories.py`
- Modify: `apps/api/src/text_verification/api/dependencies.py`
- Modify: `apps/api/tests/integration/test_analysis_repository.py`
- Modify: `apps/api/tests/integration/test_job_repository.py`

**Interfaces:**
- Consumes: schema and `DocumentVersionRead` from Task 1.
- Produces: `create_queued_version(job_id: UUID, parent_version_id: UUID | None, reason: str, idempotency_key: str | None) -> DocumentVersionRead`.
- Produces: `mark_analyzing(version_id: UUID) -> DocumentVersionRead`, `complete_analysis(version_id: UUID, document: DocumentModel, issues: list[Issue], failures: dict[CheckCategory, CheckerFailure]) -> DocumentVersionRead`, and `fail_version(version_id: UUID, code: str, message: str) -> DocumentVersionRead`.
- Produces: `get_active_version(job_id: UUID) -> DocumentVersionRead | None` and `list_versions(job_id: UUID) -> list[DocumentVersionRead]`.
- Produces: version-scoped `AnalysisRepository.persist_version_analysis(version_id, document, issues, failures)` and read methods accepting `version_id`.

- [ ] **Step 1: Write repository tests for immutability and atomic activation**

Cover:

```python
def test_complete_analysis_activates_new_version_without_deleting_parent(
    db_session,
    seeded_job,
):
    revisions = RevisionRepository(db_session)
    analysis = AnalysisRepository(db_session)
    first = revisions.create_queued_version(
        seeded_job.job_id,
        parent_version_id=None,
        reason="upload",
        idempotency_key=None,
    )
    revisions.complete_analysis(first.version_id, seeded_job.document_v1, [], {})
    second = revisions.create_queued_version(
        seeded_job.job_id,
        first.version_id,
        reason="edited",
        idempotency_key="edit-1",
    )
    revisions.complete_analysis(second.version_id, seeded_job.document_v2, [], {})
    db_session.commit()

    assert revisions.get_active_version(seeded_job.job_id).version_id == second.version_id
    assert analysis.get_document(seeded_job.job_id, first.version_id) == seeded_job.document_v1
    assert analysis.get_document(seeded_job.job_id, second.version_id) == seeded_job.document_v2
```

Also test that completing a succeeded version raises `ImmutableDocumentVersionError` and a failed version never becomes active.

- [ ] **Step 2: Verify current destructive persistence fails the tests**

Run:

```powershell
Push-Location apps\api
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_revision_repository.py tests\integration\test_analysis_repository.py -q
Pop-Location
```

Expected: FAIL because `replace_analysis()` deletes the parent document and no revision repository exists.

- [ ] **Step 3: Implement version-scoped repositories**

Use one transaction and one lock order:

```python
def complete_analysis(
    self,
    version_id: UUID,
    document: DocumentModel,
    issues: list[Issue],
    failures: dict[CheckCategory, CheckerFailure],
) -> DocumentVersionRead:
    version = self._lock_version(version_id)
    job = JobRepository(self._session).lock_job(version.job_id)
    self._analysis.persist_version_analysis(version_id, document, issues, failures)
    version.status = DocumentVersionStatus.SUCCEEDED.value
    version.content_sha256 = normalized_document_sha256(document)
    version.completed_at = datetime.now(UTC)
    job.active_version_id = version_id
    self._session.flush()
    return _to_version_read(version)
```

All analysis reads take an explicit version ID internally. Existing public job-scoped calls resolve `jobs.active_version_id` to preserve current endpoints during rollout.

- [ ] **Step 4: Update legacy fixtures without weakening assertions**

Replace tests that expect old analysis rows to disappear with assertions that:

- the active version points at the newest success;
- the parent remains queryable;
- decisions remain attached to the parent;
- pagination and summaries include only the requested version.

- [ ] **Step 5: Run targeted repository tests**

Run:

```powershell
Push-Location apps\api
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_revision_repository.py tests\integration\test_analysis_repository.py tests\integration\test_decision_repository.py -q
Pop-Location
```

Expected: PASS.

- [ ] **Step 6: Commit immutable version persistence**

```powershell
git add apps\api\src\text_verification\infrastructure apps\api\src\text_verification\api\dependencies.py apps\api\tests\integration
git commit -m "Persist immutable analysis versions" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Add version listing and optimistic draft APIs

**Files:**
- Create: `apps/api/src/text_verification/api/routes/versions.py`
- Create: `apps/api/tests/integration/test_versions_api.py`
- Modify: `apps/api/src/text_verification/infrastructure/revision_repository.py`
- Modify: `apps/api/src/text_verification/api/router.py`
- Modify: `apps/api/src/text_verification/api/routes/analysis.py`

**Interfaces:**
- Produces: `GET /api/v1/jobs/{job_id}/versions`.
- Produces: `POST /api/v1/jobs/{job_id}/drafts`, `GET/PUT/DELETE /api/v1/jobs/{job_id}/drafts/{draft_id}`.
- Produces: optional `version_id` on document, issues, and summary reads.

- [ ] **Step 1: Write failing API tests**

Assert:

```python
def test_stale_draft_update_returns_current_revision_and_preserves_text(client, seeded_job):
    created = client.post(f"/api/v1/jobs/{seeded_job}/drafts", json={
        "base_version_id": str(active_version_id),
    }).json()
    saved = client.put(
        f"/api/v1/jobs/{seeded_job}/drafts/{created['draft_id']}",
        json={"expected_revision": 1, "blocks": [{"block_id": "p-1", "text": "服务器文本"}]},
    )
    stale = client.put(
        f"/api/v1/jobs/{seeded_job}/drafts/{created['draft_id']}",
        json={"expected_revision": 1, "blocks": [{"block_id": "p-1", "text": "本地文本"}]},
    )
    assert saved.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_draft_revision"
    assert stale.json()["detail"]["current_revision"] == 2
```

Also cover historical analysis reads, duplicate active draft creation returning the same draft, and deleting only the requested draft.

- [ ] **Step 2: Run tests and confirm routes are missing**

Run:

```powershell
Push-Location apps\api
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_versions_api.py -q
Pop-Location
```

Expected: FAIL with `404` responses.

- [ ] **Step 3: Implement repository draft operations**

Implement:

```python
def update_draft(
    self,
    job_id: UUID,
    draft_id: UUID,
    *,
    expected_revision: int,
    blocks: list[DraftBlock],
) -> EditDraftRead:
    row = self._lock_draft(job_id, draft_id)
    if row.revision != expected_revision:
        raise StaleDraftRevision(current_revision=row.revision)
    row.blocks_json = [block.model_dump(mode="json") for block in blocks]
    row.revision += 1
    row.content_sha256 = draft_blocks_sha256(blocks)
    row.updated_at = datetime.now(UTC)
    self._session.flush()
    return _to_draft_read(row)
```

Draft creation copies every block in order from the selected succeeded base version.

- [ ] **Step 4: Implement routes and structured conflicts**

Register `versions.router`. Return `404` for unknown job/version/draft, `409` for stale revision or a non-succeeded base, and `422` for duplicate/missing block IDs. Add `version_id` query support to existing analysis endpoints while keeping absent `version_id` equivalent to active version.

- [ ] **Step 5: Run API and existing analysis tests**

Run:

```powershell
Push-Location apps\api
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_versions_api.py tests\integration\test_analysis_api.py -q
Pop-Location
```

Expected: PASS.

- [ ] **Step 6: Commit version and draft APIs**

```powershell
git add apps\api\src\text_verification\api apps\api\src\text_verification\infrastructure\revision_repository.py apps\api\tests\integration\test_versions_api.py apps\api\tests\integration\test_analysis_api.py
git commit -m "Add document version and draft APIs" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Run retry-safe draft reanalysis with version SSE

**Files:**
- Create: `apps/api/src/text_verification/workers/reanalysis_tasks.py`
- Create: `apps/api/tests/integration/test_reanalysis_task.py`
- Modify: `apps/api/src/text_verification/workers/pipeline.py`
- Modify: `apps/api/src/text_verification/workers/tasks.py`
- Modify: `apps/api/src/text_verification/workers/celery_app.py`
- Modify: `apps/api/src/text_verification/api/routes/versions.py`
- Modify: `apps/api/tests/integration/test_pipeline_task.py`

**Interfaces:**
- Consumes: draft and version repository interfaces from Tasks 2–3.
- Produces: `POST /api/v1/jobs/{job_id}/drafts/{draft_id}/reanalyze`.
- Produces: `GET /api/v1/jobs/{job_id}/versions/{version_id}/events`.
- Produces Celery task `text_verification.process_document_version`.

- [ ] **Step 1: Write worker and endpoint tests**

Test all state transitions:

```python
def test_reanalysis_success_activates_new_version_and_consumes_draft(
    db_session,
    seeded_edit_draft,
    celery_eager,
):
    revisions = RevisionRepository(db_session)
    draft = seeded_edit_draft.draft
    job_id = seeded_edit_draft.job_id
    version = revisions.create_reanalysis_version(
        draft_id=draft.draft_id,
        idempotency_key="request-1",
    )
    process_document_version.delay(str(version.version_id))
    session.expire_all()
    assert revisions.get_version(version.version_id).status == "succeeded"
    assert revisions.get_active_version(job_id).version_id == version.version_id
    assert revisions.get_draft(job_id, draft.draft_id).consumed_at is not None


def test_reanalysis_failure_keeps_parent_active_and_draft_editable(
    db_session,
    seeded_edit_draft,
    failing_checker_registry,
):
    revisions = RevisionRepository(db_session)
    draft = seeded_edit_draft.draft
    parent = seeded_edit_draft.parent
    job_id = seeded_edit_draft.job_id
    version = revisions.create_reanalysis_version(
        draft_id=draft.draft_id,
        idempotency_key="request-failure",
    )
    result = process_document_version.delay(str(version.version_id))
    assert result.successful()
    db_session.expire_all()
    assert revisions.get_active_version(job_id).version_id == parent.version_id
    assert revisions.get_draft(job_id, draft.draft_id).consumed_at is None
```

Also assert repeated idempotency keys return the same version and old task completion cannot reactivate an older child.

- [ ] **Step 2: Run tests and confirm no reanalysis task exists**

Run:

```powershell
Push-Location apps\api
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_reanalysis_task.py -q
Pop-Location
```

Expected: FAIL on missing task and endpoint.

- [ ] **Step 3: Extract checker execution from source parsing**

Keep initial upload parsing intact, but add:

```python
def analyze_document(
    self,
    version_id: UUID,
    document: DocumentModel,
    options: CheckOptions,
) -> None:
    self._versions.mark_analyzing(version_id)
    result = self._checkers.run(
        document,
        self._check_context,
        options,
        on_progress=lambda progress: self._versions.record_progress(version_id, progress),
    )
    self._versions.complete_analysis(version_id, document, result.issues, result.failures)
```

The draft document copies base metadata and source locators, replaces block text by block ID, and increments the revision number supplied by the queued version.

- [ ] **Step 4: Implement bounded retries and terminal failure persistence**

Mirror the existing `process_job` retry policy: two retries for unexpected failures, no retry for invalid draft/configuration errors, one persisted failed event after exhaustion. Before activation, lock the job and reject activation when `revision_number` is lower than the active revision.

- [ ] **Step 5: Add reanalysis dispatch and SSE**

The POST request body is:

```json
{
  "expected_draft_revision": 3,
  "idempotency_key": "018f6e36-7f5d-7d7a-a7b5-5f05db25af68"
}
```

Return `202` with version data and `events_url`. Stream ordered version events with `Last-Event-ID` behavior matching the existing job stream.

- [ ] **Step 6: Run worker and job regressions**

Run:

```powershell
Push-Location apps\api
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_reanalysis_task.py tests\integration\test_pipeline_task.py tests\integration\test_job_progress.py -q
Pop-Location
```

Expected: PASS.

- [ ] **Step 7: Commit reanalysis**

```powershell
git add apps\api\src\text_verification\workers apps\api\src\text_verification\api\routes\versions.py apps\api\tests\integration
git commit -m "Add retry-safe document reanalysis" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Make suggestions and decision batches atomic and reversible

**Files:**
- Create: `apps/api/src/text_verification/infrastructure/review_operation_repository.py`
- Create: `apps/api/src/text_verification/api/routes/review_history.py`
- Create: `apps/api/tests/integration/test_review_history_api.py`
- Modify: `apps/api/src/text_verification/infrastructure/analysis_repositories.py`
- Modify: `apps/api/src/text_verification/infrastructure/decision_repository.py`
- Modify: `apps/api/src/text_verification/api/routes/decisions.py`
- Modify: `apps/api/src/text_verification/api/router.py`
- Modify: `apps/api/tests/integration/test_decision_repository.py`
- Modify: `apps/api/tests/integration/test_decision_api.py`

**Interfaces:**
- Produces: issue responses with ordered `suggestions`.
- Produces: atomic `put_decisions()` response `{batch_id, outcomes}`.
- Produces: `GET /api/v1/jobs/{job_id}/operation-batches`.
- Produces: `POST /api/v1/jobs/{job_id}/operation-batches/{batch_id}/undo`.

- [ ] **Step 1: Replace partial-success expectations with atomic tests**

Write tests proving:

```python
def test_one_stale_item_rolls_back_complete_batch(client, db_session, seeded_review):
    decision_url = f"/api/v1/jobs/{seeded_review.job_id}/decisions"
    valid = seeded_review.valid_command
    stale = seeded_review.stale_command
    response = client.put(decision_url, json={"decisions": [valid, stale]})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "decision_batch_conflict"
    assert decision_count(session, valid["issue_id"]) == 0
    assert operation_batch_count(session) == 0


def test_undo_restores_prior_values_only_when_after_snapshot_still_matches(
    client,
    seeded_review,
):
    history_url = f"/api/v1/jobs/{seeded_review.job_id}/operation-batches"
    applied = client.put(
        f"/api/v1/jobs/{seeded_review.job_id}/decisions",
        json={"decisions": [seeded_review.valid_command]},
    ).json()
    batch_id = applied["batch_id"]
    undo = client.post(f"{history_url}/{batch_id}/undo")
    assert undo.status_code == 200
    assert undo.json()["operation_type"] == "undo"
```

Cover custom accepted text (`suggestion_id=None`), edited candidate text, ignored decisions, overlapping ranges, long-term undo, and undo conflict after a newer decision.

- [ ] **Step 2: Run tests and confirm legacy partial writes fail**

Run:

```powershell
Push-Location apps\api
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_decision_api.py tests\integration\test_review_history_api.py -q
Pop-Location
```

Expected: FAIL because current nested transactions persist valid siblings and no history exists.

- [ ] **Step 3: Persist ordered suggestions**

When analysis is stored, normalize `issue.suggestion` plus unique `issue.alternatives` into `IssueSuggestionRow` records. Return:

```python
class IssueSuggestion(BaseModel):
    suggestion_id: UUID
    text: str
    source: SuggestionSource
    explanation: str | None
    rank: int
    preferred: bool
```

Retain legacy issue columns during the rollback window, but all new UI decisions use `suggestions`.

- [ ] **Step 4: Implement deterministic lock and preflight order**

Lock the job, then issue rows sorted by UUID, then existing decision rows. Validate every command and overlap before mutating any row. Store `before_json` and `after_json` for each item in one `ReviewOperationBatchRow`.

An accepted command is valid only when `replacement` is non-empty. When `suggestion_id` is present, it must belong to the issue; edited candidate text remains valid and is stored verbatim.

- [ ] **Step 5: Implement undo as a new operation**

Undo locks the original batch and affected decisions. Each current decision must equal the original `after_json`; otherwise raise `OperationUndoConflict`. Restore `before_json`, deleting the row when the prior decision was absent, and write a new batch with `undoes_batch_id`.

- [ ] **Step 6: Wire API routes and structured errors**

Keep the 500-item limit. Return `409 decision_batch_conflict`, `409 overlapping_decisions`, or `409 operation_undo_conflict` with affected IDs. Return the created batch ID on success.

- [ ] **Step 7: Run decision, concurrency, and history tests**

Run:

```powershell
Push-Location apps\api
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_decision_api.py tests\integration\test_decision_repository.py tests\integration\test_review_history_api.py -q
Pop-Location
```

Expected: PASS, including reversed concurrent batches without deadlock.

- [ ] **Step 8: Commit atomic review operations**

```powershell
git add apps\api\src\text_verification\domain apps\api\src\text_verification\infrastructure apps\api\src\text_verification\api apps\api\tests\integration
git commit -m "Add reversible review operation batches" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Derive modified content, character diffs, and export snapshots

**Files:**
- Create: `apps/api/src/text_verification/domain/derived_content.py`
- Create: `apps/api/tests/unit/domain/test_derived_content.py`
- Modify: `apps/api/src/text_verification/domain/exports.py`
- Modify: `apps/api/src/text_verification/exporters/replacements.py`
- Modify: `apps/api/src/text_verification/api/routes/versions.py`
- Modify: `apps/api/src/text_verification/api/routes/exports.py`
- Modify: `apps/api/tests/unit/domain/test_exports.py`
- Modify: `apps/api/tests/unit/exporters/test_replacements.py`
- Modify: `apps/api/tests/integration/test_export_api.py`

**Interfaces:**
- Produces: `derive_document(version_id: UUID, document: DocumentModel, issues: Sequence[Issue]) -> DerivedDocument`.
- Produces: `myers_diff(original: str, modified: str) -> Sequence[DiffSegment]`.
- Produces: `GET /api/v1/jobs/{job_id}/versions/{version_id}/derived?view=modified|diff`.
- Produces export snapshot schema version 2 with `document_version_id` and `decision_snapshot_sha256`.

- [ ] **Step 1: Write pure-domain tests**

Include exact assertions:

```python
def test_derived_document_applies_replacements_from_right_to_left() -> None:
    derived = derive_document(VERSION_ID, document("甲乙丙丁"), [
        accepted_issue(0, 1, "甲", "A"),
        accepted_issue(2, 4, "丙丁", "CD"),
    ])
    assert derived.document.blocks[0].text == "A乙CD"


def test_modified_text_and_diff_reconstruct_same_value() -> None:
    segments = myers_diff("文字错误", "文本正确")
    assert "".join(s.text for s in segments if s.kind != "delete") == "文本正确"
```

Also test astral Unicode, empty replacements, unchanged blocks, stable snapshot hashes, mismatched original text, and overlap rejection listing every issue ID.

- [ ] **Step 2: Run unit tests and confirm derived service is absent**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\domain\test_derived_content.py apps\api\tests\unit\exporters\test_replacements.py -q
```

Expected: FAIL on missing imports and current accepted decisions reselecting `issue.suggestion`.

- [ ] **Step 3: Implement one canonical replacement planner**

`derive_document()` validates issue bounds and original text, rejects overlaps, and applies each block's replacements in descending start order. It computes SHA-256 over canonical JSON containing version ID and sorted decision snapshots.

`ReplacementPlanner` becomes an adapter over the same validated replacement list. Delete `_resolve_replacement_value()` logic that reads `issue.suggestion`; use `decision.replacement`.

- [ ] **Step 4: Implement character-level Myers diff**

Return only:

```python
class DiffKind(StrEnum):
    EQUAL = "equal"
    INSERT = "insert"
    DELETE = "delete"


class DiffSegment(BaseModel):
    kind: DiffKind
    text: str
```

Coalesce adjacent segments of the same kind. Diff each paragraph independently so a large document cannot create one unbounded matrix.

- [ ] **Step 5: Add derived endpoints and export snapshot v2**

Modified responses contain ordered derived blocks plus `decision_snapshot_sha256`. Diff responses contain ordered per-block segments and the same hash. Export creation resolves the requested or active version, calls `derive_document(version_id, document, issues)` before enqueueing, and stores the returned hash and version ID in `ExportSnapshot(schema_version=2)`.

Deserialize schema-v1 snapshots for already queued exports; new snapshots must be schema 2.

- [ ] **Step 6: Run domain and export tests**

Run:

```powershell
Push-Location apps\api
& .\.venv\Scripts\python.exe -m pytest tests\unit\domain\test_derived_content.py tests\unit\domain\test_exports.py tests\unit\exporters tests\integration\test_export_api.py tests\integration\test_export_task.py -q
Pop-Location
```

Expected: PASS.

- [ ] **Step 7: Commit derived content parity**

```powershell
git add apps\api\src\text_verification\domain apps\api\src\text_verification\exporters apps\api\src\text_verification\api\routes apps\api\tests
git commit -m "Unify modified preview and export content" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Add typed frontend revision clients

**Files:**
- Create: `apps/web/src/types/revisions.ts`
- Create: `apps/web/src/api/revisions.ts`
- Create: `apps/web/tests/revisionsApi.spec.ts`
- Modify: `apps/web/src/types/analysis.ts`
- Modify: `apps/web/src/types/review.ts`
- Modify: `apps/web/src/api/analysis.ts`
- Modify: `apps/web/src/main.ts`
- Modify: `apps/web/tests/analysisApi.spec.ts`

**Interfaces:**
- Consumes: backend API contracts from Tasks 3–6.
- Produces: `RevisionsApi` and injection key.
- Produces frontend DTOs used by all subsequent Vue tasks.

- [ ] **Step 1: Write request-shape tests**

Verify exact URLs, methods, and payloads:

```typescript
expect(fetch).toHaveBeenCalledWith(
  '/api/v1/jobs/job-1/drafts/draft-1',
  expect.objectContaining({
    method: 'PUT',
    body: JSON.stringify({
      expected_revision: 2,
      blocks: [{ block_id: 'p-1', text: '修改后' }]
    })
  })
)
```

Also cover `version_id` query encoding, reanalysis idempotency body, derived modes, `Last-Event-ID`, history pagination, and undo.

- [ ] **Step 2: Run API tests and confirm missing types**

Run:

```powershell
npm --prefix apps\web test -- revisionsApi.spec.ts analysisApi.spec.ts
```

Expected: FAIL because `RevisionsApi` and DTOs do not exist.

- [ ] **Step 3: Add exact frontend contracts**

Define:

```typescript
export type DocumentViewMode = 'original' | 'modified' | 'diff'
export type DocumentVersionStatus = 'queued' | 'analyzing' | 'succeeded' | 'failed'

export interface DraftBlock {
  block_id: string
  text: string
}

export interface DecisionCommand {
  issue_id: string
  issue_version: number
  expected_revision: number
  action: 'accepted' | 'ignored' | 'unreviewed'
  replacement: string | null
  suggestion_id: string | null
}
```

Model decision summaries with `revision`, final `replacement`, and optional `suggestion_id`. Remove `custom` as a status while retaining compatibility parsing only for schema-v1 cached test data.

- [ ] **Step 4: Implement and provide `RevisionsApi`**

Methods:

```typescript
interface RevisionsApi {
  listVersions(jobId: string): Promise<VersionListResponse>
  createDraft(jobId: string, baseVersionId: string): Promise<EditDraft>
  getDraft(jobId: string, draftId: string): Promise<EditDraft>
  updateDraft(jobId: string, draftId: string, request: UpdateDraftRequest): Promise<EditDraft>
  deleteDraft(jobId: string, draftId: string): Promise<void>
  reanalyze(jobId: string, draftId: string, request: ReanalyzeRequest): Promise<ReanalysisResponse>
  getDerived(jobId: string, versionId: string, mode: 'modified' | 'diff'): Promise<DerivedResponse>
  listHistory(jobId: string, versionId: string): Promise<OperationBatchPage>
  undoBatch(jobId: string, batchId: string): Promise<OperationBatch>
}
```

- [ ] **Step 5: Run API tests and type-check**

Run:

```powershell
npm --prefix apps\web test -- revisionsApi.spec.ts analysisApi.spec.ts
npm --prefix apps\web run build
```

Expected: PASS.

- [ ] **Step 6: Commit typed clients**

```powershell
git add apps\web\src\types apps\web\src\api apps\web\src\main.ts apps\web\tests\revisionsApi.spec.ts apps\web\tests\analysisApi.spec.ts
git commit -m "Add versioned review web clients" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 8: Extract version, draft, preview, and history state

**Files:**
- Create: `apps/web/src/composables/useDocumentVersions.ts`
- Create: `apps/web/src/composables/useEditDraft.ts`
- Create: `apps/web/src/composables/useDerivedPreview.ts`
- Create: `apps/web/src/composables/useReviewHistory.ts`
- Create: `apps/web/tests/reviewEditing.spec.ts`
- Modify: `apps/web/src/composables/useReviewWorkspace.ts`
- Modify: `apps/web/tests/ReviewWorkspace.spec.ts`

**Interfaces:**
- Consumes: `AnalysisApi` and `RevisionsApi`.
- Produces focused composables with stale-request guards and no direct DOM dependencies.
- Produces an expanded `ReviewWorkspaceState` consumed by Task 9 and Task 10 components.

- [ ] **Step 1: Write composable tests before extraction**

Mount small harness components and prove:

- selecting a historical version reloads document, issues, and summary with that version ID;
- only the active succeeded version is editable by default;
- draft updates preserve local text on `stale_draft_revision`;
- reanalysis progress ignores events from an older request generation;
- derived responses with an old decision hash cannot replace newer state;
- a successful decision batch starts a 10-second undo deadline;
- long-term undo remains available after fake timers pass 10 seconds.

Use `vi.useFakeTimers()` for the undo deadline and deferred promises for stale-response tests.

- [ ] **Step 2: Run focused tests and observe missing state**

Run:

```powershell
npm --prefix apps\web test -- reviewEditing.spec.ts ReviewWorkspace.spec.ts
```

Expected: FAIL because the current monolithic composable has no versions, drafts, derived views, or history.

- [ ] **Step 3: Implement `useDocumentVersions` and `useEditDraft`**

Expose:

```typescript
interface DocumentVersionsState {
  versions: Ref<DocumentVersion[]>
  activeVersionId: Ref<string | null>
  selectedVersionId: Ref<string | null>
  selectedVersion: ComputedRef<DocumentVersion | null>
  reanalysis: Ref<ReanalysisProgress | null>
  selectVersion(versionId: string): Promise<void>
  refreshVersions(): Promise<void>
}

interface EditDraftState {
  draft: Ref<EditDraft | null>
  localBlocks: Ref<DraftBlock[]>
  dirty: ComputedRef<boolean>
  conflict: Ref<DraftConflict | null>
  begin(baseVersionId: string): Promise<void>
  updateBlock(blockId: string, text: string): void
  save(): Promise<EditDraft>
  discard(): Promise<void>
  reanalyze(): Promise<DocumentVersion>
}
```

Keep submitted local blocks in `conflict` when a stale save fails.

- [ ] **Step 4: Implement derived preview and history state**

`useDerivedPreview` uses a monotonically increasing request generation and clears derived content when decisions or versions change. `useReviewHistory` stores the latest batch, deadline, history page, and undo conflict; the 10-second timer hides only the toast, not the batch.

- [ ] **Step 5: Turn `useReviewWorkspace` into an orchestrator**

Retain existing pagination, filters, selected issue, and focus behavior. Delegate version, draft, preview, and history state to the new files. Reload all three analysis resources on version selection and after successful reanalysis.

Change `decide()` to send final replacement and expected decision revision. Change `decideVisible()` to build accepted commands only for issues with a preferred suggestion and final text; missing suggestions return a visible batch error before any request.

- [ ] **Step 6: Run composable regressions**

Run:

```powershell
npm --prefix apps\web test -- reviewEditing.spec.ts ReviewWorkspace.spec.ts analysisApi.spec.ts revisionsApi.spec.ts
```

Expected: PASS.

- [ ] **Step 7: Commit state extraction**

```powershell
git add apps\web\src\composables apps\web\tests\reviewEditing.spec.ts apps\web\tests\ReviewWorkspace.spec.ts
git commit -m "Add versioned review workspace state" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 9: Add version controls, paragraph editing, and three document views

**Files:**
- Create: `apps/web/src/components/review/VersionToolbar.vue`
- Create: `apps/web/src/components/review/DocumentEditor.vue`
- Create: `apps/web/src/components/review/DocumentDiff.vue`
- Modify: `apps/web/src/components/review/DocumentHeader.vue`
- Modify: `apps/web/src/components/review/DocumentViewer.vue`
- Modify: `apps/web/src/views/ReviewWorkspaceView.vue`
- Modify: `apps/web/tests/reviewEditing.spec.ts`
- Modify: `apps/web/tests/reviewAccessibility.spec.ts`

**Interfaces:**
- Consumes: version, draft, and derived state from Task 8.
- Produces: accessible original, modified, diff, and edit rendering within the existing document panel.

- [ ] **Step 1: Write component interaction tests**

Assert:

- version selector marks historical versions “只读”;
- a historical version exposes “从此版本创建新版本” and creates a child draft explicitly;
- edit button starts a draft on the active version;
- each draft block has an accessible label with its paragraph number;
- save/reanalyze and discard are distinct buttons;
- original/modified/diff tabs use a roving tab index;
- diff insertions and deletions use `<ins>` and `<del>`;
- failed reanalysis returns to the editor with entered text intact;
- leaving the workspace with unsaved local changes invokes one confirmation.

- [ ] **Step 2: Run tests and confirm controls are absent**

Run:

```powershell
npm --prefix apps\web test -- reviewEditing.spec.ts reviewAccessibility.spec.ts
```

Expected: FAIL on missing version, edit, and view controls.

- [ ] **Step 3: Implement the toolbar and editor**

`VersionToolbar` emits `selectVersion`, `setMode`, and `edit`. `DocumentEditor` renders ordered `<textarea>` controls and emits block-level changes without owning persistence.

Use these labels exactly:

- `版本 {revision_number}（当前）`
- `版本 {revision_number}（历史，只读）`
- `从此版本创建新版本`
- `保存草稿并重新检查`
- `放弃草稿`
- `原文`, `修改后`, `差异`

- [ ] **Step 4: Render derived and diff modes**

`DocumentViewer` delegates:

- original mode to the existing highlighted block renderer;
- modified mode to derived blocks without issue highlights;
- diff mode to `DocumentDiff`;
- edit mode to `DocumentEditor`.

Keep `focusSelectedHighlight()` available in original mode. Switching away and back restores the selected issue and scroll position.

- [ ] **Step 5: Wire reanalysis progress and dirty navigation guard**

Show version progress inside the document panel, not as a new page. On failure, show the public reason and “返回草稿”/“重试” actions. `WorkspaceView` and “处理其他文件” check `dirty`; confirmation cancellation leaves the subscription and current file untouched.

- [ ] **Step 6: Run document UI and accessibility tests**

Run:

```powershell
npm --prefix apps\web test -- reviewEditing.spec.ts reviewAccessibility.spec.ts WorkspaceView.spec.ts ReviewWorkspace.spec.ts
npm --prefix apps\web run build
```

Expected: PASS.

- [ ] **Step 7: Commit document editing UI**

```powershell
git add apps\web\src\components\review apps\web\src\views apps\web\tests
git commit -m "Add versioned document editing views" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 10: Add candidate editing, enhanced draft search, and operation history

**Files:**
- Create: `apps/web/src/components/review/OperationHistory.vue`
- Create: `apps/web/src/components/review/UndoToast.vue`
- Modify: `apps/web/src/components/review/IssuePanel.vue`
- Modify: `apps/web/src/components/review/FindReplace.vue`
- Modify: `apps/web/src/components/review/BatchActions.vue`
- Modify: `apps/web/src/components/review/ToolRail.vue`
- Modify: `apps/web/src/components/review/workspaceLayout.ts`
- Modify: `apps/web/src/views/ReviewWorkspaceView.vue`
- Modify: `apps/web/src/composables/useReviewWorkspace.ts`
- Modify: `apps/web/tests/reviewEditing.spec.ts`
- Modify: `apps/web/tests/reviewShellComponents.spec.ts`

**Interfaces:**
- Consumes: atomic decision/history and draft state from Task 8.
- Produces: full review-loop interaction parity in the C2 shell.

- [ ] **Step 1: Write candidate, search, and history tests**

Cover:

```typescript
it('accepts an edited candidate as the final replacement', async () => {
  await wrapper.get('[name="suggestion"]').setValue('候选一')
  await wrapper.get('[aria-label="最终替换内容"]').setValue('人工调整')
  await wrapper.get('[name="accept"]').trigger('click')
  expect(analysisApi.putDecisions).toHaveBeenCalledWith(jobId, [{
    issue_id: 'issue-1',
    issue_version: 1,
    expected_revision: 0,
    action: 'accepted',
    replacement: '人工调整',
    suggestion_id: 'suggestion-1'
  }])
})
```

Also assert restore-to-unreviewed, regex/case flags, invalid-regex inline error, replace current, replace all, clear, `Enter`, `Shift+Enter`, review-mode hidden replacement controls, toast undo, history undo, and conflict messages.

- [ ] **Step 2: Run tests and confirm behavior is missing**

Run:

```powershell
npm --prefix apps\web test -- reviewEditing.spec.ts reviewShellComponents.spec.ts
```

Expected: FAIL.

- [ ] **Step 3: Implement candidate-aware issue decisions**

Render suggestions as a radio group with source and explanation. Selecting a suggestion copies its text into `最终替换内容`; editing that field does not clear the selected source. A blank custom field fails locally. Add `恢复为未处理` for an existing decision and implement it through a reversible operation command, not client-only deletion.

- [ ] **Step 4: Restrict replacement to drafts and enhance search**

Extract pure search compilation:

```typescript
function compileSearch(query: string, regex: boolean, caseSensitive: boolean): RegExp {
  const source = regex ? query : escapeRegExp(query)
  return new RegExp(source, caseSensitive ? 'gu' : 'giu')
}
```

Guard against zero-length regex matches by advancing one Unicode code point. In review mode render find, flags, navigation, and clear only. In edit mode add replacement input, replace current, and replace all; both update `localBlocks` and mark the draft dirty.

- [ ] **Step 5: Add history to desktop rail and compact footer**

Extend:

```typescript
export type WorkspaceTool = 'document' | 'issues' | 'search' | 'batch' | 'history'
export type SidePanelTool = 'issues' | 'batch' | 'history'
```

Desktop history opens in `WorkspaceSidePanel`; compact history is a bottom-navigation view. `UndoToast` uses `role="status"` and keeps its undo button focusable for the full 10 seconds.

- [ ] **Step 6: Run interaction and shell tests**

Run:

```powershell
npm --prefix apps\web test -- reviewEditing.spec.ts reviewShellComponents.spec.ts ReviewWorkspace.spec.ts reviewAccessibility.spec.ts
npm --prefix apps\web run build
```

Expected: PASS.

- [ ] **Step 7: Commit complete review-loop interactions**

```powershell
git add apps\web\src apps\web\tests
git commit -m "Complete review loop interactions" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 11: Prove end-to-end parity and single-screen layout

**Files:**
- Modify: `apps/api/tests/e2e/test_upload_lifecycle.py`
- Create: `apps/api/tests/e2e/test_versioned_review_lifecycle.py`
- Modify: `apps/web/tests/layout/reviewWorkspaceLayout.spec.ts`
- Modify: `apps/web/tests/fixtures/review-workspace.html`
- Create: `docs/feature-matrix.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a measurable acceptance test and the authoritative feature-baseline matrix for this subproject.

- [ ] **Step 1: Add the backend lifecycle acceptance test**

Exercise:

1. upload and initial analysis;
2. create and update a draft;
3. reanalyze to revision 2;
4. verify revision 1 remains readable;
5. accept an edited suggestion and ignore a second issue;
6. create a modified preview and export snapshot;
7. assert normalized preview text equals text extracted from the exported modified file;
8. undo the decision batch and verify the derived hash changes;
9. switch back to revision 1 and reproduce its prior decisions.

- [ ] **Step 2: Add real-browser geometry and continuous-operation tests**

At 1280×800, 1366×768, 768×1024, and 390×844 assert:

- `documentElement.scrollHeight <= innerHeight`;
- history is reachable without hiding export;
- document editor and its primary actions remain in the document panel;
- selecting next search match keeps the search controls visible;
- selecting an issue keeps the inspector visible;
- all new buttons are at least 44×44 CSS pixels;
- version toolbar controls do not wrap vertically at desktop widths.

- [ ] **Step 3: Write the production feature matrix**

In `docs/feature-matrix.md`, add an “审阅闭环” section with one row per reference production behavior:

| Reference behavior | Current implementation | Status | Evidence |
|---|---|---|---|
| 原文按段落编辑并重新检查 | Immutable child version from persisted draft | Equivalent, stronger persistence | API and E2E test names |
| 修改后预览 | Canonical derived-content service shared with export | Stronger replacement | Domain parity test |
| 单项与批量撤销 | 10-second shortcut plus persistent operation history | Stronger replacement | History API test |
| 正则与大小写查找 | Draft-only safe replacement with regex validation | Equivalent | Vitest test name |

Include every review-loop function from the approved audit; do not list the three later subprojects as completed.

- [ ] **Step 4: Run the complete backend verification**

Run:

```powershell
Push-Location apps\api
& .\.venv\Scripts\python.exe -m ruff check src tests
& .\.venv\Scripts\python.exe -m mypy src
& .\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
```

Expected: all commands exit 0 with no skipped newly added versioned-review tests.

- [ ] **Step 5: Run the complete frontend verification**

Run:

```powershell
npm --prefix apps\web test
npm --prefix apps\web run build
npm --prefix apps\web run test:layout
```

Expected: all Vitest tests, TypeScript production build, and Playwright geometry tests pass.

- [ ] **Step 6: Run the deployed smoke test**

Run:

```powershell
docker compose -f infra\compose.yaml up --build -d
(Invoke-WebRequest -UseBasicParsing http://localhost:8080).StatusCode
```

Expected: `200`. Complete one real upload → draft edit → reanalysis → preview → export flow in the deployed stack and confirm no browser-level page scrollbar.

- [ ] **Step 7: Commit acceptance coverage and matrix**

```powershell
git add apps\api\tests\e2e apps\web\tests docs\feature-matrix.md
git commit -m "Verify versioned review loop parity" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
