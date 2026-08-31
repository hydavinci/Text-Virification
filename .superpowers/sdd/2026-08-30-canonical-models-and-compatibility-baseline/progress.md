# SDD ledger — plan: docs/superpowers/plans/2026-08-30-canonical-models-and-compatibility-baseline.md

## Preflight scan

| Task(s) | Shared file or interface | Finding |
|---|---|---|
| Task 1 | `domain/documents.py`, `domain/issues.py` | Internally consistent; Task 3 consumes the canonical models produced here. |
| Task 2 | `domain/verification.py`, `config.py` | Plan snippet references `Scenario` without defining its dependency direction. |
| Task 3 | `compatibility/service.py`, `compatibility/llm_review.py` | Consumes Tasks 1-2 models and settings; no conflict after the Scenario ruling. |
| Tasks 3-4 | Compatibility issue conversion and analyzer behavior | Task 3 changes result shape; Task 4 changes one deterministic rule. The contract remains canonical and the rule fix is isolated. |
| Tasks 3-5 | `compatibility/analyzer.py` and dictionary metadata | Task 5 must preserve the adapter contract introduced by Task 3 while replacing only dictionary loading. |
| Tasks 4-5 | `compatibility/analyzer.py` | Sequential changes are compatible: PII matching and dictionary loading affect separate rules. |
| Task 5 | Packaged dictionary files and `pyproject.toml` | Internally consistent; duplicate JSON files are removed only after the packaged loader is tested. |
| Task 6 | Frontend verification types and API tests | Consumes Task 3 response identities; it does not alter workspace behavior. |

Ruling: Define canonical `Scenario` in `domain.verification` and make `compatibility.models.Scenario` a temporary re-export or adapter — domain code must not depend on the compatibility package — if wrong, compatibility imports may require a broader migration in Task 3.

## Baseline

- Frontend: 29 tests passed.
- Backend: 86 tests passed, 8 skipped.

Task 1: fix round 1/5 (1 addressed, 0 open — async upload allowlist regression; commits 0cf26be..570c6f4)
Task 1: complete (commits 6806b6e..570c6f4, review clean)
Task 2: Ruling: `compatibility.models.Scenario` remains until Task 3 because Task 3 owns the compatibility adapter and response migration; Task 2 establishes the canonical domain type only — changing it early would mix API compatibility work into the contract task — if wrong, Task 3 may reveal additional compatibility call sites.
Task 2: complete (commits 570c6f4..5649715, reviewer finding ruled as Task 3 scope)
Task 3: fix round 1/5 (2 addressed, 0 open — uploaded block metadata and stray uv.lock; commits 97cd3e5..05fde47)
Task 3: complete (commits 5649715..05fde47, review clean)
Task 4: minor (deferred): source-rule contract covers uppercase identity-card `X` but lacks a distinct lowercase `x` case.
Task 4: complete (commits 05fde47..8799396, review clean with 1 deferred minor)
Task 5: Ruling: `DictionarySnapshot` exposes only `name`, `version`, and validated immutable `entries`; the version test hashes the canonical source file bytes directly instead of adding the plan example's undeclared `raw_bytes` field — exposing raw bytes would expand the domain contract without a consumer — if wrong, future audit tooling may need a separate raw-resource API.
Task 5: fix round 1/5 (2 addressed, 0 open — required dictionary fields and controlled failure cleanup; commits 1861c86..a4fa1c2)
Task 5: complete (commits 8799396..a4fa1c2, review clean)
Task 6: complete (commits a4fa1c2..459ca64, review clean)
Final fix: Ruling: production backend format declarations, MIME checks, and upload allowlists now derive from typed capability profiles; `UploadWorkspace.vue` keeps its existing hard-coded seven-format behavior in this compatibility stage, and consuming `/formats` remains explicit Stage 4 workspace scope — if wrong, the frontend can drift from the manifest before that migration.
