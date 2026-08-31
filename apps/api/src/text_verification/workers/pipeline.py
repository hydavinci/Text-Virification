from uuid import UUID

from text_verification.application import VerificationCommand, VerificationPipeline
from text_verification.domain.jobs import JobRead, JobStatus, TerminalJobStateError
from text_verification.domain.verification import (
    VerificationExecutionMode,
    VerificationOptions,
)
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import InvalidUpload, JobStorage
from text_verification.infrastructure.verification_repository import VerificationRepository

COMPLETED_EVENT_MESSAGE = "处理完成"
CHECKING_ENGLISH_EVENT_MESSAGE = "正在检查英文"
CHECKING_CHINESE_EVENT_MESSAGE = "正在检查中文"
CHECKING_SENSITIVE_EVENT_MESSAGE = "正在检查敏感词"
CHECKING_FORMAT_EVENT_MESSAGE = "正在检查格式"
PARSING_EVENT_MESSAGE = "开始解析"
UPLOAD_VALIDATED_EVENT_MESSAGE = "上传校验完成"
MISSING_UPLOAD_MESSAGE = "Stored upload is unavailable."

CHECKING_STAGES = (
    (JobStatus.CHECKING_FORMAT, 50, CHECKING_FORMAT_EVENT_MESSAGE),
    (JobStatus.CHECKING_SENSITIVE, 65, CHECKING_SENSITIVE_EVENT_MESSAGE),
    (JobStatus.CHECKING_CHINESE, 80, CHECKING_CHINESE_EVENT_MESSAGE),
    (JobStatus.CHECKING_ENGLISH, 90, CHECKING_ENGLISH_EVENT_MESSAGE),
)
ACTIVE_PIPELINE_STATUSES = (
    JobStatus.PARSING,
    *(status for status, _, _ in CHECKING_STAGES),
)


class PipelineRunner:
    def __init__(
        self,
        repository: JobRepository,
        verification_repository: VerificationRepository,
        storage: JobStorage,
        pipeline: VerificationPipeline,
    ) -> None:
        self._repository = repository
        self._verification_repository = verification_repository
        self._storage = storage
        self._pipeline = pipeline

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

        if job.status not in ACTIVE_PIPELINE_STATUSES:
            return

        result = self._verification_repository.get_result_for_job(job_id)
        if result is None:
            try:
                source_path = self._storage.source_path(job.job_id, job.file_type)
            except InvalidUpload:
                raise InvalidUpload(MISSING_UPLOAD_MESSAGE) from None

            result = self._pipeline.run(
                VerificationCommand(
                    document_id=job.job_id,
                    source_path=source_path,
                    direct_text=None,
                    source_name=job.source_name,
                    file_type=job.file_type,
                    options=VerificationOptions(),
                    execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
                )
            )

        job = self._advance_checking_stages(job)
        if job is None:
            return

        if self._verification_repository.get_result_for_job(job_id) is None:
            self._verification_repository.save_result(job_id, result)
            self._verification_repository.commit()

        self._transition_and_reload(
            job_id,
            JobStatus.COMPLETED,
            100,
            COMPLETED_EVENT_MESSAGE,
        )

    def _advance_checking_stages(self, job: JobRead) -> JobRead | None:
        current_stage_index = ACTIVE_PIPELINE_STATUSES.index(job.status)
        completed_stages = current_stage_index
        for status, progress, message in CHECKING_STAGES[completed_stages:]:
            next_job = self._transition_and_reload(job.job_id, status, progress, message)
            if next_job is None:
                return None
            job = next_job
        return job

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
