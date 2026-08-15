# Issue Review Decisions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist versioned issue decisions and provide conflict-safe single and batch review APIs.

**Architecture:** Decisions are separate rows keyed by issue ID and issue version. A repository applies each requested decision independently, returns per-item outcomes, and uses optimistic version matching so stale clients cannot overwrite newer analysis.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, PostgreSQL 16, pytest.

**Spec:** `docs/superpowers/specs/2026-08-15-document-review-workspace-design.md`

## Global Constraints

- Requires `docs/superpowers/plans/2026-08-15-core-analysis-pipeline.md`.
- Actions are exactly `accepted`, `ignored`, and `custom`.
- `custom` requires a non-empty replacement; other actions reject a replacement value.
- Batch requests return an outcome for every item and never hide partial failure.
- Decision writes use the issue/document version and return HTTP 409 semantics for stale items.
- PostgreSQL integration tests use real PostgreSQL.

---

### Task 1: Decision domain model and persistence

**Files:**
- Modify: `apps/api/src/text_verification/domain/issues.py`
- Create: `apps/api/alembic/versions/0004_create_issue_decisions.py`
- Modify: `apps/api/src/text_verification/infrastructure/orm.py`
- Create: `apps/api/src/text_verification/infrastructure/decision_repository.py`
- Create: `apps/api/tests/integration/test_decision_repository.py`

**Interfaces:**
- Produces: `DecisionAction` enum.
- Produces: `IssueDecision(issue_id, issue_version, action, replacement, updated_at)`.
- Produces: `DecisionRepository.apply(job_id, command) -> DecisionOutcome`.

- [ ] **Step 1: Write failing model validation tests**

```python
@pytest.mark.parametrize(
    ("action", "replacement"),
    [
        (DecisionAction.CUSTOM, None),
        (DecisionAction.CUSTOM, "   "),
        (DecisionAction.ACCEPTED, "replacement"),
        (DecisionAction.IGNORED, "replacement"),
    ],
)
def test_decision_rejects_invalid_replacement(action, replacement) -> None:
    with pytest.raises(ValidationError):
        DecisionCommand(
            issue_id=uuid4(),
            issue_version=1,
            action=action,
            replacement=replacement,
        )
```

- [ ] **Step 2: Write failing repository conflict and idempotency tests**

```python
def test_apply_rejects_stale_issue_version(postgres_session: Session) -> None:
    job_id, issue = seed_issue(postgres_session, document_version=2)
    outcome = DecisionRepository(postgres_session).apply(
        job_id,
        DecisionCommand(
            issue_id=issue.issue_id,
            issue_version=1,
            action=DecisionAction.ACCEPTED,
        ),
    )
    assert outcome.status == DecisionOutcomeStatus.CONFLICT
    assert outcome.code == "stale_issue_version"


def test_apply_same_decision_is_idempotent(postgres_session: Session) -> None:
    job_id, issue = seed_issue(postgres_session, document_version=1)
    command = DecisionCommand(
        issue_id=issue.issue_id,
        issue_version=1,
        action=DecisionAction.IGNORED,
    )
    repository = DecisionRepository(postgres_session)
    first = repository.apply(job_id, command)
    second = repository.apply(job_id, command)
    postgres_session.commit()
    assert first.decision == second.decision
    assert count_decisions(postgres_session, issue.issue_id) == 1
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_decision_repository.py -v
```

Expected: FAIL because the domain types, table, and repository are absent.

- [ ] **Step 4: Add decision models and migration**

Create `issue_decisions`:

```text
issue_id UUID PRIMARY KEY REFERENCES issues(issue_id) ON DELETE CASCADE
job_id UUID NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE
issue_version INTEGER NOT NULL
action VARCHAR(16) NOT NULL
replacement TEXT NULL
updated_at TIMESTAMPTZ NOT NULL
```

Add a check constraint matching replacement rules and an index on `(job_id, action)`.

- [ ] **Step 5: Implement atomic per-item application**

`DecisionRepository.apply` loads the issue scoped to `job_id`, compares `document_version`, validates replacement, and upserts the row. It returns `applied`, `conflict`, or `invalid`; it raises only for database/infrastructure failures.

- [ ] **Step 6: Apply migration and run tests**

Run:

```powershell
docker compose -f infra\compose.yaml run --rm migrate alembic upgrade head
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_decision_repository.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add apps\api\src\text_verification\domain\issues.py apps\api\src\text_verification\infrastructure apps\api\alembic\versions\0004_create_issue_decisions.py apps\api\tests\integration\test_decision_repository.py
git commit -m "feat: persist versioned issue decisions" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Batch decision API and decision-aware issue queries

**Files:**
- Create: `apps/api/src/text_verification/api/routes/decisions.py`
- Modify: `apps/api/src/text_verification/api/router.py`
- Modify: `apps/api/src/text_verification/api/routes/analysis.py`
- Create: `apps/api/tests/integration/test_decision_api.py`
- Modify: `apps/api/tests/integration/test_analysis_api.py`

**Interfaces:**
- Produces: `PUT /api/v1/jobs/{job_id}/decisions`.
- Extends issue query with `decision=unreviewed|accepted|ignored|custom`.
- Returns `DecisionBatchResponse(outcomes: list[DecisionOutcome])`.

- [ ] **Step 1: Write failing mixed-outcome API test**

```python
def test_batch_decisions_return_per_item_outcomes(client: TestClient) -> None:
    job_id, current_issue, stale_issue = seed_two_versioned_issues()
    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json={
            "decisions": [
                {
                    "issue_id": str(current_issue.issue_id),
                    "issue_version": current_issue.document_version,
                    "action": "accepted",
                    "replacement": None,
                },
                {
                    "issue_id": str(stale_issue.issue_id),
                    "issue_version": stale_issue.document_version - 1,
                    "action": "ignored",
                    "replacement": None,
                },
            ]
        },
    )
    assert response.status_code == 200
    assert [item["status"] for item in response.json()["outcomes"]] == [
        "applied",
        "conflict",
    ]
