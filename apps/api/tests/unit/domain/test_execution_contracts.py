from uuid import uuid4

import pytest
from pydantic import ValidationError

from text_verification.config import Settings
from text_verification.domain.documents import FileType, TextBlock
from text_verification.domain.verification import (
    Scenario,
    VerificationAnalysisMode,
    VerificationExecutionMode,
    VerificationResult,
    VerificationStatistics,
    VerificationSummary,
)


def test_verification_result_separates_transport_from_analysis_mode() -> None:
    result = VerificationResult(
        verification_run_id=uuid4(),
        document_id=uuid4(),
        source_version="sha256:direct",
        source_name="direct.txt",
        file_type=FileType.TXT,
        scenario=Scenario.GENERAL,
        text="clean",
        blocks=(
            TextBlock(
                block_id="p-0",
                kind="paragraph",
                text="clean",
                global_start=0,
                global_end=5,
                block_start=0,
                block_end=5,
                page=None,
                paragraph_index=0,
                table_index=None,
                row_index=None,
                cell_index=None,
                bbox=None,
                parent_id=None,
                style={},
                source_locator={"paragraph_index": 0},
            ),
        ),
        parser_name="test-parser",
        parser_version="1",
        stats=VerificationStatistics(
            char_count=5,
            char_count_no_space=5,
            line_count=1,
            paragraph_count=1,
            language="en",
            primary_count=1,
            primary_label="总单词数",
        ),
        issues=(),
        summary=VerificationSummary(total=0),
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
        analysis_mode=VerificationAnalysisMode.LOCAL_ONLY,
    )

    assert result.execution_mode.value == "synchronous"
    assert result.analysis_mode.value == "local_only"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_max_review", 201),
        ("llm_context_radius", 2001),
        ("llm_timeout", 301.0),
    ],
)
def test_settings_reject_excessive_llm_limits(field: str, value: int | float) -> None:
    with pytest.raises(ValidationError, match=field):
        Settings(**{field: value})
