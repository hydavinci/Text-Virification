from text_verification.application import VerificationCommand, VerificationPipeline
from text_verification.domain.jobs import JobRead
from text_verification.domain.ports import (
    VerificationProgressObserver,
    VerificationProgressStage,
)
from text_verification.domain.verification import (
    VerificationExecutionMode,
    VerificationOptions,
    VerificationResult,
)
from text_verification.infrastructure.storage import InvalidUpload, JobStorage

COMPLETED_EVENT_MESSAGE = "处理完成"
CHECKING_ENGLISH_EVENT_MESSAGE = "正在检查英文"
CHECKING_CHINESE_EVENT_MESSAGE = "正在检查中文"
CHECKING_SENSITIVE_EVENT_MESSAGE = "正在检查敏感词"
CHECKING_FORMAT_EVENT_MESSAGE = "正在检查格式"
PARSING_EVENT_MESSAGE = "开始解析"
UPLOAD_VALIDATED_EVENT_MESSAGE = "上传校验完成"
MISSING_UPLOAD_MESSAGE = "Stored upload is unavailable."


class PipelineRunner:
    def __init__(
        self,
        storage: JobStorage,
        pipeline: VerificationPipeline,
    ) -> None:
        self._storage = storage
        self._pipeline = pipeline

    def run(
        self,
        job: JobRead,
        progress_observer: VerificationProgressObserver,
    ) -> VerificationResult:
        progress_observer(VerificationProgressStage.PARSING)
        try:
            source_path = self._storage.source_path(job.job_id, job.file_type)
        except InvalidUpload:
            raise InvalidUpload(MISSING_UPLOAD_MESSAGE) from None

        return self._pipeline.run(
            VerificationCommand(
                document_id=job.job_id,
                source_path=source_path,
                direct_text=None,
                source_name=job.source_name,
                file_type=job.file_type,
                options=VerificationOptions(),
                execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
            ),
            progress_observer=progress_observer,
        )
