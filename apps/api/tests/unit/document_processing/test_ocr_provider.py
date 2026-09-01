import importlib
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from text_verification.document_processing.errors import OcrOutputError, OcrUnavailableError
from text_verification.document_processing.ocr_provider import (
    OcrProvider,
    OcrTextBox,
    _segments_intersect,
)


class FakeArray:
    def __init__(self, value: object) -> None:
        self._value = value

    def tolist(self) -> object:
        return self._value


def _box_points() -> list[list[float]]:
    return [[0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [0.0, 1.0]]


def _payload(
    *,
    text: object = "hello",
    confidence: object = 0.99,
    bbox: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        boxes=(bbox if bbox is not None else _box_points(),),
        txts=(text,),
        scores=(confidence,),
    )


def test_ocr_text_box_normalizes_text_confidence_and_bbox() -> None:
    box = OcrTextBox(
        text="  Hello\tworld  ",
        confidence=0.75,
        bbox=[[0, 1], [3, 1], [3, 4], [0, 4]],
    )

    assert box.text == "Hello world"
    assert box.confidence == 0.75
    assert box.bbox == ((0.0, 1.0), (3.0, 1.0), (3.0, 4.0), (0.0, 4.0))


def test_ocr_text_box_rejects_empty_normalized_text() -> None:
    with pytest.raises(ValidationError, match="text must not be empty"):
        OcrTextBox(
            text=" \n\t ",
            confidence=0.5,
            bbox=[[0, 0], [1, 0], [1, 1], [0, 1]],
        )


def test_ocr_text_box_rejects_degenerate_bbox() -> None:
    with pytest.raises(ValidationError, match="non-degenerate"):
        OcrTextBox(
            text="box",
            confidence=0.5,
            bbox=[[0, 0], [1, 0], [2, 0], [3, 0]],
        )


def test_ocr_text_box_rejects_repeated_vertices() -> None:
    with pytest.raises(ValidationError, match="distinct"):
        OcrTextBox(
            text="box",
            confidence=0.5,
            bbox=[[0, 0], [2, 0], [2, 0], [0, 1]],
        )


def test_ocr_text_box_accepts_clockwise_and_counterclockwise_quadrilaterals() -> None:
    clockwise = OcrTextBox(
        text="cw",
        confidence=0.5,
        bbox=[[0, 0], [4, 1], [3, 4], [-1, 3]],
    )
    counterclockwise = OcrTextBox(
        text="ccw",
        confidence=0.5,
        bbox=[[0, 0], [-1, 3], [3, 4], [4, 1]],
    )

    assert clockwise.bbox == ((0.0, 0.0), (4.0, 1.0), (3.0, 4.0), (-1.0, 3.0))
    assert counterclockwise.bbox == ((0.0, 0.0), (-1.0, 3.0), (3.0, 4.0), (4.0, 1.0))


def test_ocr_text_box_rejects_non_adjacent_edge_touching() -> None:
    with pytest.raises(ValidationError, match="intersect|touch"):
        OcrTextBox(
            text="touch",
            confidence=0.5,
            bbox=[[0, 0], [3, 0], [1, 0], [1, 2]],
        )


def test_segments_intersect_detects_collinear_overlap_inclusively() -> None:
    assert _segments_intersect((0.0, 0.0), (3.0, 0.0), (1.0, 0.0), (2.0, 0.0)) is True


def test_provider_does_not_import_rapidocr_until_recognition(monkeypatch) -> None:
    imported: list[str] = []

    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: imported.append(name),
    )

    OcrProvider()

    assert imported == []


def test_recognize_normalizes_language_case_and_whitespace(monkeypatch) -> None:
    constructor_calls: list[dict[str, object]] = []

    def fake_constructor(*, params: dict[str, object]) -> object:
        constructor_calls.append(params)
        return lambda image: _payload(text="语言")

    fake_module = SimpleNamespace(
        RapidOCR=fake_constructor,
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)

    provider = OcrProvider()

    result = provider.recognize(object(), " ZH ")

    assert [box.text for box in result] == ["语言"]
    assert constructor_calls == [{"Rec.lang_type": "ch"}]


def test_recognize_rejects_unsupported_language_before_import_or_cache_mutation(
    monkeypatch,
) -> None:
    imported: list[str] = []
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: imported.append(name),
    )
    provider = OcrProvider()

    with pytest.raises(ValueError, match="Unsupported OCR language: FR"):
        provider.recognize(object(), "FR")

    assert imported == []
    assert provider._engines == {}


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


