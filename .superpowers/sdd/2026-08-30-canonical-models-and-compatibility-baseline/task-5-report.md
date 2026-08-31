# Task 5 Report — consolidate dictionaries and expose deterministic versions

## Status

- Completed on `main`.
- Report created at the requested path because `task-5-report.md` did not exist before implementation.

## Scope completed

- Added canonical dictionary domain models in `apps/api/src/text_verification/domain/dictionaries.py`.
- Added packaged-resource loading, schema validation, deterministic SHA-256 versions, and content-hash-aware caching in `apps/api/src/text_verification/infrastructure/dictionary_loader.py`.
- Moved the only runtime dictionary JSON files to `apps/api/src/text_verification/resources/dictionaries/`.
- Updated `apps/api/src/text_verification/compatibility/analyzer.py` to consume validated snapshots instead of `compatibility/data` files and to expose loaded dictionary versions.
- Added typed `dictionary_versions` metadata to `VerificationResult` and forwarded it through the legacy compatibility response.
- Removed duplicate JSON copies from `resources/dictionaries/` and `apps/api/src/text_verification/compatibility/data/`.
- Updated `resources/dictionaries/README.md` to document the packaged source of truth and deterministic versioning.

## Boundaries preserved

- Kept the public `DictionarySnapshot` surface limited to `name`, `version`, and validated immutable `entries`; no public `raw_bytes` field was added.
- Kept dictionary schema definitions in the domain package and loader behavior in infrastructure; domain code still has no dependency on `text_verification.compatibility`.
- Preserved analyzer rule behavior by reusing the existing `_check_sensitive()` and `_check_ad_extreme()` logic against validated entries rather than changing rule semantics.
- Preserved legacy response fields while adding the new `dictionary_versions` field alongside existing metadata.
- Removed silent-empty fallback behavior: malformed or missing dictionaries now raise `DictionaryLoadError` instead of degrading unnoticed.

## RED evidence

### Failing tests written first

Created or tightened:

- `apps/api/tests/unit/infrastructure/test_dictionary_loader.py`
- `apps/api/tests/unit/domain/test_verification.py`
- `apps/api/tests/unit/compatibility/test_adapters.py`
- `apps/api/tests/integration/test_compatibility_api.py`

### RED command

```bash
cd /Users/yhe/Work/Text-Virification/apps/api
uv run --extra dev pytest tests/unit/infrastructure/test_dictionary_loader.py tests/unit/domain/test_verification.py tests/unit/compatibility/test_adapters.py tests/integration/test_compatibility_api.py -q
```

### RED result

- `12 failed, 22 passed`
- First failure: `ModuleNotFoundError: No module named 'text_verification.infrastructure.dictionary_loader'`
- The remaining failures were the expected metadata-contract breaks:
  - `VerificationResult` had no typed `dictionary_versions` field/default.
  - The legacy compatibility payload did not include `dictionary_versions`.
  - The API `/api/v1/analyze` response did not expose dictionary versions.

This proved the tests were exercising missing functionality rather than typos or unrelated regressions.

## GREEN implementation

### Production change

1. Added immutable, validated dictionary entry models and `DictionarySnapshot`.
2. Added `DictionaryLoader` that:
   - loads packaged files with `importlib.resources`,
   - supports filesystem-root injection for invalid-file tests,
   - versions snapshots with `sha256(file_bytes).hexdigest()`,
   - validates malformed top-level/category/entry shapes with `DictionaryLoadError`,
   - caches successful snapshots by content hash while refreshing stored file metadata.
3. Switched `TextAnalyzer` to load `sensitive_rules` and `ad_extreme_words` through the loader and expose the versions actually loaded during analysis.
4. Added `dictionary_versions` to `VerificationResult` with a safe default `{}` and included it in the legacy response payload.
5. Moved runtime dictionaries into the package resources tree and removed all duplicate JSON copies after focused tests passed.

## Focused GREEN / verification evidence

### Focused dictionary + compatibility command

```bash
cd /Users/yhe/Work/Text-Virification/apps/api
uv run --extra dev pytest tests/unit/infrastructure/test_dictionary_loader.py tests/unit/domain/test_verification.py tests/unit/compatibility/test_adapters.py tests/contract/test_source_rule_contracts.py tests/integration/test_compatibility_api.py -q
```

### Focused result

- `37 passed, 6 warnings`

### Ruff command

