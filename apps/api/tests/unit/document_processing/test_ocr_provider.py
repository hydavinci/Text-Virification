import importlib
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from text_verification.document_processing.errors import OcrOutputError, OcrUnavailableError
from text_verification.document_processing.ocr_provider import OcrProvider, OcrTextBox


def test_ocr_text_box_normalizes_text_confidence_and_bbox() -> None:
    box = OcrTextBox(
        text="  Hello\tworld  ",
        confidence=0.75,
        bbox=[[0, 1], [2, 3], [4, 5], [6, 7]],
    )

    assert box.text == "Hello world"
    assert box.confidence == 0.75
    assert box.bbox == ((0.0, 1.0), (2.0, 3.0), (4.0, 5.0), (6.0, 7.0))


def test_ocr_text_box_rejects_empty_normalized_text() -> None:
    with pytest.raises(ValidationError, match="text must not be empty"):
        OcrTextBox(
            text=" \n\t ",
            confidence=0.5,
            bbox=[[0, 0], [1, 0], [1, 1], [0, 1]],
        )


def test_provider_does_not_import_rapidocr_until_recognition(monkeypatch) -> None:
    imported: list[str] = []

    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: imported.append(name),
    )

    OcrProvider()

    assert imported == []


def test_recognize_converts_import_failures_to_capability_error(monkeypatch) -> None:
    def fake_import_module(name: str) -> object:
        raise ModuleNotFoundError("rapidocr is not installed in /private/secret")

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    provider = OcrProvider()

    with pytest.raises(OcrUnavailableError) as raised:
        provider.recognize(object(), "zh")

    assert raised.value.code == "ocr_unavailable"
    assert raised.value.stage == "ocr"
    assert raised.value.retryable is False
    assert "secret" not in raised.value.message.lower()
    assert "rapidocr" not in raised.value.message.lower()


def test_recognize_caches_one_engine_per_language(monkeypatch) -> None:
    constructor_calls: list[dict[str, object]] = []

    class FakeEngine:
        def __call__(self, image: object) -> object:
            return SimpleNamespace(
                boxes=(
                    ((0, 0), (10, 0), (10, 5), (0, 5)),
                ),
                txts=("你好",),
                scores=(0.99,),
            )

    def fake_constructor(*, params: dict[str, object]) -> FakeEngine:
        constructor_calls.append(params)
        return FakeEngine()

    fake_module = SimpleNamespace(
        RapidOCR=fake_constructor,
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)

    provider = OcrProvider()

    first = provider.recognize(object(), "zh")
    second = provider.recognize(object(), "zh")
    third = provider.recognize(object(), "en")

    assert [box.text for box in first] == ["你好"]
    assert [box.text for box in second] == ["你好"]
    assert [box.text for box in third] == ["你好"]
    assert constructor_calls == [
        {"Rec.lang_type": "ch"},
        {"Rec.lang_type": "en"},
    ]


def test_recognize_converts_expected_engine_initialization_failures(monkeypatch) -> None:
    def fake_constructor(*, params: dict[str, object]) -> object:
        raise OSError("dlopen(/private/secret/libonnxruntime.dylib) failed")

    fake_module = SimpleNamespace(
        RapidOCR=fake_constructor,
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)

    provider = OcrProvider()

    with pytest.raises(OcrUnavailableError) as raised:
        provider.recognize(object(), "zh")

    assert raised.value.stage == "ocr"
    assert raised.value.retryable is False
    assert "secret" not in raised.value.message.lower()
    assert "dlopen" not in raised.value.message.lower()


def test_recognize_rejects_malformed_provider_output(monkeypatch) -> None:
    class FakeEngine:
        def __call__(self, image: object) -> object:
            return SimpleNamespace(
                boxes=(
                    ((0, 0), (10, 0), (10, 5), (0, 5)),
                ),
                txts=("first", "second"),
                scores=(0.99,),
            )

    fake_module = SimpleNamespace(
        RapidOCR=lambda *, params: FakeEngine(),
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)

    provider = OcrProvider()

    with pytest.raises(OcrOutputError, match="lengths"):
        provider.recognize(object(), "zh")