def test_recognize_normalizes_ndarray_like_provider_output(monkeypatch) -> None:
    class FakeEngine:
        def __call__(self, image: object) -> object:
            return SimpleNamespace(
                boxes=FakeArray([_box_points()]),
                txts=FakeArray(["  Hello\tworld  "]),
                scores=FakeArray([0.5]),
            )

    fake_module = SimpleNamespace(
        RapidOCR=lambda *, params: FakeEngine(),
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)
    provider = OcrProvider()

    result = provider.recognize(object(), "zh")

    assert result == [
        OcrTextBox(
            text="Hello world",
            confidence=0.5,
            bbox=((0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)),
        )
    ]


def test_recognize_treats_empty_ndarray_like_output_as_empty_result(monkeypatch) -> None:
    class FakeEngine:
        def __call__(self, image: object) -> object:
            return SimpleNamespace(
                boxes=FakeArray([]),
                txts=FakeArray([]),
                scores=FakeArray([]),
            )

    fake_module = SimpleNamespace(
        RapidOCR=lambda *, params: FakeEngine(),
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)
    provider = OcrProvider()

    assert provider.recognize(object(), "zh") == []


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


def test_recognize_converts_onnxruntime_session_errors_to_capability_error(monkeypatch) -> None:
    class FakeOrtBindings:
        class RuntimeException(Exception):
            pass

    def fake_constructor(*, params: dict[str, object]) -> object:
        raise FakeOrtBindings.RuntimeException("ORT session init failed with /private/model.onnx")

    fake_module = SimpleNamespace(
        RapidOCR=fake_constructor,
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )

    def fake_import_module(name: str) -> object:
        if name == "rapidocr":
            return fake_module
        if name == "onnxruntime.capi.onnxruntime_pybind11_state":
            return FakeOrtBindings
        raise AssertionError(name)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    provider = OcrProvider()

    with pytest.raises(OcrUnavailableError) as raised:
        provider.recognize(object(), "zh")

    assert raised.value.stage == "ocr"
    assert raised.value.retryable is False
    assert "private" not in raised.value.message.lower()


def test_recognize_converts_clearly_ort_runtime_errors_when_binding_import_fails(
    monkeypatch,
) -> None:
    def fake_constructor(*, params: dict[str, object]) -> object:
        raise RuntimeError("onnxruntime failed to initialize native session for model")

    fake_module = SimpleNamespace(
        RapidOCR=fake_constructor,
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )

    def fake_import_module(name: str) -> object:
        if name == "rapidocr":
            return fake_module
        if name == "onnxruntime.capi.onnxruntime_pybind11_state":
            raise ModuleNotFoundError("missing onnxruntime bindings")
        raise AssertionError(name)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    provider = OcrProvider()

    with pytest.raises(OcrUnavailableError):
        provider.recognize(object(), "zh")


def test_recognize_preserves_unrelated_runtime_errors_during_engine_creation(monkeypatch) -> None:
    class UnexpectedRuntimeError(RuntimeError):
        pass

    def fake_constructor(*, params: dict[str, object]) -> object:
        raise UnexpectedRuntimeError("constructor bug")

    fake_module = SimpleNamespace(
        RapidOCR=fake_constructor,
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )

    def fake_import_module(name: str) -> object:
        if name == "rapidocr":
            return fake_module
        if name == "onnxruntime.capi.onnxruntime_pybind11_state":
            raise ModuleNotFoundError("missing onnxruntime bindings")
        raise AssertionError(name)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    provider = OcrProvider()

    with pytest.raises(UnexpectedRuntimeError, match="constructor bug"):
        provider.recognize(object(), "zh")


def test_recognize_keeps_module_contract_errors_as_output_error(monkeypatch) -> None:
    fake_module = SimpleNamespace(LangRec=SimpleNamespace(CH="ch", EN="en"))
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)
    provider = OcrProvider()

    with pytest.raises(OcrOutputError, match="callable RapidOCR"):
        provider.recognize(object(), "zh")


def test_recognize_keeps_non_callable_engine_contract_as_output_error(monkeypatch) -> None:
    fake_module = SimpleNamespace(
        RapidOCR=lambda *, params: object(),
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)
    provider = OcrProvider()

    with pytest.raises(OcrOutputError, match="non-callable engine"):
        provider.recognize(object(), "zh")


def test_recognize_preserves_engine_exceptions(monkeypatch) -> None:
    class EngineFailure(RuntimeError):
        pass

    class FakeEngine:
        def __call__(self, image: object) -> object:
            raise EngineFailure("engine boom")

    fake_module = SimpleNamespace(
        RapidOCR=lambda *, params: FakeEngine(),
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)
    provider = OcrProvider()

    with pytest.raises(EngineFailure, match="engine boom"):
        provider.recognize(object(), "zh")


@pytest.mark.parametrize("confidence", [True, "0.5", float("nan"), float("inf"), -0.1, 1.1])
def test_recognize_rejects_invalid_confidence_scalars(
    monkeypatch,
    confidence: object,
) -> None:
    fake_module = SimpleNamespace(
        RapidOCR=lambda *, params: lambda image: _payload(confidence=confidence),
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)
    provider = OcrProvider()

    with pytest.raises(OcrOutputError, match="confidence"):
        provider.recognize(object(), "zh")


