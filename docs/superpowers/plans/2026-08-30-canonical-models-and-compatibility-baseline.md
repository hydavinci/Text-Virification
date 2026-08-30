# Canonical Models and Compatibility Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish tested source-behavior contracts and one canonical document, issue, capability, and verification-result model without breaking the current API.

**Architecture:** Expand the existing domain models, adapt the compatibility analyzer into those models, and keep the current JSON fields through an explicit response mapper. Capability declarations and LLM settings become typed configuration consumed by both backend and frontend.

**Tech Stack:** Python 3.12, Pydantic 2, FastAPI, pytest, Vue 3, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-30-translation-pre-checker-integration-design.md`

## Global Constraints

- Preserve all current `Text-Virification` behavior while adding canonical fields.
- Preserve all implemented source rules and make disconnected source capabilities explicit.
- Do not preserve known source defects.
- Keep Python `>=3.12,<3.13` and existing dependency major-version bounds.
- Keep API response compatibility until the Vue migration is complete.
- Write failing tests before every production change.

---

### Task 1: Expand document and issue domain models

**Files:**
- Modify: `apps/api/src/text_verification/domain/documents.py`
- Modify: `apps/api/src/text_verification/domain/issues.py`
- Test: `apps/api/tests/unit/domain/test_models.py`

**Interfaces:**
- Produces: `FileType` with `docx`, `doc`, `pdf`, `txt`, `rtf`, `md`, and `csv`.
- Produces: `TextBlock(global_start, global_end, block_start, block_end, page, paragraph_index, table_index, row_index, cell_index, bbox, style, source_locator)`.
- Produces: `DocumentModel(document_id, source_version, file_type, source_name, text, blocks, parser_name, parser_version)`.
- Produces: canonical `Issue` with stable identity, run identity, global and block-local offsets, rule version, review metadata, and legacy-compatible content fields.

- [ ] **Step 1: Write failing domain-model tests**

```python
def test_document_model_supports_all_source_formats() -> None:
    assert {item.value for item in FileType} == {
        "docx", "doc", "pdf", "txt", "rtf", "md", "csv"
    }


def test_document_model_rejects_block_outside_document_text() -> None:
    with pytest.raises(ValidationError, match="block range"):
        DocumentModel(
            document_id=uuid4(),
            source_version="sha256:abc",
            file_type=FileType.TXT,
            source_name="sample.txt",
            text="abc",
            parser_name="plain-text",
            parser_version="1",
            blocks=[
                TextBlock(
                    block_id="b1",
                    kind="paragraph",
                    text="abcd",
                    global_start=0,
                    global_end=4,
                    block_start=0,
                    block_end=4,
                    page=None,
                    paragraph_index=0,
                    table_index=None,
                    row_index=None,
                    cell_index=None,
                    bbox=None,
                    parent_id=None,
                    style={},
                    source_locator={},
                )
            ],
        )
```

- [ ] **Step 2: Run tests and confirm the old models fail**

Run:

```bash
cd apps/api
python -m pytest tests/unit/domain/test_models.py -v
```

Expected: FAIL because the additional formats and canonical fields do not exist.

- [ ] **Step 3: Implement canonical models and validators**

```python
class FileType(StrEnum):
    DOCX = "docx"
    DOC = "doc"
    PDF = "pdf"
    TXT = "txt"
    RTF = "rtf"
    MARKDOWN = "md"
    CSV = "csv"


class DocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    source_version: str
    file_type: FileType
    source_name: str
    text: str
    blocks: list[TextBlock]
    parser_name: str
    parser_version: str

    @model_validator(mode="after")
    def validate_blocks(self) -> "DocumentModel":
        for block in self.blocks:
            if block.global_end > len(self.text):
                raise ValueError("block range exceeds document text")
            if self.text[block.global_start:block.global_end] != block.text:
                raise ValueError("block text does not match document text")
        return self
