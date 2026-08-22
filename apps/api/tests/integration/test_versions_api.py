from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from text_verification.api.dependencies import get_db_session
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import (
    DecisionAction,
    DecisionCommand,
    Issue,
    IssueSeverity,
)
from text_verification.domain.jobs import JobStatus
from text_verification.domain.revisions import DocumentVersionRead
from text_verification.infrastructure.decision_repository import DecisionRepository
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.revision_repository import RevisionRepository


@pytest.fixture(autouse=True)
def override_db_session(app: FastAPI, db_session: Session) -> None:
    def _db_session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _db_session_override


def test_list_versions_returns_ordered_versions_and_active_version(
    client,
    db_session: Session,
) -> None:
    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    revisions = RevisionRepository(db_session)
    first = _create_succeeded_version(
        revisions,
        job_id,
        _build_document([("第一版", 1)], version=1),
    )
    second = _create_succeeded_version(
        revisions,
        job_id,
        _build_document([("第二版", 2)], version=2),
        parent_version_id=first.version_id,
        idempotency_key="edit-1",
    )
    failed = _create_failed_version(
        revisions,
        job_id,
        parent_version_id=second.version_id,
        idempotency_key="edit-2",
    )
    db_session.commit()

    response = client.get(f"/api/v1/jobs/{job_id}/versions")

    assert response.status_code == 200
    payload = response.json()
    versions = payload["versions"]

    assert payload["job_id"] == str(job_id)
    assert payload["active_version_id"] == str(second.version_id)
    assert [item["version_id"] for item in versions] == [
        str(first.version_id),
        str(second.version_id),
        str(failed.version_id),
    ]
    assert [item["parent_version_id"] for item in versions] == [
        None,
        str(first.version_id),
        str(second.version_id),
    ]
    assert [item["revision_number"] for item in versions] == [1, 2, 3]
    assert [item["status"] for item in versions] == ["succeeded", "succeeded", "failed"]
    assert [item["source_kind"] for item in versions] == ["upload", "edit", "edit"]
    assert [item["created_reason"] for item in versions] == ["upload", "edited", "edited"]
    assert [item["content_sha256"] for item in versions] == [
        first.content_sha256,
        second.content_sha256,
        None,
    ]
    assert versions[2]["failure_code"] == "checker_failed"
    assert versions[2]["failure_message"] == "分析失败。"
    for item in versions:
        assert item["created_at"].endswith("Z")
    assert versions[0]["started_at"].endswith("Z")
    assert versions[0]["completed_at"].endswith("Z")
    assert versions[1]["started_at"].endswith("Z")
    assert versions[1]["completed_at"].endswith("Z")
    assert versions[2]["started_at"].endswith("Z")
    assert versions[2]["completed_at"].endswith("Z")