@pytest.mark.parametrize(
    "bbox",
    [
        [[True, 0], [2, 0], [2, 1], [0, 1]],
        [["0", 0], [2, 0], [2, 1], [0, 1]],
        [[0, float("nan")], [2, 0], [2, 1], [0, 1]],
        [[0, float("inf")], [2, 0], [2, 1], [0, 1]],
        [[0, 0], [1, 0], [2, 0], [3, 0]],
        [[0, 0], [2, 0], [2, 0], [0, 1]],
        [[0, 0], [2, 2], [0, 2], [2, 0]],
        [[0, 0], [3, 0], [1, 0], [1, 2]],
    ],
)
def test_recognize_rejects_invalid_bbox_geometry(monkeypatch, bbox: object) -> None:
    fake_module = SimpleNamespace(
        RapidOCR=lambda *, params: lambda image: _payload(bbox=bbox),
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)
    provider = OcrProvider()

    with pytest.raises(OcrOutputError, match="bbox|coordinate|degenerate"):
        provider.recognize(object(), "zh")


def test_recognize_rejects_generator_payloads_as_malformed_output(monkeypatch) -> None:
    def generator() -> object:
        yield _box_points()

    fake_module = SimpleNamespace(
        RapidOCR=lambda *, params: lambda image: SimpleNamespace(
            boxes=generator(),
            txts=("hello",),
            scores=(0.99,),
        ),
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)
    provider = OcrProvider()

    with pytest.raises(OcrOutputError, match="boxes"):
        provider.recognize(object(), "zh")


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


def test_recognize_converts_normalized_empty_text_to_output_error(monkeypatch) -> None:
    fake_module = SimpleNamespace(
        RapidOCR=lambda *, params: lambda image: _payload(text=" \n\t "),
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)
    provider = OcrProvider()

    with pytest.raises(OcrOutputError, match="text must not be empty"):
        provider.recognize(object(), "zh")


def test_recognize_serializes_same_language_calls(monkeypatch) -> None:
    constructor_calls: list[dict[str, object]] = []
    first_started = Event()
    allow_first_to_finish = Event()
    second_entered_engine = Event()

    class FakeEngine:
        def __init__(self) -> None:
            self._calls = 0

        def __call__(self, image: object) -> object:
            self._calls += 1
            if self._calls == 1:
                first_started.set()
                assert allow_first_to_finish.wait(1)
            else:
                second_entered_engine.set()
            return _payload(text=f"text-{self._calls}")

    def fake_constructor(*, params: dict[str, object]) -> FakeEngine:
        constructor_calls.append(params)
        return FakeEngine()

    fake_module = SimpleNamespace(
        RapidOCR=fake_constructor,
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)
    provider = OcrProvider()
    results: list[str] = []
    about_to_call_second = Event()

    def recognize_and_store(language: str, marker: Event | None = None) -> None:
        if marker is not None:
            marker.set()
        results.append(provider.recognize(object(), language)[0].text)

    first = Thread(target=recognize_and_store, args=("zh",))
    second = Thread(target=recognize_and_store, args=("zh", about_to_call_second))
    first.start()
    assert first_started.wait(1)
    second.start()
    assert about_to_call_second.wait(1)
    assert second_entered_engine.is_set() is False
    allow_first_to_finish.set()
    first.join(1)
    second.join(1)

    assert constructor_calls == [{"Rec.lang_type": "ch"}]
    assert second_entered_engine.is_set()
    assert sorted(results) == ["text-1", "text-2"]


def test_recognize_allows_different_language_calls_to_run_concurrently(monkeypatch) -> None:
    started = {"zh": Event(), "en": Event()}
    released = {"zh": Event(), "en": Event()}
    constructor_calls: list[dict[str, object]] = []

    def fake_constructor(*, params: dict[str, object]) -> object:
        language = "zh" if params["Rec.lang_type"] == "ch" else "en"

        def engine(image: object) -> object:
            started[language].set()
            assert released[language].wait(1)
            return _payload(text=language)

        constructor_calls.append(params)
        return engine

    fake_module = SimpleNamespace(
        RapidOCR=fake_constructor,
        LangRec=SimpleNamespace(CH="ch", EN="en"),
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)
    provider = OcrProvider()

    first = Thread(target=provider.recognize, args=(object(), "zh"))
    second = Thread(target=provider.recognize, args=(object(), "en"))
    first.start()
    assert started["zh"].wait(1)
    second.start()
    assert started["en"].wait(1)
    released["zh"].set()
    released["en"].set()
    first.join(1)
    second.join(1)

    assert constructor_calls == [
        {"Rec.lang_type": "ch"},
        {"Rec.lang_type": "en"},
    ]
