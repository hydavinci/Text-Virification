from uuid import UUID

from text_verification.domain.jobs import JobRead, JobStatus, TerminalJobStateError
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import InvalidUpload, JobStorage

COMPLETED_EVENT_MESSAGE = "处理完成"
PARSING_EVENT_MESSAGE = "开始解析"
UPLOAD_VALIDATED_EVENT_MESSAGE = "上传校验完成"
MISSING_UPLOAD_MESSAGE = "Stored upload is unavailable."


class PipelineRunner:
    def __init__(self, repository: JobRepository, storage: JobStorage) -> None:
        self._repository = repository
        self._storage = storage

    def run(self, job_id: UUID) -> None:
        job = self._repository.get_job(job_id)
        if job is None:
            return

        if job.status == JobStatus.QUEUED:
            job = self._transition_and_reload(
                job_id,
                JobStatus.UPLOAD_VALIDATED,
                10,
                UPLOAD_VALIDATED_EVENT_MESSAGE,
            )
            if job is None:
                return

        if job.status == JobStatus.UPLOAD_VALIDATED:
            job = self._transition_and_reload(
                job_id,
                JobStatus.PARSING,
                25,
                PARSING_EVENT_MESSAGE,
            )
            if job is None:
                return

        if job.status == JobStatus.PARSING:
            try:
                self._storage.source_path(job.job_id, job.file_type)
            except InvalidUpload:
                raise InvalidUpload(MISSING_UPLOAD_MESSAGE) from None

            self._transition_and_reload(
                job_id,
                JobStatus.COMPLETED,
                100,
                COMPLETED_EVENT_MESSAGE,
            )

    def _transition_and_reload(
        self,
        job_id: UUID,
        status: JobStatus,
        progress: int,
        message: str,
    ) -> JobRead | None:
        try:
            self._repository.transition(job_id, status, progress, message)
            self._repository.commit()
        except TerminalJobStateError:
            self._repository.rollback()
            return None
        return self._repository.get_job(job_id)