def test_create_draft_copies_base_blocks_and_returns_existing_active_draft(
    client,
    db_session: Session,
) -> None:
    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    base_version = _create_succeeded_version(
        RevisionRepository(db_session),
        job_id,
        _build_document([("第一段", 1), ("第二段", 2)], version=1),
    )
    db_session.commit()

    first_response = client.post(
        f"/api/v1/jobs/{job_id}/drafts",
        json={"base_version_id": str(base_version.version_id)},
    )
    second_response = client.post(
        f"/api/v1/jobs/{job_id}/drafts",
        json={"base_version_id": str(base_version.version_id)},
    )
    get_response = client.get(
        f"/api/v1/jobs/{job_id}/drafts/{first_response.json()['draft_id']}"
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert get_response.status_code == 200
    assert first_response.json() == second_response.json() == get_response.json()
    assert first_response.json()["base_version_id"] == str(base_version.version_id)
    assert first_response.json()["revision"] == 1
    assert [block["block_id"] for block in first_response.json()["blocks"]] == [
        "p-000001",
        "p-000002",
    ]
    assert [block["text"] for block in first_response.json()["blocks"]] == [
        "第一段",
        "第二段",
    ]
    assert first_response.json()["content_sha256"] is not None


def test_create_draft_returns_structured_base_version_errors(client, db_session: Session) -> None:
    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    revisions = RevisionRepository(db_session)
    _create_succeeded_version(
        revisions,
        job_id,
        _build_document([("当前版本", 1)], version=1),
    )
    queued = revisions.create_queued_version(
        job_id,
        parent_version_id=None,
        reason="edited",
        idempotency_key="queued",
    )
    db_session.commit()

    unknown_response = client.post(
        f"/api/v1/jobs/{job_id}/drafts",
        json={"base_version_id": str(uuid4())},
    )
    invalid_response = client.post(
        f"/api/v1/jobs/{job_id}/drafts",
        json={"base_version_id": str(queued.version_id)},
    )

    assert unknown_response.status_code == 404
    assert unknown_response.json()["detail"] == {
        "code": "version_not_found",
        "message": "文档版本不存在。",
    }
    assert invalid_response.status_code == 409
    assert invalid_response.json()["detail"] == {
        "code": "invalid_base_version",
        "message": "只能基于成功版本创建草稿。",
    }


def test_stale_draft_update_returns_current_revision_and_preserves_text(
    client,
    db_session: Session,
) -> None:
    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    base_version = _create_succeeded_version(
        RevisionRepository(db_session),
        job_id,
        _build_document([("服务器文本", 1), ("第二段", 2)], version=1),
    )
    db_session.commit()
    created = client.post(
        f"/api/v1/jobs/{job_id}/drafts",
        json={"base_version_id": str(base_version.version_id)},
    ).json()

    saved = client.put(
        f"/api/v1/jobs/{job_id}/drafts/{created['draft_id']}",
        json={
            "expected_revision": 1,
            "blocks": [
                {"block_id": "p-000001", "text": "服务器文本"},
                {"block_id": "p-000002", "text": "已保存文本"},
            ],
        },
    )
    stale = client.put(
        f"/api/v1/jobs/{job_id}/drafts/{created['draft_id']}",
        json={
            "expected_revision": 1,
            "blocks": [
                {"block_id": "p-000001", "text": "本地文本"},
                {"block_id": "p-000002", "text": "本地第二段"},
            ],
        },
    )
    current = client.get(f"/api/v1/jobs/{job_id}/drafts/{created['draft_id']}")

    assert saved.status_code == 200
    assert saved.json()["revision"] == 2
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_draft_revision"
    assert stale.json()["detail"]["current_revision"] == 2
    assert current.status_code == 200
    assert current.json()["revision"] == 2
    assert [block["text"] for block in current.json()["blocks"]] == [
        "服务器文本",
        "已保存文本",
    ]


def test_update_draft_rejects_duplicate_and_missing_block_ids(
    client,
    db_session: Session,
) -> None:
    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    base_version = _create_succeeded_version(
        RevisionRepository(db_session),
        job_id,
        _build_document([("第一段", 1), ("第二段", 2)], version=1),
    )
    db_session.commit()
    draft = client.post(
        f"/api/v1/jobs/{job_id}/drafts",
        json={"base_version_id": str(base_version.version_id)},
    ).json()

    duplicate_response = client.put(
        f"/api/v1/jobs/{job_id}/drafts/{draft['draft_id']}",
        json={
            "expected_revision": 1,
            "blocks": [
                {"block_id": "p-000001", "text": "覆盖第一段"},
                {"block_id": "p-000001", "text": "重复第一段"},
            ],
        },
    )
    missing_response = client.put(
        f"/api/v1/jobs/{job_id}/drafts/{draft['draft_id']}",
        json={
            "expected_revision": 1,
            "blocks": [{"block_id": "p-000001", "text": "仅保留第一段"}],
        },
    )

    assert duplicate_response.status_code == 422
    assert duplicate_response.json()["detail"] == {
        "code": "invalid_draft_blocks",
        "message": "草稿段落列表无效，请刷新后重试。",
        "duplicate_block_ids": ["p-000001"],
        "missing_block_ids": ["p-000002"],
        "unexpected_block_ids": [],
    }
    assert missing_response.status_code == 422
    assert missing_response.json()["detail"] == {
        "code": "invalid_draft_blocks",
        "message": "草稿段落列表无效，请刷新后重试。",
        "duplicate_block_ids": [],
        "missing_block_ids": ["p-000002"],
        "unexpected_block_ids": [],
    }


def test_delete_draft_only_removes_requested_draft(client, db_session: Session) -> None:
    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    revisions = RevisionRepository(db_session)
    first_version = _create_succeeded_version(
        revisions,
        job_id,
        _build_document([("第一版", 1)], version=1),
    )
    second_version = _create_succeeded_version(
        revisions,
        job_id,
        _build_document([("第二版", 2)], version=2),
        parent_version_id=first_version.version_id,
        idempotency_key="edit-1",
    )
    db_session.commit()
    first_draft = client.post(
        f"/api/v1/jobs/{job_id}/drafts",
        json={"base_version_id": str(first_version.version_id)},
    ).json()
    second_draft = client.post(
        f"/api/v1/jobs/{job_id}/drafts",
        json={"base_version_id": str(second_version.version_id)},
    ).json()

    delete_response = client.delete(f"/api/v1/jobs/{job_id}/drafts/{first_draft['draft_id']}")
    deleted_response = client.get(f"/api/v1/jobs/{job_id}/drafts/{first_draft['draft_id']}")
    remaining_response = client.get(f"/api/v1/jobs/{job_id}/drafts/{second_draft['draft_id']}")

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert deleted_response.status_code == 404
    assert deleted_response.json()["detail"] == {
        "code": "draft_not_found",
        "message": "草稿不存在。",
    }
    assert remaining_response.status_code == 200
    assert remaining_response.json()["draft_id"] == second_draft["draft_id"]


def test_derived_endpoint_returns_modified_blocks_and_diff_segments(
    client,
    db_session: Session,
) -> None:
    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    document = _build_document([("原始正文", 1), ("第二段", 2)], version=1)
    issue = _build_issue(
        document,
        block_index=0,
        start=0,
        end=2,
        suggestion="系统首选",
    )
    version = _create_succeeded_version(
        RevisionRepository(db_session),
        job_id,
        document,
        issues=[issue],
    )
    _apply_decision(db_session, job_id, issue, replacement="最终")
    db_session.commit()

    modified = client.get(
        f"/api/v1/jobs/{job_id}/versions/{version.version_id}/derived",
        params={"view": "modified"},
    )
    diff = client.get(
        f"/api/v1/jobs/{job_id}/versions/{version.version_id}/derived",
        params={"view": "diff"},
    )

    assert modified.status_code == 200
    assert diff.status_code == 200
    assert modified.json()["decision_snapshot_sha256"] == diff.json()[
        "decision_snapshot_sha256"
    ]
    assert len(modified.json()["decision_snapshot_sha256"]) == 64
    assert [block["text"] for block in modified.json()["blocks"]] == [
        "最终正文",
        "第二段",
    ]
    assert diff.json()["blocks"] == [
        {
            "block_id": "p-000001",
            "segments": [
                {"kind": "delete", "text": "原始"},
                {"kind": "insert", "text": "最终"},
                {"kind": "equal", "text": "正文"},
            ],
        },
        {
            "block_id": "p-000002",
            "segments": [{"kind": "equal", "text": "第二段"}],
        },
    ]


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/v1/jobs/{job_id}/versions", None),
        ("GET", "/api/v1/jobs/{job_id}/versions/{draft_id}/derived?view=modified", None),
        ("POST", "/api/v1/jobs/{job_id}/drafts", {"base_version_id": str(uuid4())}),
        ("GET", "/api/v1/jobs/{job_id}/drafts/{draft_id}", None),
        (
            "PUT",
            "/api/v1/jobs/{job_id}/drafts/{draft_id}",
            {
                "expected_revision": 1,
                "blocks": [{"block_id": "p-000001", "text": "正文"}],
            },
        ),
        ("DELETE", "/api/v1/jobs/{job_id}/drafts/{draft_id}", None),
    ],
)
def test_version_routes_return_structured_job_not_found(
    client,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    url = path.format(
        job_id="00000000-0000-0000-0000-000000000000",
        draft_id="00000000-0000-0000-0000-000000000000",
    )

    response = client.request(method, url, json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "job_not_found",
        "message": "作业不存在。",
    }


def _seed_job(
    db_session: Session,
    *,
    status: JobStatus,
) -> UUID:
    now = datetime.now(UTC)
    job_id = uuid4()
    repository = JobRepository(db_session)
    repository.create_job(
        job_id=job_id,
        source_name="analysis.txt",
        file_type=FileType.TXT.value,
        size_bytes=16,
        storage_key=str(job_id),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    if status != JobStatus.QUEUED:
        repository.transition(
            job_id,
            status,
            100 if status in {JobStatus.COMPLETED, JobStatus.PARTIAL} else 0,
            (
                "处理完成"
                if status in {JobStatus.COMPLETED, JobStatus.PARTIAL}
                else "处理中"
            ),
            error_code="pipeline_failed" if status == JobStatus.FAILED else None,
            error_message="处理失败" if status == JobStatus.FAILED else None,
        )
    repository.commit()
    return job_id


def _create_succeeded_version(
    revisions: RevisionRepository,
    job_id: UUID,
    document: DocumentModel,
    *,
    issues: list[Issue] | None = None,
    parent_version_id: UUID | None = None,
    idempotency_key: str | None = None,
) -> DocumentVersionRead:
    version = revisions.create_queued_version(
        job_id,
        parent_version_id=parent_version_id,
        reason="upload" if parent_version_id is None else "edited",
        idempotency_key=idempotency_key,
    )
    return revisions.complete_analysis(version.version_id, document, issues or [], {})


def _create_failed_version(
    revisions: RevisionRepository,
    job_id: UUID,
    *,
    parent_version_id: UUID,
    idempotency_key: str,
) -> DocumentVersionRead:
    version = revisions.create_queued_version(
        job_id,
        parent_version_id=parent_version_id,
        reason="edited",
        idempotency_key=idempotency_key,
    )
    revisions.mark_analyzing(version.version_id)
    return revisions.fail_version(
        version.version_id,
        code="checker_failed",
        message="分析失败。",
    )


def _build_document(block_specs: list[tuple[str, int | None]], *, version: int) -> DocumentModel:
    blocks = [
        TextBlock(
            block_id=f"p-{index + 1:06d}",
            kind="paragraph",
            text=text,
            page=page,
            paragraph_index=index,
            parent_id=None,
            style={"style_name": "Normal"},
            source_locator={"paragraph_index": index},
        )
        for index, (text, page) in enumerate(block_specs)
    ]
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        file_type=FileType.TXT,
        source_name="analysis.txt",
        version=version,
        blocks=blocks,
        metadata={"language": "zh-CN"},
    )


def _build_issue(
    document: DocumentModel,
    *,
    block_index: int,
    start: int,
    end: int,
    suggestion: str,
) -> Issue:
    block = document.blocks[block_index]
    return Issue(
        issue_id=UUID(f"00000000-0000-0000-0000-{start + end + 1:012d}"),
        document_id=document.document_id,
        document_version=document.version,
        block_id=block.block_id,
        page=block.page,
        start=start,
        end=end,
        original=block.text[start:end],
        suggestion=suggestion,
        alternatives=[suggestion],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer="character",
        message="命中规则。",
        rule_id="character-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=True,
        context=block.text,
    )


def _apply_decision(
    session: Session,
    job_id: UUID,
    issue: Issue,
    *,
    replacement: str,
) -> None:
    outcome = DecisionRepository(session).apply(
        job_id,
        DecisionCommand(
            issue_id=issue.issue_id,
            issue_version=issue.document_version or 1,
            expected_revision=0,
            action=DecisionAction.ACCEPTED,
            replacement=replacement,
        ),
    )
    assert outcome.decision is not None
