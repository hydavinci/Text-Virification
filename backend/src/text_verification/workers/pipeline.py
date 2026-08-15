from pathlib import Path
from uuid import UUID

from text_verification.domain.jobs import JobRead, JobStatus
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

        self._repository.transition(
            job_id,
            JobStatus.UPLOAD_VALIDATED,
            10,
            UPLOAD_VALIDATED_EVENT_MESSAGE,
        )
        self._repository.commit()

        self._repository.transition(
            job_id,
            JobStatus.PARSING,
            25,
            PARSING_EVENT_MESSAGE,
        )
        self._repository.commit()

        if not self._source_path(job).is_file():
            raise InvalidUpload(MISSING_UPLOAD_MESSAGE)

        self._repository.transition(
            job_id,
            JobStatus.COMPLETED,
            100,
            COMPLETED_EVENT_MESSAGE,
        )
        self._repository.commit()

    def _source_path(self, job: JobRead) -> Path:
        return self._storage.job_directory(job.job_id) / f"source.{job.file_type.value}"

