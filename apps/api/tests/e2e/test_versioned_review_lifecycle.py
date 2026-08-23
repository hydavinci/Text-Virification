from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from text_verification.api.dependencies import get_db_session, get_job_storage
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import JobStatus
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.export_repository import ExportRepository
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.revision_repository import RevisionRepository
from text_verification.infrastructure.storage import JobStorage
from text_verification.workers.export_tasks import _run_process_export_attempt
from text_verification.workers.reanalysis_tasks import _build_reanalysis_document


@pytest.fixture
def review_storage(tmp_path: Path) -> JobStorage:
    root = tmp_path / "versioned-review-jobs"
    root.mkdir()
    return JobStorage(root, max_upload_bytes=25 * 1024 * 1024)


@pytest.fixture(autouse=True)
def versioned_review_dependencies(
    app: FastAPI,
    db_session: Session,
    review_storage: JobStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.api.routes import exports as export_routes
    from text_verification.api.routes import jobs as job_routes
    from text_verification.api.routes import versions as version_routes
    from text_verification.workers import export_tasks

    def db_session_override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db_session] = db_session_override
    app.dependency_overrides[get_job_storage] = lambda: review_storage
    monkeypatch.setattr(job_routes, "dispatch_process_job", lambda job_id: None)
    monkeypatch.setattr(
        version_routes,
        "dispatch_process_document_version",
        lambda version_id: _complete_reanalysis(db_session, UUID(version_id)),
    )
    monkeypatch.setattr(export_routes, "dispatch_process_export", lambda export_id: None)
    monkeypatch.setattr(export_tasks, "STORAGE_FACTORY", lambda: review_storage)


