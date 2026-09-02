from __future__ import annotations

import pytest
from pydantic import ValidationError

from text_verification.domain.verification import (
    MAX_BANNED_WORDS,
    MAX_CUSTOM_GLOSSARY_TERMS,
    GlossaryTerm,
    Scenario,
    VerificationOptions,
    decode_verification_options,
    encode_verification_options,
)


def _custom_options() -> VerificationOptions:
    return VerificationOptions(
        scenario=Scenario.LEGAL,
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
