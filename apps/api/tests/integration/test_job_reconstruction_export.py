from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, RLock
from uuid import UUID, uuid4

import pytest
from docx import Document

from text_verification.application import (
    ArtifactLifecycleStatus,
    ArtifactReservation,
    ArtifactSnapshot,
    VerificationError,
)
from text_verification.application.factory import build_default_exporter_registry
from text_verification.application.reconstruction_export import (
    ReconstructionExportService,
)
from text_verification.document_processing.ocr_provider import OcrTextBox
from text_verification.domain.documents import (
    DocumentMetadata,
    DocumentModel,
    ExportFormat,
    FileType,
    TextBlock,
)
from text_verification.domain.jobs import JobProgressStage, JobRead, JobStatus
from text_verification.domain.verification import (
    Scenario,
    VerificationAnalysisMode,
    VerificationDegradation,
    VerificationExecutionMode,
    VerificationResult,
    VerificationStatistics,
    VerificationSummary,
)
from text_verification.exporters.registry import ExporterRegistry
from text_verification.infrastructure.storage import (
    JobOwnedSourcePathResolver,
    JobStorage,
)
from text_verification.infrastructure.verification_repository import (
    JobResultSnapshot,
    JobResultState,
)
from text_verification.parsers.pdf_parser import PdfParser

PDF_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pdf"


class _FakeOcr:
    def recognize(self, image: object, language: str) -> list[OcrTextBox]:
        del image, language
        return [
            OcrTextBox(
                text="test@example.com",
                confidence=0.99,
                bbox=((40.0, 40.0), (300.0, 40.0), (300.0, 80.0), (40.0, 80.0)),
            )
        ]


@dataclass
class _RepositoryState:
    result_by_job: dict[UUID, VerificationResult]
    artifacts: dict[UUID, ArtifactSnapshot] = field(default_factory=dict)
    result_state_by_job: dict[UUID, JobResultState] = field(default_factory=dict)
    reserve_error: Exception | None = None
    expire_on_snapshot_read: int | None = None
    replacement_result_on_snapshot_read: tuple[int, VerificationResult] | None = None
    reject_finalize_once: bool = False
    snapshot_reads: int = 0
    lock: RLock = field(default_factory=RLock)


class _InMemoryExportRepository:
    def __init__(self, state: _RepositoryState) -> None:
        self._state = state

    def read_result_snapshot(self, job_id: UUID) -> JobResultSnapshot:
        self._state.snapshot_reads += 1
        if self._state.expire_on_snapshot_read == self._state.snapshot_reads:
            return JobResultSnapshot(JobResultState.EXPIRED, None)
        replacement = self._state.replacement_result_on_snapshot_read
        if replacement is not None and replacement[0] == self._state.snapshot_reads:
            self._state.result_by_job[job_id] = replacement[1]
        result = self._state.result_by_job.get(job_id)
        state = self._state.result_state_by_job.get(
            job_id,
            JobResultState.MISSING if result is None else JobResultState.READY,
        )
        return JobResultSnapshot(
            state,
            result if state is JobResultState.READY else None,
        )

    def begin_export_artifact_repair(
        self,
        expected: ArtifactReservation,
        *,
        consistency_check,
    ) -> ArtifactReservation | None:
        with self._state.lock:
            existing = self._state.artifacts.get(expected.export_artifact_id)
            if existing is None:
                return None
            if existing.content_sha256 != expected.content_sha256:
                raise ValueError("repair metadata conflict")
            consistency_check()
            pending = replace(
                existing,
                status=ArtifactLifecycleStatus.PENDING,
                reserved_at=expected.reserved_at,
                ready_at=None,
            )
            self._state.artifacts[expected.export_artifact_id] = pending
            return ArtifactReservation(
                **{
                    key: value
                    for key, value in asdict(pending).items()
                    if key != "ready_at"
                }
            )

    def reserve_export_artifact(self, **values: object) -> ArtifactReservation:
        if self._state.reserve_error is not None:
            raise self._state.reserve_error
        artifact_id = values["export_artifact_id"]
        assert isinstance(artifact_id, UUID)
        verification_run_id = values["verification_run_id"]
        job_id = next(
            job_id
            for job_id, result in self._state.result_by_job.items()
            if result.verification_run_id == verification_run_id
        )
        with self._state.lock:
            existing = self._state.artifacts.get(artifact_id)
            if existing is not None:
                assert existing.content_sha256 == values["content_sha256"]
                return ArtifactReservation(
                    **{
                        key: value
                        for key, value in asdict(existing).items()
                        if key != "ready_at"
                    }
                )
            reservation = ArtifactReservation(
                job_id=job_id,
                **values,
                status=ArtifactLifecycleStatus.PENDING,
            )
            snapshot_values = asdict(reservation)
            self._state.artifacts[artifact_id] = ArtifactSnapshot(
                **snapshot_values,
                ready_at=None,
            )
            return reservation

    def finalize_export_artifact(
        self,
        reservation: ArtifactReservation,
        *,
        ready_at: datetime,
        consistency_check,
        require_current_result: bool = False,
    ) -> ArtifactSnapshot | None:
        del require_current_result
        consistency_check()
        with self._state.lock:
            if self._state.reject_finalize_once:
                self._state.reject_finalize_once = False
                self._state.artifacts.pop(reservation.export_artifact_id, None)
                return None
            snapshot_values = asdict(reservation)
            snapshot_values["status"] = ArtifactLifecycleStatus.READY
            snapshot = ArtifactSnapshot(
                **snapshot_values,
                ready_at=ready_at,
            )
            self._state.artifacts[reservation.export_artifact_id] = snapshot
            return snapshot

    def read_export_artifact(self, export_artifact_id: UUID) -> ArtifactSnapshot | None:
        with self._state.lock:
            return self._state.artifacts.get(export_artifact_id)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def _repository_factory(state: _RepositoryState):
    @contextmanager
    def factory() -> Iterator[_InMemoryExportRepository]:
        yield _InMemoryExportRepository(state)

    return factory