```

Add canonical Issue fields without removing current semantic fields:

```python
verification_run_id: UUID
block_id: str | None
block_start: int | None
block_end: int | None
rule_version: str
description: str
review: str | None = None
review_reason: str | None = None
```

- [ ] **Step 4: Run domain tests**

Run:

```bash
cd apps/api
python -m pytest tests/unit/domain/test_models.py -v
python -m mypy src/text_verification/domain
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/text_verification/domain apps/api/tests/unit/domain/test_models.py
git commit -m "feat: define canonical verification models"
```

### Task 2: Add typed capability and verification contracts

**Files:**
- Create: `apps/api/src/text_verification/domain/capabilities.py`
- Create: `apps/api/src/text_verification/domain/verification.py`
- Modify: `apps/api/src/text_verification/config.py`
- Test: `apps/api/tests/unit/domain/test_capabilities.py`
- Test: `apps/api/tests/unit/domain/test_verification.py`

**Interfaces:**
- Produces: `CapabilityManifest.formats`.
- Produces: `VerificationOptions`.
- Produces: `VerificationResult`.
- Produces: `Settings.llm_*` fields.

- [ ] **Step 1: Write failing capability tests**

```python
def test_default_manifest_declares_seven_formats() -> None:
    manifest = default_capability_manifest()
    assert [item.file_type for item in manifest.formats] == [
        FileType.DOCX,
        FileType.DOC,
        FileType.PDF,
        FileType.TXT,
        FileType.RTF,
        FileType.MARKDOWN,
        FileType.CSV,
    ]
    assert manifest.for_type(FileType.PDF).supports_ocr is True


def test_verification_options_keep_ad_extreme_disabled_by_default() -> None:
    options = VerificationOptions()
    assert options.enable_security is True
    assert options.enable_sensitive is True
    assert options.enable_ad_extreme is False
```

- [ ] **Step 2: Run tests and confirm missing modules**

Run:

```bash
cd apps/api
python -m pytest tests/unit/domain/test_capabilities.py tests/unit/domain/test_verification.py -v
```

Expected: FAIL with module import errors.

- [ ] **Step 3: Implement typed contracts**

```python
class FormatCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file_type: FileType
    display_name: str
    extensions: tuple[str, ...]
    supports_structure: bool
    supports_ocr: bool
    supports_original_export: bool
    supports_track_changes: bool


class VerificationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Scenario = Scenario.GENERAL
    enable_security: bool = True
    enable_sensitive: bool = True
    enable_ad_extreme: bool = False
    custom_glossary: tuple[GlossaryTerm, ...] = ()
    banned_words: tuple[str, ...] = ()
```

Define `VerificationResult` with canonical IDs, document text, statistics,
issues, summary, execution mode, and degradation metadata.

Move all `LLM_*` values from module-level environment reads into `Settings`
using typed fields and bounds.

- [ ] **Step 4: Run tests and static checks**

Run:

```bash
cd apps/api
python -m pytest tests/unit/domain/test_capabilities.py tests/unit/domain/test_verification.py -v
python -m ruff check src/text_verification/domain src/text_verification/config.py
python -m mypy src/text_verification/domain src/text_verification/config.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/text_verification/domain apps/api/src/text_verification/config.py apps/api/tests/unit/domain
git commit -m "feat: add verification capability contracts"
```

### Task 3: Adapt compatibility issues to the canonical contract

**Files:**
- Create: `apps/api/src/text_verification/compatibility/adapters.py`
- Modify: `apps/api/src/text_verification/compatibility/service.py`
- Modify: `apps/api/src/text_verification/compatibility/llm_review.py`
- Test: `apps/api/tests/unit/compatibility/test_adapters.py`
- Modify: `apps/api/tests/integration/test_compatibility_api.py`

**Interfaces:**
- Consumes: canonical `Issue`, `DocumentModel`, and `VerificationResult`.
- Produces: `legacy_issue_to_domain(issue, document, run_id) -> Issue`.
- Produces: `verification_result_to_legacy_response(result) -> dict[str, object]`.

- [ ] **Step 1: Write failing adapter tests**

```python
def test_issue_adapter_builds_stable_issue_id() -> None:
    first = legacy_issue_to_domain(legacy_issue, document, run_id)
    second = legacy_issue_to_domain(legacy_issue, document, run_id)
    assert first.issue_id == second.issue_id
    assert first.original == document.text[first.start:first.end]


def test_legacy_response_keeps_existing_fields_and_adds_ids() -> None:
    payload = verification_result_to_legacy_response(result)
    assert set(EXISTING_TOP_LEVEL_FIELDS) <= set(payload)
    assert payload["document_id"] == str(result.document_id)
    assert payload["verification_run_id"] == str(result.verification_run_id)
    assert payload["issues"][0]["issue_id"] == str(result.issues[0].issue_id)
