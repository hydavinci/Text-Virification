from collections.abc import Callable
from uuid import UUID

from text_verification.checkers.models import (
    CHECK_CATEGORY_ORDER,
    CheckerProgress,
    CheckOptions,
    CheckRunResult,
    CheckScenario,
)
from text_verification.checkers.registry import CheckerRegistry
from text_verification.domain.documents import DocumentModel
from text_verification.domain.jobs import (
    JobEventMetadata,
    JobRead,
    JobStatus,
    TerminalJobStateError,
)
from text_verification.domain.ports import CheckContext
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.revision_repository import RevisionRepository
from text_verification.infrastructure.storage import InvalidUpload, JobStorage
from text_verification.parsers.registry import ParserRegistry

COMPLETED_EVENT_MESSAGE = "处理完成"
CHECKING_EVENT_MESSAGE = "检查进度已更新"
PARTIAL_EVENT_MESSAGE = "部分完成"
PARSING_EVENT_MESSAGE = "开始解析"
UPLOAD_VALIDATED_EVENT_MESSAGE = "上传校验完成"
MISSING_UPLOAD_MESSAGE = "上传文件不存在或已被清理，请重新上传。"
DEFAULT_CHECK_CONTEXT = CheckContext((), ())


class PipelineRunner:
    def __init__(
        self,
        repository: JobRepository,
        analysis_repository: AnalysisRepository,
        storage: JobStorage,
        parsers: ParserRegistry,
        checkers: CheckerRegistry,
        check_context: CheckContext = DEFAULT_CHECK_CONTEXT,
        *,
        revision_repository: RevisionRepository | None = None,
    ) -> None:
        self._repository = repository
        self._analysis_repository = analysis_repository
        self._storage = storage
        self._parsers = parsers
        self._checkers = checkers
        self._check_context = check_context
        self._revision_repository = revision_repository

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
            self._run_analysis(job)

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

    def _run_analysis(self, job: JobRead) -> None:
        try:
            source_path = self._storage.source_path(job.job_id, job.file_type)
        except InvalidUpload:
            raise InvalidUpload(MISSING_UPLOAD_MESSAGE) from None

        parser = self._parsers.get(job.file_type)
        document = parser.parse(
            source_path,
            document_id=job.job_id,
            source_name=job.source_name,
        )
        options = self._check_options_for(job)
        enabled_count = len(options.enabled_categories)
        attempted_count = 0

        def persist_progress(checker_progress: CheckerProgress) -> None:
            nonlocal attempted_count
            attempted_count += 1
            progress = 25 + (70 * attempted_count) // enabled_count
            self._repository.record_progress(
                job.job_id,
                progress=progress,
                message=CHECKING_EVENT_MESSAGE,
                metadata=JobEventMetadata(
                    current_category=checker_progress.current_category,
                    completed_categories=list(checker_progress.completed_categories),
                    issue_count=checker_progress.issue_count,
                ),
            )
            self._repository.commit()

        result = self._run_checks(document, options, on_progress=persist_progress)
        self._analysis_repository.replace_analysis(
            job.job_id,
            document,
            result.issues,
            result.failures,
        )
        terminal_status = JobStatus.PARTIAL if result.failures else JobStatus.COMPLETED
        terminal_message = PARTIAL_EVENT_MESSAGE if result.failures else COMPLETED_EVENT_MESSAGE
        self._repository.transition(job.job_id, terminal_status, 100, terminal_message)
        self._repository.commit()

    def analyze_document(
        self,
        version_id: UUID,
        document: DocumentModel,
        options: CheckOptions,
    ) -> CheckRunResult:
        if self._revision_repository is None:
            raise RuntimeError("Revision repository is required for versioned analysis.")
        revision_repository = self._revision_repository

        revision_repository.mark_analyzing(version_id)
        revision_repository.commit()

        def persist_progress(progress: CheckerProgress) -> None:
            revision_repository.record_progress(version_id, progress)
            revision_repository.commit()

        result = self._run_checks(
            document,
            options,
            on_progress=persist_progress,
        )
        revision_repository.complete_analysis(
            version_id,
            document,
            result.issues,
            result.failures,
        )
        return result

    def _run_checks(
        self,
        document: DocumentModel,
        options: CheckOptions,
        *,
        on_progress: Callable[[CheckerProgress], None] | None = None,
    ) -> CheckRunResult:
        return self._checkers.run(
            document,
            self._check_context,
            options,
            on_progress=on_progress,
        )

    def _check_options_for(self, job: JobRead) -> CheckOptions:
        scenario = getattr(job, "scenario", None) or CheckScenario.GENERAL
        enabled_categories = getattr(job, "enabled_categories", None)
        if enabled_categories is None:
            enabled_categories = CHECK_CATEGORY_ORDER
        return CheckOptions(scenario=scenario, enabled_categories=enabled_categories)
