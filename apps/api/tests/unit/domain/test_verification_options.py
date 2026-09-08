from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from text_verification.domain.verification import (
    MAX_BANNED_WORDS,
    MAX_CUSTOM_GLOSSARY_TERMS,
    MAX_VERIFICATION_OPTIONS_JSON_BYTES,
    GlossaryTerm,
    Scenario,
    VerificationOptions,
    decode_verification_options,
    encode_verification_options,
)


def _legacy_options_payload_at_size_limit() -> dict[str, object]:
    glossary = [
        {"original": "x", "standard": ""}
        for _ in range(MAX_CUSTOM_GLOSSARY_TERMS)
    ]
    payload: dict[str, object] = {
        "scenario": "general",
        "enable_security": True,
        "enable_sensitive": True,
        "enable_ad_extreme": False,
        "custom_glossary": glossary,
        "banned_words": [],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    remaining = MAX_VERIFICATION_OPTIONS_JSON_BYTES - len(encoded)
    assert 0 <= remaining <= MAX_CUSTOM_GLOSSARY_TERMS * 200
    for term in glossary:
        added = min(remaining, 200)
        term["standard"] = "x" * added
        remaining -= added
    assert remaining == 0
    assert (
        len(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        )
        == MAX_VERIFICATION_OPTIONS_JSON_BYTES
    )
    return payload


def _custom_options() -> VerificationOptions:
    return VerificationOptions(
        scenario=Scenario.LEGAL,
        ocr_language="ja",
        enable_extended_rules=True,
        enable_security=False,
        enable_sensitive=False,
        enable_ad_extreme=True,
        custom_glossary=(
            GlossaryTerm(original="colour", standard="color"),
        ),
        banned_words=("forbidden",),
    )


def test_verification_options_snapshot_is_immutable_and_json_roundtrips() -> None:
    options = _custom_options()

    payload = encode_verification_options(options)
    restored = decode_verification_options(payload)

    assert restored == options
    assert payload == {
        "scenario": "legal",
        "ocr_language": "ja",
        "enable_extended_rules": True,
        "enable_security": False,
        "enable_sensitive": False,
        "enable_ad_extreme": True,
        "custom_glossary": [{"original": "colour", "standard": "color"}],
        "banned_words": ["forbidden"],
    }
    with pytest.raises(ValidationError):
        options.scenario = Scenario.GENERAL


def test_empty_legacy_options_payload_maps_to_fresh_defaults() -> None:
    first = decode_verification_options({})
    second = decode_verification_options({})

    assert first == VerificationOptions()
    assert second == VerificationOptions()
    assert first is not second
    assert first.ocr_language == "zh"


def test_legacy_options_at_size_limit_ignore_new_default_field_overhead() -> None:
    payload = _legacy_options_payload_at_size_limit()

    restored = decode_verification_options(payload)

    assert restored.ocr_language == "zh"
    assert restored.enable_extended_rules is False
    assert encode_verification_options(restored) == payload


def test_explicit_new_option_fields_count_toward_serialized_size_limit() -> None:
    payload = _legacy_options_payload_at_size_limit()
    payload["ocr_language"] = "zh"
    payload["enable_extended_rules"] = False

    with pytest.raises(ValidationError, match="serialized size limit"):
        VerificationOptions.model_validate(payload)


@pytest.mark.parametrize("language", ["zh", "en", "ja"])
def test_verification_options_accepts_supported_ocr_languages(language: str) -> None:
    assert VerificationOptions(ocr_language=language).ocr_language == language


def test_verification_options_rejects_unknown_ocr_language() -> None:
    with pytest.raises(ValidationError):
        VerificationOptions(ocr_language="fr")


@pytest.mark.parametrize(
    "values",
    [
        {
            "custom_glossary": [
                {"original": f"term-{index}", "standard": "x"}
                for index in range(MAX_CUSTOM_GLOSSARY_TERMS + 1)
            ]
        },
        {
            "banned_words": [
                f"word-{index}" for index in range(MAX_BANNED_WORDS + 1)
            ]
        },
        {"banned_words": ["x" * 201]},
    ],
)
def test_verification_options_snapshot_rejects_oversized_values(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        VerificationOptions.model_validate(values)


def test_verification_options_codec_rejects_unknown_or_non_json_payload() -> None:
    with pytest.raises(ValueError):
        decode_verification_options({"unknown": True})
    with pytest.raises(ValueError):
        decode_verification_options({"banned_words": [object()]})