```

- [ ] **Step 2: Run adapter and API tests**

Run:

```bash
cd apps/api
python -m pytest tests/unit/compatibility/test_adapters.py tests/integration/test_compatibility_api.py -v
```

Expected: FAIL because canonical adaptation is absent.

- [ ] **Step 3: Implement deterministic adaptation**

Use UUID5 over document source version, rule ID, start, end, and original text:

```python
issue_id = uuid5(
    NAMESPACE_URL,
    f"{document.source_version}:{issue.rule_id}:{issue.position}:"
    f"{issue.end_position}:{issue.original}",
)
```

Create one paragraph block for direct text until structured parsers are
introduced. Make `service.analyze()` return canonical `VerificationResult` and
map it at the API boundary.

Update LLM review to accept `Settings` and return canonical review metadata
without importing environment variables.

- [ ] **Step 4: Run compatibility tests**

Run:

```bash
cd apps/api
python -m pytest tests/unit/compatibility/test_adapters.py tests/integration/test_compatibility_api.py -v
python -m ruff check src/text_verification/compatibility
```

Expected: PASS, including all pre-existing response fields.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/text_verification/compatibility apps/api/tests
git commit -m "refactor: map compatibility analysis to canonical results"
```

### Task 4: Establish source-rule compatibility contracts and fix deterministic defects

**Files:**
- Create: `apps/api/tests/contract/test_source_rule_contracts.py`
- Create: `apps/api/tests/contract/cases/source_rules.json`
- Modify: `apps/api/src/text_verification/compatibility/analyzer.py`

**Interfaces:**
- Produces: a data-driven rule contract keyed by rule ID.
- Preserves: zero-based half-open offsets, issue ordering, punctuation priority,
  switch behavior, and LLM fallback semantics.

- [ ] **Step 1: Add representative failing contract cases**

```json
[
  {
    "name": "identity number ending in X",
    "text": "身份证号：11010519491231002X",
    "options": {"enable_security": true},
    "expected": [{"type": "pii_id", "original": "11010519491231002X"}]
  },
  {
    "name": "advertising disabled by default",
    "text": "这是全球领先产品",
    "options": {},
    "expected": []
  },
  {
    "name": "territory naming",
    "text": "台湾产品",
    "options": {"enable_sensitive": true},
    "expected": [{"type": "sensitive_territory", "original": "台湾"}]
  }
]
```

Load cases with `pytest.mark.parametrize`, run the analyzer, assert exact
matched slices, sorted offsets, and expected issue types.

- [ ] **Step 2: Run the contracts**

Run:

```bash
cd apps/api
python -m pytest tests/contract/test_source_rule_contracts.py -v
```

Expected: FAIL for the identity number ending in `X`.

- [ ] **Step 3: Fix the PII entry pattern without changing checksum validation**

Change the candidate regex to include `[0-9Xx]` in the final position and keep
the existing date and checksum checks.

- [ ] **Step 4: Run contract and integration tests**

Run:

```bash
cd apps/api
python -m pytest tests/contract tests/integration/test_compatibility_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/text_verification/compatibility/analyzer.py apps/api/tests/contract
git commit -m "test: codify source rule compatibility"
```

### Task 5: Consolidate dictionaries and expose deterministic versions

**Files:**
- Create: `apps/api/src/text_verification/resources/__init__.py`
- Create: `apps/api/src/text_verification/resources/dictionaries/sensitive_rules.json`
- Create: `apps/api/src/text_verification/resources/dictionaries/ad_extreme_words.json`
- Create: `apps/api/src/text_verification/domain/dictionaries.py`
- Create: `apps/api/src/text_verification/infrastructure/dictionary_loader.py`
- Modify: `apps/api/src/text_verification/compatibility/analyzer.py`
- Modify: `apps/api/pyproject.toml`
- Modify: `resources/dictionaries/README.md`
- Delete: `resources/dictionaries/sensitive_rules.json`
- Delete: `resources/dictionaries/ad_extreme_words.json`
- Delete: `apps/api/src/text_verification/compatibility/data/sensitive_rules.json`
- Delete: `apps/api/src/text_verification/compatibility/data/ad_extreme_words.json`
- Test: `apps/api/tests/unit/infrastructure/test_dictionary_loader.py`

