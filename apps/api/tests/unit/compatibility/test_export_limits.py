import pytest

from text_verification.compatibility.exporters import ExportError, _build_edits


def test_modified_text_diff_rejects_adversarial_repeated_input_by_work_budget() -> None:
    repeated = "ab" * 600

    with pytest.raises(ExportError, match="work budget"):
        _build_edits(
            [],
            repeated + "x",
            "x" + repeated,
        )
