from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from math import isfinite
from numbers import Real
from threading import Lock
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from text_verification.document_processing.errors import OcrOutputError, OcrUnavailableError

SupportedOcrLanguage = Literal["zh", "en"]
OcrEngine = Callable[[object], object]

_EXPECTED_ENGINE_INIT_ERRORS = (
    ImportError,
    ModuleNotFoundError,
    FileNotFoundError,
    OSError,
)
_LANGUAGE_CONFIG: dict[SupportedOcrLanguage, tuple[str, str]] = {
    "zh": ("CH", "ch"),
    "en": ("EN", "en"),
}


class _SupportsToList(Protocol):
    def tolist(self) -> object: ...


class _SupportsArrayProtocol(Protocol):
    def __array__(self) -> object: ...


class OcrTextBox(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    confidence: float
    bbox: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ]

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("text must be a string")
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("text must not be empty")
        return normalized

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: object) -> float:
        confidence = _coerce_real_number(value, field_name="confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return confidence

    @field_validator("bbox", mode="before")
    @classmethod
    def normalize_bbox(
        cls,
        value: object,
    ) -> tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ]:
        raw_points = _as_supported_sequence(value, field_name="bbox")
        if len(raw_points) != 4:
            raise ValueError("bbox must contain exactly four points")

        points: list[tuple[float, float]] = []
        for point in raw_points:
            raw_point = _as_supported_sequence(point, field_name="bbox point")
            if len(raw_point) != 2:
                raise ValueError("bbox points must contain exactly two coordinates")
            x = _coerce_real_number(raw_point[0], field_name="bbox coordinate")
            y = _coerce_real_number(raw_point[1], field_name="bbox coordinate")
            points.append((x, y))

        if _polygon_area(points) <= 0.0:
            raise ValueError("bbox must be a non-degenerate quadrilateral")

        return cast(
            tuple[
                tuple[float, float],
                tuple[float, float],
                tuple[float, float],
                tuple[float, float],
            ],
            tuple(points),
        )


class OcrProvider:
    def __init__(
        self,
        *,
        supported_languages: tuple[SupportedOcrLanguage, ...] = ("zh", "en"),
    ) -> None:
        self._supported_languages = frozenset(supported_languages)
        self._engines: dict[SupportedOcrLanguage, OcrEngine] = {}
        self._call_locks = {language: Lock() for language in supported_languages}

    def recognize(self, image: object, language: str) -> list[OcrTextBox]:
        normalized_language = self._normalize_language(language)
        with self._call_locks[normalized_language]:
            engine = self._engines.get(normalized_language)
            if engine is None:
                engine = self._create_engine(normalized_language)
                self._engines[normalized_language] = engine
            result = engine(image)
        try:
            return _normalize_ocr_output(result)
        except OcrOutputError:
            raise
        except (ValidationError, TypeError, ValueError) as error:
            raise OcrOutputError(str(error)) from error

    def _normalize_language(self, language: str) -> SupportedOcrLanguage:
        normalized = language.strip().lower()
        if normalized not in self._supported_languages:
            raise ValueError(f"Unsupported OCR language: {language}")
        return normalized

    def _create_engine(self, language: SupportedOcrLanguage) -> OcrEngine:
        try:
            module = importlib.import_module("rapidocr")
        except _EXPECTED_ENGINE_INIT_ERRORS as error:
            raise OcrUnavailableError() from error

        constructor = getattr(module, "RapidOCR", None)
        if not callable(constructor):
            raise OcrOutputError("rapidocr module does not expose a callable RapidOCR")

        params = {"Rec.lang_type": _rapidocr_language(module, language)}
        try:
            engine = constructor(params=params)
        except _EXPECTED_ENGINE_INIT_ERRORS as error:
            raise OcrUnavailableError() from error

        if not callable(engine):
            raise OcrOutputError("RapidOCR constructor returned a non-callable engine")
        return cast(OcrEngine, engine)


def _rapidocr_language(module: object, language: SupportedOcrLanguage) -> object:
    enum_name, fallback = _LANGUAGE_CONFIG[language]
    enum_container = getattr(module, "LangRec", None)
    if enum_container is None:
        return fallback
    return getattr(enum_container, enum_name, fallback)


def _normalize_ocr_output(result: object) -> list[OcrTextBox]:
    payload = _payload_view(result)
    boxes = _optional_supported_sequence(payload.get("boxes"), field_name="boxes")
    texts = _optional_supported_sequence(payload.get("txts"), field_name="txts")
    scores = _optional_supported_sequence(payload.get("scores"), field_name="scores")

    if boxes is None and texts is None and scores is None:
        return []
    if boxes is None or texts is None or scores is None:
        raise OcrOutputError("OCR provider output must include boxes, txts, and scores")
    if len(boxes) == len(texts) == len(scores) == 0:
        return []
    if not (len(boxes) == len(texts) == len(scores)):
        raise OcrOutputError("OCR provider output lengths do not match")

    return [
        OcrTextBox(text=text, confidence=score, bbox=box)
        for box, text, score in zip(boxes, texts, scores, strict=True)
    ]


def _payload_view(result: object) -> Mapping[str, object]:
    if isinstance(result, Mapping):
        return cast(Mapping[str, object], result)
    return {
        "boxes": getattr(result, "boxes", None),
        "txts": getattr(result, "txts", None),
        "scores": getattr(result, "scores", None),
    }


def _optional_supported_sequence(
    value: object | None,
    *,
    field_name: str,
) -> Sequence[object] | None:
    if value is None:
        return None
    return _as_supported_sequence(value, field_name=field_name)


def _as_supported_sequence(value: object, *, field_name: str) -> Sequence[object]:
    normalized = _coerce_supported_sequence(value)
    if not isinstance(normalized, Sequence) or isinstance(normalized, str | bytes):
        raise TypeError(
            f"OCR provider output field {field_name} must be a sequence or array-like value"
        )
    return cast(Sequence[object], normalized)


def _coerce_supported_sequence(value: object) -> object:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return value

    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return cast(_SupportsToList, value).tolist()

    array_protocol = getattr(value, "__array__", None)
    if callable(array_protocol):
        array_value = cast(_SupportsArrayProtocol, value).__array__()
        nested_tolist = getattr(array_value, "tolist", None)
        if callable(nested_tolist):
            return cast(_SupportsToList, array_value).tolist()

    return value


def _coerce_real_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a real numeric scalar")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _polygon_area(points: Sequence[tuple[float, float]]) -> float:
    area = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        area += (x1 * y2) - (x2 * y1)
    return abs(area) / 2.0