**Interfaces:**
- Produces: `DictionarySnapshot(name, version, entries)`.
- Produces: `DictionaryLoader.load(name) -> DictionarySnapshot`.
- Produces: `DictionaryLoadError`.

- [ ] **Step 1: Write failing dictionary tests**

```python
def test_dictionary_version_is_content_hash(loader):
    snapshot = loader.load("sensitive_rules")
    assert snapshot.version == hashlib.sha256(snapshot.raw_bytes).hexdigest()


def test_invalid_dictionary_is_not_silently_empty(tmp_path):
    (tmp_path / "sensitive_rules.json").write_text("{invalid", encoding="utf-8")
    with pytest.raises(DictionaryLoadError, match="sensitive_rules"):
        DictionaryLoader(tmp_path).load("sensitive_rules")
```

- [ ] **Step 2: Run dictionary tests**

Run:

```bash
cd apps/api
python -m pytest tests/unit/infrastructure/test_dictionary_loader.py -v
```

Expected: FAIL because the typed loader and snapshot do not exist.

- [ ] **Step 3: Move to one packaged dictionary source**

Move both JSON files into
`text_verification/resources/dictionaries`. Configure setuptools:

```toml
[tool.setuptools.package-data]
"text_verification.resources" = ["dictionaries/*.json"]
```

Load with `importlib.resources.files`, validate the expected JSON schema, cache
by file metadata and content hash, and return immutable snapshots. Update
`TextAnalyzer` to receive snapshots or a loader instead of reading
`compatibility/data` directly. Include dictionary versions in verification
result metadata.

Update `resources/dictionaries/README.md` to point maintainers to the single
packaged location; remove duplicate runtime and root copies in the same commit.

- [ ] **Step 4: Run dictionary, contract, and packaging tests**

Run:

```bash
cd apps/api
python -m pytest tests/unit/infrastructure/test_dictionary_loader.py tests/contract -v
python -m pip wheel . --no-deps --wheel-dir dist
python -m ruff check src/text_verification/infrastructure/dictionary_loader.py src/text_verification/domain/dictionaries.py
```

Expected: PASS, and the wheel contains both dictionary JSON files.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/text_verification/resources apps/api/src/text_verification/domain/dictionaries.py apps/api/src/text_verification/infrastructure/dictionary_loader.py apps/api/src/text_verification/compatibility/analyzer.py apps/api/pyproject.toml resources/dictionaries
git commit -m "refactor: use one versioned dictionary source"
```

### Task 6: Extend frontend types without changing the current workspace

**Files:**
- Modify: `apps/web/src/types/verification.ts`
- Modify: `apps/web/src/api/verification.ts`
- Modify: `apps/web/tests/verificationApi.spec.ts`

**Interfaces:**
- Consumes: compatibility JSON plus canonical identity fields.
- Produces: `VerificationIssue.issue_id`, `VerificationResult.document_id`,
  `verification_run_id`, `source_version`, and `execution_mode`.

- [ ] **Step 1: Write a failing API parsing test**

```ts
it('returns stable canonical identities with legacy issue fields', async () => {
  const result = await api.analyzeText('帐号', options)
  expect(result.document_id).toBe('11111111-1111-1111-1111-111111111111')
  expect(result.verification_run_id).toBe('22222222-2222-2222-2222-222222222222')
  expect(result.issues[0].issue_id).toBe('33333333-3333-3333-3333-333333333333')
  expect(result.issues[0].position).toBe(0)
})
```

- [ ] **Step 2: Run the frontend test**

Run:

```bash
cd apps/web
npm test -- verificationApi.spec.ts
```

Expected: FAIL at TypeScript compile time because the canonical fields are absent.

- [ ] **Step 3: Add canonical fields to TypeScript interfaces**

```ts
export interface VerificationIssue {
  issue_id: string
  block_id: string | null
  rule_version: string
  position: number
  end_position: number
  // Keep all existing display fields.
}

export interface VerificationResult {
  document_id: string
  verification_run_id: string
  source_version: string
  execution_mode: 'synchronous' | 'asynchronous'
  // Keep all existing fields until the workspace migration.
}
```

- [ ] **Step 4: Run frontend tests and build**

Run:

```bash
cd apps/web
npm test -- verificationApi.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/types/verification.ts apps/web/src/api/verification.ts apps/web/tests/verificationApi.spec.ts
git commit -m "feat: expose canonical verification identities"
```