```bash
cd /Users/yhe/Work/Text-Virification/apps/api
uv run --extra dev ruff check src/text_verification/domain/dictionaries.py src/text_verification/infrastructure/dictionary_loader.py src/text_verification/domain/verification.py src/text_verification/compatibility/adapters.py src/text_verification/compatibility/service.py tests/unit/infrastructure/test_dictionary_loader.py tests/unit/domain/test_verification.py tests/unit/compatibility/test_adapters.py tests/integration/test_compatibility_api.py
```

### Ruff result

- `All checks passed!`

### mypy command

```bash
cd /Users/yhe/Work/Text-Virification/apps/api
uv run --extra dev mypy src/text_verification/domain/dictionaries.py src/text_verification/infrastructure/dictionary_loader.py src/text_verification/domain/verification.py src/text_verification/compatibility/adapters.py src/text_verification/compatibility/service.py
```

### mypy result

- `Success: no issues found in 5 source files`

### Wheel packaging command

The project virtualenv did not provide `python -m pip`, so I used `uv build --wheel` to produce the equivalent wheel artifact and then inspected its contents:

```bash
cd /Users/yhe/Work/Text-Virification/apps/api
uv build --wheel --out-dir dist
python3 - <<'PY'
from pathlib import Path
from zipfile import ZipFile
wheel = sorted(Path('dist').glob('text_verification-*.whl'))[-1]
print(f'WHEEL={wheel.name}')
with ZipFile(wheel) as archive:
    names = sorted(name for name in archive.namelist() if 'text_verification/resources/dictionaries/' in name)
for name in names:
    print(name)
PY
```

### Wheel packaging result

- Built `text_verification-0.1.0-py3-none-any.whl`
- Confirmed the wheel contains:
  - `text_verification/resources/dictionaries/ad_extreme_words.json`
  - `text_verification/resources/dictionaries/sensitive_rules.json`

## Full backend suite evidence

### Full-suite command

```bash
cd /Users/yhe/Work/Text-Virification/apps/api
uv run --extra dev pytest -q
```

### Full-suite result

- `120 passed, 8 skipped, 6 warnings`

Skipped tests were the existing environment-gated cases for:

- `LIVE_API_URL`
- `TEST_DATABASE_URL`

Warnings were the same pre-existing FastAPI/TestClient and PyMuPDF SWIG deprecation warnings seen before this task.

## Files changed

- `apps/api/pyproject.toml`
- `apps/api/src/text_verification/compatibility/adapters.py`
- `apps/api/src/text_verification/compatibility/analyzer.py`
- `apps/api/src/text_verification/compatibility/service.py`
- `apps/api/src/text_verification/domain/dictionaries.py`
- `apps/api/src/text_verification/domain/verification.py`
- `apps/api/src/text_verification/infrastructure/dictionary_loader.py`
- `apps/api/src/text_verification/resources/__init__.py`
- `apps/api/src/text_verification/resources/dictionaries/ad_extreme_words.json`
- `apps/api/src/text_verification/resources/dictionaries/sensitive_rules.json`
- `apps/api/tests/integration/test_compatibility_api.py`
- `apps/api/tests/unit/compatibility/test_adapters.py`
- `apps/api/tests/unit/domain/test_verification.py`
- `apps/api/tests/unit/infrastructure/test_dictionary_loader.py`
- `resources/dictionaries/README.md`
- deleted `resources/dictionaries/advertising-extreme-terms.zh-cn.json`
- deleted `resources/dictionaries/compliance-sensitive-rules.zh-cn.json`
- deleted `apps/api/src/text_verification/compatibility/data/ad_extreme_words.json`
- deleted `apps/api/src/text_verification/compatibility/data/sensitive_rules.json`

## Self-review

- Reviewed the diff to confirm only dictionary sourcing/versioning changed; sensitive/ad-extreme rule detection logic itself remains intact.
- Verified `git --no-pager diff --check` exited cleanly.
- Verified `apps/api/src/text_verification/domain/` still contains no imports from `text_verification.compatibility`.
- Verified the deterministic-version test hashes the packaged source file bytes directly, not an exposed raw-bytes field.

## Concerns / follow-up notes

1. Full backend verification still skips the existing environment-gated live-stack and PostgreSQL integration tests when `LIVE_API_URL` or `TEST_DATABASE_URL` are unset.
2. The task-required wheel verification used `uv build --wheel` instead of `python -m pip wheel` because the managed project environment lacked the `pip` module; the produced wheel was inspected successfully.
3. The compatibility package still contains an empty `data/__init__.py`; it is inert, but it may be worth removing in a later cleanup if the team wants the old package path gone entirely.