def test_versioned_review_lifecycle_preserves_history_and_export_parity(
    client: TestClient,
    db_session: Session,
) -> None:
    created = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", _INITIAL_UPLOAD.encode(), "text/plain")},
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    _complete_initial_analysis(db_session, UUID(job_id))

    completed_job = client.get(f"/api/v1/jobs/{job_id}")
    assert completed_job.status_code == 200
    assert completed_job.json()["status"] == "completed"
    version_1 = _active_version_id(client, job_id)
    revision_1_page = client.get(
        f"/api/v1/jobs/{job_id}/document",
        params={"version_id": version_1},
    )
    assert revision_1_page.status_code == 200
    assert [block["text"] for block in revision_1_page.json()["blocks"]] == [
        "祕密项目需要错误词。",
        "第二段保密合同保留。",
    ]

    revision_1_issues = client.get(
        f"/api/v1/jobs/{job_id}/issues",
        params={"version_id": version_1},
    )
    assert revision_1_issues.status_code == 200
    revision_1_items = revision_1_issues.json()["items"]
    revision_1_batch = _put_decisions(
        client,
        job_id,
        [
            {
                "issue_id": revision_1_items[0]["issue_id"],
                "issue_version": revision_1_items[0]["document_version"],
                "expected_revision": 0,
                "action": "accepted",
                "replacement": "秘密",
                "suggestion_id": None,
            }
        ],
    )
    revision_1_hash = _derived_hash(client, job_id, version_1)

    draft = client.post(
        f"/api/v1/jobs/{job_id}/drafts",
        json={"base_version_id": version_1},
    )
    assert draft.status_code == 200, draft.text
    draft_payload = draft.json()
    updated_draft_blocks = [
        {
            "block_id": draft_payload["blocks"][0]["block_id"],
            "text": "秘密项目需要错误词。",
        },
        {
            "block_id": draft_payload["blocks"][1]["block_id"],
            "text": "第二段保密合同保留。",
        },
    ]
    saved_draft = client.put(
        f"/api/v1/jobs/{job_id}/drafts/{draft_payload['draft_id']}",
        json={
            "expected_revision": draft_payload["revision"],
            "blocks": updated_draft_blocks,
        },
    )
    assert saved_draft.status_code == 200, saved_draft.text
    assert saved_draft.json()["revision"] == draft_payload["revision"] + 1

    reanalysis = client.post(
        f"/api/v1/jobs/{job_id}/drafts/{draft_payload['draft_id']}/reanalyze",
        json={
            "expected_draft_revision": saved_draft.json()["revision"],
            "idempotency_key": "task-11-e2e-reanalysis",
        },
    )
    assert reanalysis.status_code == 202, reanalysis.text
    version_2 = _active_version_id(client, job_id)
    assert version_2 != version_1

    versions = client.get(f"/api/v1/jobs/{job_id}/versions")
    assert versions.status_code == 200
    assert [version["revision_number"] for version in versions.json()["versions"]] == [1, 2]

    readable_revision_1 = client.get(
        f"/api/v1/jobs/{job_id}/document",
        params={"version_id": version_1},
    )
    assert readable_revision_1.status_code == 200
    assert readable_revision_1.json()["blocks"][0]["text"] == "祕密项目需要错误词。"

    version_2_issues = client.get(
        f"/api/v1/jobs/{job_id}/issues",
        params={"version_id": version_2},
    )
    assert version_2_issues.status_code == 200
    version_2_items = version_2_issues.json()["items"]
    before_decisions = _derived_content(client, job_id, version_2)
    before_decisions_hash = before_decisions["decision_snapshot_sha256"]
    before_decisions_text = _preview_plain_text(before_decisions["blocks"])
    assert "错误词" in before_decisions_text
    assert "最终词" not in before_decisions_text
    assert "保密" in before_decisions_text
    decision_batch = _put_decisions(
        client,
        job_id,
        [
            {
                "issue_id": version_2_items[0]["issue_id"],
                "issue_version": version_2_items[0]["document_version"],
                "expected_revision": 0,
                "action": "accepted",
                "replacement": "最终词",
                "suggestion_id": None,
            },
            {
                "issue_id": version_2_items[1]["issue_id"],
                "issue_version": version_2_items[1]["document_version"],
                "expected_revision": 0,
                "action": "ignored",
                "replacement": None,
                "suggestion_id": None,
            },
        ],
    )

    modified_preview = _derived_content(client, job_id, version_2)
    modified_preview_text = _normalize_plain_text(
        _preview_plain_text(modified_preview["blocks"])
    )
    after_decisions_hash = modified_preview["decision_snapshot_sha256"]
    assert after_decisions_hash != before_decisions_hash
    assert "最终词" in modified_preview_text
    assert "错误词" not in modified_preview_text
    assert "保密" in modified_preview_text

    exported = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "modified_document", "version_id": version_2},
    )
    assert exported.status_code == 202, exported.text
    export_id = UUID(exported.json()["export_id"])
    _run_process_export_attempt(db_session, export_id)
    stored_export = ExportRepository(db_session).get(export_id)
    assert stored_export is not None
    assert stored_export.status == "completed"
    downloaded = client.get(f"/api/v1/jobs/{job_id}/exports/{export_id}/download")
    assert downloaded.status_code == 200, downloaded.text
    exported_text = _normalize_plain_text(downloaded.content.decode("utf-8"))
    assert modified_preview_text == exported_text
    assert "最终词" in exported_text
    assert "错误词" not in exported_text
    assert "保密" in exported_text

    undo = client.post(
        f"/api/v1/jobs/{job_id}/operation-batches/{decision_batch['batch_id']}/undo"
    )
    assert undo.status_code == 200, undo.text
    undo_preview = _derived_content(client, job_id, version_2)
    undo_hash = undo_preview["decision_snapshot_sha256"]
    undo_text = _normalize_plain_text(_preview_plain_text(undo_preview["blocks"]))
    assert undo_hash == before_decisions_hash
    assert undo_hash != after_decisions_hash
    assert undo_text == _normalize_plain_text(before_decisions_text)
    assert "错误词" in undo_text
    assert "最终词" not in undo_text
    assert "保密" in undo_text

    revision_1_replayed = client.get(
        f"/api/v1/jobs/{job_id}/issues",
        params={"version_id": version_1},
    )
    revision_1_history = client.get(
        f"/api/v1/jobs/{job_id}/operation-batches",
        params={"version_id": version_1},
    )
    assert revision_1_replayed.status_code == 200
    assert revision_1_replayed.json()["items"][0]["decision"]["replacement"] == "秘密"
    assert revision_1_history.status_code == 200
    assert revision_1_history.json()["items"][0]["batch_id"] == revision_1_batch["batch_id"]
    assert _derived_hash(client, job_id, version_1) == revision_1_hash