```

- [ ] **Step 2: Write failing decision-filter test**

```python
def test_issue_query_filters_unreviewed_items(client: TestClient) -> None:
    job_id = seed_reviewed_and_unreviewed_issues()
    response = client.get(
        f"/api/v1/jobs/{job_id}/issues",
        params={"decision": "unreviewed"},
    )
    assert response.status_code == 200
    assert [item["decision"] for item in response.json()["items"]] == [None]
```

- [ ] **Step 3: Run API tests and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_decision_api.py apps\api\tests\integration\test_analysis_api.py -v
```

Expected: FAIL because routes and decision joins are absent.

- [ ] **Step 4: Implement request and response schemas**

Limit batches to 500 items. Reject duplicate issue IDs in one request with HTTP 422 `duplicate_issue_decision`. Unknown jobs return 404. A known job with no analysis returns 409 `analysis_not_ready`.

- [ ] **Step 5: Implement transaction and filtering**

Process commands in request order. Use a nested transaction/savepoint per command so one invalid item does not roll back successful siblings. Commit once after all outcomes are collected. Left join decisions in issue queries and expose:

```json
{
  "action": "custom",
  "replacement": "建议文本",
  "issue_version": 1,
  "updated_at": "2026-08-15T00:00:00Z"
}
```

- [ ] **Step 6: Run API and repository suites**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_decision_api.py apps\api\tests\integration\test_analysis_api.py apps\api\tests\integration\test_decision_repository.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add apps\api\src\text_verification\api apps\api\src\text_verification\infrastructure\analysis_repositories.py apps\api\tests\integration
git commit -m "feat: add conflict-safe issue review api" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Summary counts and decision invalidation on re-analysis

**Files:**
- Modify: `apps/api/src/text_verification/infrastructure/analysis_repositories.py`
- Modify: `apps/api/src/text_verification/infrastructure/decision_repository.py`
- Modify: `apps/api/src/text_verification/api/routes/analysis.py`
- Modify: `apps/api/tests/integration/test_analysis_repository.py`
- Modify: `apps/api/tests/integration/test_analysis_api.py`

**Interfaces:**
- Produces summary counts by category, severity, and decision state.
- Guarantees new analysis version removes decisions tied to replaced issues.

- [ ] **Step 1: Write failing summary and replacement tests**

```python
def test_summary_counts_decision_states(client: TestClient) -> None:
    job_id = seed_issue_decisions(accepted=2, ignored=1, custom=1, unreviewed=3)
    payload = client.get(f"/api/v1/jobs/{job_id}/summary").json()
    assert payload["by_decision"] == {
        "accepted": 2,
        "ignored": 1,
        "custom": 1,
        "unreviewed": 3,
    }


def test_replacing_analysis_removes_old_decisions(postgres_session: Session) -> None:
    job_id = seed_analysis_with_decision(postgres_session, version=1)
    replace_analysis(postgres_session, job_id, version=2)
    postgres_session.commit()
    assert list_decisions(postgres_session, job_id) == []
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_analysis_repository.py apps\api\tests\integration\test_analysis_api.py -v
```

Expected: FAIL on missing decision counts and retained old decisions.

- [ ] **Step 3: Implement grouped summary queries**

Use SQL grouped counts rather than loading all issues. `unreviewed` is the count of issues with no joined decision. Return zero for absent groups so response keys are stable.

- [ ] **Step 4: Enforce replacement cleanup**

`replace_analysis` deletes old issues; the `ON DELETE CASCADE` decision foreign key removes their decisions in the same transaction. Add an explicit assertion that the inserted document version is greater than the existing version.

- [ ] **Step 5: Run full backend verification**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests -v
& .\apps\api\.venv\Scripts\python.exe -m ruff check apps\api
& .\apps\api\.venv\Scripts\python.exe -m mypy apps\api\src
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add apps\api\src\text_verification\infrastructure apps\api\src\text_verification\api apps\api\tests
git commit -m "feat: summarize and invalidate review decisions" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Phase Acceptance

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_decision_repository.py apps\api\tests\integration\test_decision_api.py apps\api\tests\integration\test_analysis_api.py -v
```

Expected: clients can review issues individually or in mixed batches, stale writes produce item-level conflicts, and summaries reflect decision state.
