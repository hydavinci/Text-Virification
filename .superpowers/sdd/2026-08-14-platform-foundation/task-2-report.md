# Task 2 Report — Domain contracts

## Outcome
Implemented the domain contract layer for documents, issues, jobs, and extension ports.

## Commit

- `27e1ee7` — `feat: define document, issue, job, and port contracts`

## RED

Command:
```powershell
& 'C:\Work\text-verification\.worktrees\platform-foundation\backend\.venv\Scripts\python.exe' -m pytest 'C:\Work\text-verification\.worktrees\platform-foundation\backend\tests\unit\domain\test_models.py' -v
```

Output:
```text
E   ModuleNotFoundError: No module named 'text_verification.domain'
=========================== short test summary info ===========================
ERROR tests/unit/domain/test_models.py
```

## GREEN

Command:
```powershell
& 'C:\Work\text-verification\.worktrees\platform-foundation\backend\.venv\Scripts\python.exe' -m pytest 'C:\Work\text-verification\.worktrees\platform-foundation\backend\tests\unit\domain\test_models.py' -v
```

Output:
```text
3 passed, 1 warning in 0.04s
```

Command:
```powershell
& 'C:\Work\text-verification\.worktrees\platform-foundation\backend\.venv\Scripts\python.exe' -m mypy 'C:\Work\text-verification\.worktrees\platform-foundation\backend\src'
```

Output:
```text
Success: no issues found in 12 source files
```

Command:
```powershell
& 'C:\Work\text-verification\.worktrees\platform-foundation\backend\.venv\Scripts\python.exe' -m pytest 'C:\Work\text-verification\.worktrees\platform-foundation\backend\tests' -v
```

Output:
```text
4 passed, 1 warning in 0.05s
```

## Files changed

- `backend/src/text_verification/domain/__init__.py`
- `backend/src/text_verification/domain/documents.py`
- `backend/src/text_verification/domain/issues.py`
- `backend/src/text_verification/domain/jobs.py`
- `backend/src/text_verification/domain/ports.py`
- `backend/tests/unit/domain/test_models.py`

## Self-review

- Kept the change tightly scoped to the new domain contract layer.
- Preserved Task 1 behavior in `config.py` and `main.py`.
- Matched the brief’s model shapes, enum values, and protocol names.
- Added a package marker so the new domain package is importable and included in packaging.

## Concerns

- `JobRead.error_code` and `JobRead.error_message` follow the brief as required fields with nullable types; if the runtime expects omitted fields to deserialize, this may need a follow-up.
- The test suite emits an existing Starlette deprecation warning around `httpx`/`TestClient`.

## Fix round 1/5

### Changed files

- `backend/src/text_verification/domain/jobs.py`
- `backend/tests/unit/domain/test_models.py`
- `.superpowers/sdd/2026-08-14-platform-foundation/task-2-report.md`

### Commands and outputs

Command:
```powershell
& 'C:\Work\text-verification\.worktrees\platform-foundation\backend\.venv\Scripts\python.exe' -m pytest 'C:\Work\text-verification\.worktrees\platform-foundation\backend\tests\unit\domain\test_models.py' -v
```

Output:
```text
5 passed, 1 warning in 0.03s
```

Command:
```powershell
& 'C:\Work\text-verification\.worktrees\platform-foundation\backend\.venv\Scripts\python.exe' -m mypy 'C:\Work\text-verification\.worktrees\platform-foundation\backend\src'
```

Output:
```text
Success: no issues found in 12 source files
```

### Notes

- `JobRead.file_type` now uses the shared `FileType` enum.
- `JobRead.error_code` and `JobRead.error_message` now default to `None`.
- Added focused coverage for unsupported file types and omitted error fields.