def _job_and_result(storage: JobStorage) -> tuple[JobRead, VerificationResult]:
    job_id = uuid4()
    stored = storage.save_bytes(
        job_id,
        "scanned-page.pdf",
        (PDF_FIXTURES / "scanned-page.pdf").read_bytes(),
    )
    parsed = PdfParser(ocr=_FakeOcr()).parse(stored.path).model_copy(
        update={"document_id": job_id, "source_name": "scanned-page.pdf"}
    )
    now = datetime(2026, 9, 2, 4, 0, tzinfo=UTC)
    job = JobRead(
        job_id=job_id,
        source_name=parsed.source_name,
        file_type=FileType.PDF,
        size_bytes=stored.size_bytes,
        status=JobStatus.COMPLETED,
        progress=100,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    return job, _result(parsed)


def _result(document: DocumentModel) -> VerificationResult:
    return VerificationResult(
        verification_run_id=uuid4(),
        document_id=document.document_id,
        source_version=document.source_version,
        source_name=document.source_name,
        file_type=document.file_type,
        scenario=Scenario.GENERAL,
        text=document.text,
        blocks=tuple(document.blocks),
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        metadata=document.metadata,
        ocr_requirement=document.metadata.pdf_ocr_requirement,
        stats=VerificationStatistics(
            char_count=len(document.text),
            char_count_no_space=len(document.text.replace(" ", "")),
            line_count=1,
            paragraph_count=1,
            language="en",
            primary_count=len(document.text.split()),
            primary_label="英文单词",
        ),
        issues=(),
        summary=VerificationSummary(total=0),
        execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
        analysis_mode=VerificationAnalysisMode.LOCAL_ONLY,
        degradation=VerificationDegradation(),
    )


def _service(
    storage: JobStorage,
    state: _RepositoryState,
    *,
    registry_calls: list[object] | None = None,
) -> ReconstructionExportService:
    def registry_factory(resolver):
        if registry_calls is not None:
            registry_calls.append(resolver)
        return build_default_exporter_registry(
            anchored_source_resolver=resolver,
            max_output_bytes=storage.max_document_bytes,
        )

    return ReconstructionExportService(
        storage,
        _repository_factory(state),
        exporter_registry_factory=registry_factory,
    )


def test_reconstructs_persisted_ocr_document_and_downloads_verified_artifact(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState({job.job_id: result})
    stages: list[JobProgressStage] = []

    artifact = _service(storage, state).export(
        job,
        ExportFormat.DOCX_RECONSTRUCTION,
        progress_observer=stages.append,
    )
    download = _service(storage, state).download(
        job.job_id,
        artifact.export_artifact_id,
    )

    assert stages == [JobProgressStage.EXPORTING, JobProgressStage.FINALIZING]
    assert artifact.job_id == job.job_id
    assert artifact.file_type is FileType.DOCX
    rebuilt = Document(download.path)
    assert any("test@example.com" in paragraph.text for paragraph in rebuilt.paragraphs)
    assert download.handle.content_sha256 == artifact.content_sha256
    download.handle.close()


def test_reconstruction_eligibility_uses_canonical_structure_not_filename(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=1024)
    job_id = uuid4()
    now = datetime(2026, 9, 2, 4, 0, tzinfo=UTC)
    job = JobRead(
        job_id=job_id,
        source_name="looks-scanned.pdf",
        file_type=FileType.PDF,
        size_bytes=4,
        status=JobStatus.COMPLETED,
        progress=100,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    flat = DocumentModel(
        document_id=job_id,
        source_version="sha256:flat",
        file_type=FileType.PDF,
        source_name=job.source_name,
        text="flat",
        blocks=[
            TextBlock(
                block_id="p-0",
                kind="paragraph",
                text="flat",
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
        parser_name="compatibility-flat",
        parser_version="1",
        metadata=DocumentMetadata(),
    )
    state = _RepositoryState({job_id: _result(flat)})

    with pytest.raises(VerificationError) as raised:
        _service(storage, state).export(job, ExportFormat.DOCX_RECONSTRUCTION)

    assert raised.value.code == "document_not_reconstructable"
    assert raised.value.stage == "exporting"
    assert raised.value.retryable is False
    assert state.artifacts == {}


def test_export_expiry_before_render_returns_gone_without_artifact(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState(
        {job.job_id: result},
        result_state_by_job={job.job_id: JobResultState.EXPIRED},
    )
    registry_calls: list[object] = []

    with pytest.raises(VerificationError) as raised:
        _service(
            storage,
            state,
            registry_calls=registry_calls,
        ).export(job, ExportFormat.DOCX_RECONSTRUCTION)

    assert raised.value.code == "job_result_expired"
    assert registry_calls == []
    assert state.artifacts == {}


def test_export_expiry_after_render_before_publish_leaves_no_artifact(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState(
        {job.job_id: result},
        expire_on_snapshot_read=2,
    )

    with pytest.raises(VerificationError) as raised:
        _service(storage, state).export(job, ExportFormat.DOCX_RECONSTRUCTION)

    assert raised.value.code == "job_result_expired"
    assert state.artifacts == {}
    assert not list((storage._root / "artifacts").rglob("*.docx"))


def test_concurrent_cleanup_wins_after_render_barrier_before_publish(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState({job.job_id: result})
    rendered = Event()
    release = Event()

    def registry_factory(resolver):
        delegate = build_default_exporter_registry(
            anchored_source_resolver=resolver,
            max_output_bytes=storage.max_document_bytes,
        ).get(ExportFormat.DOCX_RECONSTRUCTION)

        class BlockingExporter:
            file_type = ExportFormat.DOCX_RECONSTRUCTION

            def export(self, document: DocumentModel, target: Path) -> Path:
                exported = delegate.export(document, target)
                rendered.set()
                if not release.wait(timeout=2):
                    raise TimeoutError("cleanup barrier was not released")
                return exported

        return ExporterRegistry([BlockingExporter()])

    service = ReconstructionExportService(
        storage,
        _repository_factory(state),
        exporter_registry_factory=registry_factory,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            service.export,
            job,
            ExportFormat.DOCX_RECONSTRUCTION,
        )
        assert rendered.wait(timeout=2)
        state.result_state_by_job[job.job_id] = JobResultState.EXPIRED
        release.set()
        with pytest.raises(VerificationError) as raised:
            future.result(timeout=5)

    assert raised.value.code == "job_result_expired"
    assert state.artifacts == {}
    assert not list((storage._root / "artifacts").rglob("*.docx"))


def test_export_expiry_after_publish_before_finalize_aborts_file_and_metadata(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState(
        {job.job_id: result},
        reject_finalize_once=True,
    )

    with pytest.raises(VerificationError) as raised:
        _service(storage, state).export(job, ExportFormat.DOCX_RECONSTRUCTION)

    assert raised.value.code == "job_result_expired"
    assert state.artifacts == {}
    assert not list((storage._root / "artifacts").rglob("*.docx"))


def test_export_result_supersession_after_render_prevents_publish(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    replacement = result.model_copy(
        update={
            "verification_run_id": uuid4(),
            "source_version": "sha256:replacement",
        }
    )
    state = _RepositoryState(
        {job.job_id: result},
        replacement_result_on_snapshot_read=(2, replacement),
    )

    with pytest.raises(VerificationError) as raised:
        _service(storage, state).export(job, ExportFormat.DOCX_RECONSTRUCTION)

    assert raised.value.code == "export_source_superseded"
    assert state.artifacts == {}
    assert not list((storage._root / "artifacts").rglob("*.docx"))


def test_repeated_and_concurrent_exports_share_one_artifact_reference(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState({job.job_id: result})
    registry_calls: list[object] = []
    service = _service(storage, state, registry_calls=registry_calls)

    with ThreadPoolExecutor(max_workers=2) as executor:
        references = list(
            executor.map(
                lambda _: service.export(job, ExportFormat.DOCX_RECONSTRUCTION),
                range(2),
            )
        )
    repeated = service.export(job, ExportFormat.DOCX_RECONSTRUCTION)

    assert references[0] == references[1] == repeated
    assert len(state.artifacts) == 1
    assert len(list((storage._root / "artifacts" / str(job.job_id)).glob("*.docx"))) == 1
    assert not list(storage.job_directory(job.job_id).glob("*.reconstructing.docx"))
    assert len(registry_calls) <= 2


def test_job_owned_source_resolver_rejects_cross_job_document(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    document = DocumentModel(
        document_id=result.document_id,
        source_version=result.source_version,
        file_type=result.file_type,
        source_name=result.source_name,
        text=result.text,
        blocks=list(result.blocks),
        parser_name=result.parser_name,
        parser_version=result.parser_version,
        metadata=result.metadata,
    ).model_copy(update={"document_id": uuid4()})

    with pytest.raises(ValueError, match="does not belong"):
        JobOwnedSourcePathResolver(
            storage,
            job.job_id,
            FileType.PDF,
        ).resolve_anchored(document)


def test_export_persistence_failure_is_typed_and_leaves_no_orphan(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState(
        {job.job_id: result},
        reserve_error=RuntimeError("database unavailable"),
    )

    with pytest.raises(VerificationError) as raised:
        _service(storage, state).export(job, ExportFormat.DOCX_RECONSTRUCTION)

    assert raised.value.code == "export_persistence_failed"
    assert raised.value.stage == "finalizing"
    assert raised.value.retryable is True
    assert state.artifacts == {}
    assert not list(storage.job_directory(job.job_id).glob("*.reconstructing.docx"))


def test_repeated_export_repairs_missing_ready_artifact_without_new_reference(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState({job.job_id: result})
    service = _service(storage, state)
    first = service.export(job, ExportFormat.DOCX_RECONSTRUCTION)
    snapshot = state.artifacts[first.export_artifact_id]
    (storage._root / snapshot.storage_key).unlink()

    repaired = service.export(job, ExportFormat.DOCX_RECONSTRUCTION)
    download = service.download(job.job_id, repaired.export_artifact_id)

    assert repaired == first
    assert download.handle.read_bytes()
    download.handle.close()


def test_repeated_export_repairs_corrupt_ready_artifact_without_new_reference(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState({job.job_id: result})
    service = _service(storage, state)
    first = service.export(job, ExportFormat.DOCX_RECONSTRUCTION)
    snapshot = state.artifacts[first.export_artifact_id]
    (storage._root / snapshot.storage_key).write_bytes(b"corrupt")

    repaired = service.export(job, ExportFormat.DOCX_RECONSTRUCTION)
    download = service.download(job.job_id, repaired.export_artifact_id)

    assert repaired == first
    assert download.handle.read_bytes()
    download.handle.close()
    assert not storage.artifact_repair_quarantine_path(
        job.job_id,
        first.export_artifact_id,
        FileType.DOCX,
    ).exists()


def test_concurrent_corrupt_ready_repairs_converge(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState({job.job_id: result})
    service = _service(storage, state)
    first = service.export(job, ExportFormat.DOCX_RECONSTRUCTION)
    snapshot = state.artifacts[first.export_artifact_id]
    (storage._root / snapshot.storage_key).write_bytes(b"corrupt")

    with ThreadPoolExecutor(max_workers=2) as executor:
        repaired = list(
            executor.map(
                lambda _: service.export(job, ExportFormat.DOCX_RECONSTRUCTION),
                range(2),
            )
        )

    assert repaired == [first, first]
    concurrent_download = service.download(job.job_id, first.export_artifact_id)
    with concurrent_download.handle:
        assert concurrent_download.handle.read_bytes()
    assert not storage.artifact_repair_quarantine_path(
        job.job_id,
        first.export_artifact_id,
        FileType.DOCX,
    ).exists()


def test_crash_after_corrupt_quarantine_is_recoverable_on_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState({job.job_id: result})
    service = _service(storage, state)
    first = service.export(job, ExportFormat.DOCX_RECONSTRUCTION)
    snapshot = state.artifacts[first.export_artifact_id]
    (storage._root / snapshot.storage_key).write_bytes(b"corrupt")
    real_publish = storage.publish_verified_artifact
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("worker stopped")
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(storage, "publish_verified_artifact", fail_once)

    with pytest.raises(VerificationError) as raised:
        service.export(job, ExportFormat.DOCX_RECONSTRUCTION)

    assert raised.value.code == "export_artifact_repair_pending"
    assert state.artifacts[first.export_artifact_id].status is ArtifactLifecycleStatus.PENDING
    assert storage.artifact_repair_quarantine_path(
        job.job_id,
        first.export_artifact_id,
        FileType.DOCX,
    ).exists()

    repaired = service.export(job, ExportFormat.DOCX_RECONSTRUCTION)

    assert repaired == first
    retry_download = service.download(job.job_id, first.export_artifact_id)
    with retry_download.handle:
        assert retry_download.handle.read_bytes()
    assert not storage.artifact_repair_quarantine_path(
        job.job_id,
        first.export_artifact_id,
        FileType.DOCX,
    ).exists()


def test_corrupt_ready_repair_rejects_changed_canonical_metadata(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState({job.job_id: result})
    service = _service(storage, state)
    artifact = service.export(job, ExportFormat.DOCX_RECONSTRUCTION)
    snapshot = state.artifacts[artifact.export_artifact_id]
    (storage._root / snapshot.storage_key).write_bytes(b"corrupt")
    state.artifacts[artifact.export_artifact_id] = replace(
        snapshot,
        content_sha256="0" * 64,
    )

    with pytest.raises(VerificationError) as raised:
        service.export(job, ExportFormat.DOCX_RECONSTRUCTION)

    assert raised.value.code == "export_artifact_conflict"
    assert raised.value.retryable is False


def test_download_maps_corrupt_artifact_to_typed_unavailable_error(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState({job.job_id: result})
    service = _service(storage, state)
    artifact = service.export(job, ExportFormat.DOCX_RECONSTRUCTION)
    snapshot = state.artifacts[artifact.export_artifact_id]
    (storage._root / snapshot.storage_key).write_bytes(b"corrupt")

    with pytest.raises(VerificationError) as raised:
        service.download(job.job_id, artifact.export_artifact_id)

    assert raised.value.code == "export_artifact_unavailable"
    assert raised.value.stage == "finalizing"
    assert raised.value.retryable is True


@pytest.mark.parametrize(
    ("result_state", "expected_code"),
    [
        (JobResultState.MISSING, "job_result_expired"),
        (JobResultState.PENDING, "job_result_unavailable"),
        (JobResultState.UNAVAILABLE, "job_result_expired"),
        (JobResultState.EXPIRED, "job_result_expired"),
    ],
)
def test_download_denies_lingering_artifact_without_current_ready_result(
    tmp_path: Path,
    result_state: JobResultState,
    expected_code: str,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState({job.job_id: result})
    service = _service(storage, state)
    artifact = service.export(job, ExportFormat.DOCX_RECONSTRUCTION)
    state.result_state_by_job[job.job_id] = result_state

    with pytest.raises(VerificationError) as raised:
        service.download(job.job_id, artifact.export_artifact_id)

    assert raised.value.code == expected_code


def test_download_denies_artifact_from_superseded_result_version(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState({job.job_id: result})
    service = _service(storage, state)
    artifact = service.export(job, ExportFormat.DOCX_RECONSTRUCTION)
    state.result_by_job[job.job_id] = result.model_copy(
        update={
            "verification_run_id": uuid4(),
            "source_version": "sha256:superseded",
        }
    )

    with pytest.raises(VerificationError) as raised:
        service.download(job.job_id, artifact.export_artifact_id)

    assert raised.value.code == "export_artifact_not_found"


def test_authorized_download_descriptor_survives_retention_unlink(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState({job.job_id: result})
    service = _service(storage, state)
    artifact = service.export(job, ExportFormat.DOCX_RECONSTRUCTION)
    download = service.download(job.job_id, artifact.export_artifact_id)
    artifact_path = download.handle.path
    artifact_path.unlink()

    content = download.handle.read_bytes(require_current_entry=False)

    assert content
    download.handle.close()


def test_export_workspace_cleanup_failure_is_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=5 * 1024 * 1024)
    job, result = _job_and_result(storage)
    state = _RepositoryState({job.job_id: result})
    real_unlink = Path.unlink

    def fail_reconstruction_cleanup(
        path: Path,
        *args: object,
        **kwargs: object,
    ) -> None:
        if path.name.endswith(".reconstructing.docx"):
            raise PermissionError("locked")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_reconstruction_cleanup)

    with pytest.raises(VerificationError) as raised:
        _service(storage, state).export(job, ExportFormat.DOCX_RECONSTRUCTION)

    assert raised.value.code == "export_workspace_cleanup_failed"
    assert raised.value.stage == "finalizing"
    assert raised.value.retryable is True
    assert state.artifacts == {}
