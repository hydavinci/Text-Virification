import subprocess
import sys

import pytest

from text_verification.compatibility.analyzer import TextAnalyzer


def analyze(text: str, **kwargs: object):
    return TextAnalyzer().analyze(
        text, enable_security=False, enable_sensitive=False,
        enable_extended_rules=True, **kwargs,
    )


def test_dictionary_candidates_find_errors_outside_curated_list() -> None:
    issues = [i for i in analyze("This is a documment.") if i.type == "typo"]
    assert len(issues) == 1
    assert (issues[0].original, issues[0].suggestion) == ("documment", "document")
    assert issues[0].confidence < 1


def test_common_transposition_is_detected_without_extended_rules() -> None:
    issues = TextAnalyzer().analyze("This is teh file.", enable_sensitive=False)
    assert [(i.original, i.suggestion) for i in issues] == [("teh", "the")]


@pytest.mark.parametrize("text", [
    "The dose is low.",
    "She has a plan.",
    "I insist he go now.",
    "He can go now.",
    "They have a plan.",
    "AcmeCorp supports PostgreSQL and XML.",
    "Use `documment` with https://example.test/documment.",
    "The colour is grey.",
])
def test_valid_grammar_names_dialects_and_code_are_preserved(text: str) -> None:
    assert not [i for i in analyze(text) if i.type in {"typo", "grammar"}]


@pytest.mark.parametrize(("text", "original", "suggestion"), [
    ("He go to school every day.", "go", "goes"),
    ("She have a plan.", "have", "has"),
    ("They is ready.", "is", "are"),
    ("I has a question.", "has", "have"),
    ("He don't know.", "don't", "doesn't"),
    ("We was ready.", "was", "were"),
    ("He GO to school.", "GO", "GOES"),
    ("She often work here.", "work", "works"),
    ("They goes home.", "goes", "go"),
])
def test_conservative_agreement_rules_have_minimal_source_spans(
    text: str, original: str, suggestion: str,
) -> None:
    issues = [i for i in analyze(text) if i.rule_id == "en_subject_agreement"]
    assert len(issues) == 1
    issue = issues[0]
    assert issue.original == original
    assert issue.suggestion == suggestion
    assert text[issue.position:issue.end_position] == original


def test_user_standard_terms_override_spelling_candidates_without_cross_request_leak() -> None:
    text = "This documment is ready."
    glossary = [{"original": "document", "standard": "documment"}]
    assert not [i for i in analyze(text, custom_glossary=glossary) if i.type == "typo"]
    assert [i for i in analyze(text) if i.original == "documment"]


def test_extended_spelling_is_opt_in() -> None:
    issues = TextAnalyzer().analyze("A documment.", enable_sensitive=False)
    assert not any(i.rule_id == "en_dictionary_spelling" for i in issues)


def test_repeated_misspelling_keeps_every_location() -> None:
    issues = [i for i in analyze("documment and documment") if i.type == "typo"]
    assert [(i.position, i.end_position) for i in issues] == [(0, 9), (14, 23)]


def test_grammar_does_not_cross_line_or_sentence_boundaries() -> None:
    assert not [i for i in analyze("He\n go.\nShe. Have a seat.") if i.type == "grammar"]


def test_long_unknown_word_does_not_match_a_short_fragment() -> None:
    assert not [i for i in analyze("a" * 1000) if i.type == "typo"]


def test_conflicting_glossary_suggestions_do_not_change_english_agreement() -> None:
    issues = analyze(
        "She have a plan.",
        custom_glossary=[{"original": "have", "standard": "possess"}],
    )
    assert {(i.rule_id, i.suggestion) for i in issues} >= {
        ("en_subject_agreement", "has"), ("custom_glossary", "possess"),
    }


@pytest.mark.parametrize("text", [
    r"Read C:\data\documment.txt for details.",
    "Read /srv/documment.json for details.",
    "Read docs/documment.txt for details.",
    "Read documment.txt for details.",
    "Read ../documment.md for details.",
    r"Read \\server\share\documment.txt for details.",
    r'Read "C:\my files\documment.txt" for details.',
    'Read "documment draft.txt" for details.',
    "Read .env and .env.local for settings.",
])
def test_filesystem_references_are_not_spelling_candidates(text: str) -> None:
    assert not [i for i in analyze(text) if i.type == "typo"]


def test_file_protection_does_not_hide_following_prose_error() -> None:
    text = "Read documment.txt. This documment is wrong."
    issues = [i for i in analyze(text) if i.type == "typo"]
    assert [(i.original, i.position, i.end_position) for i in issues] == [
        ("documment", 25, 34),
    ]


@pytest.mark.parametrize("separator", ["-", "`", "~"])
def test_long_separator_line_does_not_trigger_quadratic_path_matching(separator: str) -> None:
    result = subprocess.run(
        [
            sys.executable, "-c",
            "from text_verification.compatibility.text_context import TextContext; "
            f"context = TextContext.build({separator!r} * 100000); "
            "assert not any(context.technical)",
        ],
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stderr