def _complete_initial_analysis(db_session: Session, job_id: UUID) -> None:
    repository = JobRepository(db_session)
    repository.transition(job_id, JobStatus.CHECKING_CHINESE, 25, "正在检查")
    document = _document(
        ["祕密项目需要错误词。", "第二段保密合同保留。"],
        version=1,
    )
    AnalysisRepository(db_session).replace_analysis(
        job_id,
        document,
        [
            _issue(
                document,
                issue_id=UUID("00000000-0000-0000-0000-000000001101"),
                block_index=0,
                original="祕密",
                suggestion="秘密",
                message="请使用通用汉字。",
            ),
            _issue(
                document,
                issue_id=UUID("00000000-0000-0000-0000-000000001102"),
                block_index=1,
                original="保密",
                suggestion="公开",
                message="请确认保密表达。",
            ),
        ],
        {},
    )
    repository.transition(job_id, JobStatus.COMPLETED, 100, "处理完成")
    repository.commit()


def _complete_reanalysis(db_session: Session, version_id: UUID) -> None:
    revisions = RevisionRepository(db_session)
    version, draft_id, expected_revision = revisions.get_reanalysis_request(version_id)
    draft = revisions.get_reanalysis_draft(
        version.job_id,
        draft_id,
        expected_revision=expected_revision,
    )
    assert version.parent_version_id is not None
    base_document = AnalysisRepository(db_session).get_document(
        version.job_id,
        version.parent_version_id,
    )
    assert base_document is not None
    document = _build_reanalysis_document(version.revision_number, base_document, draft)
    revisions.complete_analysis(
        version.version_id,
        document,
        [
            _issue(
                document,
                issue_id=UUID("00000000-0000-0000-0000-000000002201"),
                block_index=0,
                original="错误词",
                suggestion="正确词",
                message="请替换编辑后文本中的错误词。",
            ),
            _issue(
                document,
                issue_id=UUID("00000000-0000-0000-0000-000000002202"),
                block_index=1,
                original="保密",
                suggestion="公开",
                message="请复核保密提示。",
            ),
        ],
        {},
    )
    db_session.commit()


def _document(texts: list[str], *, version: int) -> DocumentModel:
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000111"),
        file_type=FileType.TXT,
        source_name="sample.txt",
        version=version,
        blocks=[
            TextBlock(
                block_id=f"p-{index + 1:06d}",
                kind="paragraph",
                text=text,
                page=index + 1,
                paragraph_index=index,
                parent_id=None,
                style={"style_name": "Normal"},
                source_locator={"paragraph_index": index},
            )
            for index, text in enumerate(texts)
        ],
        metadata={"language": "zh-CN"},
    )


def _issue(
    document: DocumentModel,
    *,
    issue_id: UUID,
    block_index: int,
    original: str,
    suggestion: str,
    message: str,
) -> Issue:
    block = document.blocks[block_index]
    start = block.text.index(original)
    return Issue(
        issue_id=issue_id,
        document_id=document.document_id,
        document_version=document.version,
        block_id=block.block_id,
        page=block.page,
        start=start,
        end=start + len(original),
        original=original,
        suggestion=suggestion,
        alternatives=[suggestion],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer="character",
        message=message,
        rule_id=f"task-11-{issue_id.hex[-4:]}",
        source="task-11-e2e",
        source_version="1",
        confidence=1.0,
        auto_fixable=True,
        context=block.text,
    )


def _put_decisions(
    client: TestClient,
    job_id: str,
    decisions: list[dict[str, object]],
) -> dict[str, object]:
    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json={"decisions": decisions},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert all(outcome["status"] == "applied" for outcome in payload["outcomes"])
    return payload


def _active_version_id(client: TestClient, job_id: str) -> str:
    response = client.get(f"/api/v1/jobs/{job_id}/versions")
    assert response.status_code == 200
    active_version_id = response.json()["active_version_id"]
    assert isinstance(active_version_id, str)
    return active_version_id


def _derived_hash(client: TestClient, job_id: str, version_id: str) -> str:
    return str(_derived_content(client, job_id, version_id)["decision_snapshot_sha256"])


def _derived_content(
    client: TestClient,
    job_id: str,
    version_id: str,
) -> dict[str, object]:
    response = client.get(
        f"/api/v1/jobs/{job_id}/versions/{version_id}/derived",
        params={"view": "modified"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def _preview_plain_text(blocks: object) -> str:
    assert isinstance(blocks, list)
    return "\n\n".join(
        str(block["text"])
        for block in blocks
        if isinstance(block, dict)
    )


def _normalize_plain_text(text: str) -> str:
    normalized_newlines = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized_newlines.split("\n")).strip()


_INITIAL_UPLOAD = "祕密项目需要错误词。\n第二段保密合同保留。"
