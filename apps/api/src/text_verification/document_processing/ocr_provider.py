from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from math import isfinite
from threading import Lock
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from text_verification.document_processing.errors import OcrOutputError, OcrUnavailableError

SupportedOcrLanguage = Literal["zh", "en"]
OcrEngine = Callable[[object], object]

_EXPECTED_ENGINE_INIT_ERRORS = (
    ImportError,
    ModuleNotFoundError,
    FileNotFoundError,
    OSError,
    RuntimeError,
)
_LANGUAGE_CONFIG: dict[SupportedOcrLanguage, tuple[str, str]] = {
    "zh": ("CH", "ch"),
    "en": ("EN", "en"),
}


class OcrTextBox(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    confidence: float = Field(ge=0.0, le=1.0)
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
        if not isinstance(value, Sequence) or isinstance(value, str | bytes):
            raise TypeError("bbox must be a sequence of four coordinate pairs")

        points: list[tuple[float, float]] = []
        for point in value:
            if not isinstance(point, Sequence) or isinstance(point, str | bytes):
                raise TypeError("bbox points must be coordinate pairs")
            if len(point) != 2:
                raise ValueError("bbox points must contain exactly two coordinates")
            x = float(point[0])
            y = float(point[1])
            if not isfinite(x) or not isfinite(y):
                raise ValueError("bbox coordinates must be finite")
            points.append((x, y))

        if len(points) != 4:
            raise ValueError("bbox must contain exactly four points")

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
        self._engine_lock = Lock()

    def recognize(self, image: object, language: str) -> list[OcrTextBox]:
        normalized_language = self._normalize_language(language)
        engine = self._get_engine(normalized_language)
        result = engine(image)
        return _normalize_ocr_output(result)

    def _normalize_language(self, language: str) -> SupportedOcrLanguage:
        normalized = language.strip().lower()
        if normalized not in self._supported_languages:
            raise ValueError(f"Unsupported OCR language: {language}")
        return normalized

    def _get_engine(self, language: SupportedOcrLanguage) -> OcrEngine:
        engine = self._engines.get(language)
        if engine is not None:
            return engine

        with self._engine_lock:
            engine = self._engines.get(language)
            if engine is None:
                engine = self._create_engine(language)
                self._engines[language] = engine
        return engine

    def _create_engine(self, language: SupportedOcrLanguage) -> OcrEngine:
        try:
            module = importlib.import_module("rapidocr")
            constructor = getattr(module, "RapidOCR", None)
            if not callable(constructor):
                raise OcrOutputError("rapidocr module does not expose a callable RapidOCR")
            params = {"Rec.lang_type": _rapidocr_language(module, language)}
            engine = constructor(params=params)
            if not callable(engine):
                raise OcrOutputError("RapidOCR constructor returned a non-callable engine")
            return cast(OcrEngine, engine)
        except _EXPECTED_ENGINE_INIT_ERRORS as error:
            raise OcrUnavailableError() from error


def _rapidocr_language(module: object, language: SupportedOcrLanguage) -> object:
    enum_name, fallback = _LANGUAGE_CONFIG[language]
    enum_container = getattr(module, "LangRec", None)
    if enum_container is None:
        return fallback
    return getattr(enum_container, enum_name, fallback)


def _normalize_ocr_output(result: object) -> list[OcrTextBox]:
    payload = _payload_view(result)
    raw_boxes = payload.get("boxes")
    raw_texts = payload.get("txts")
    raw_scores = payload.get("scores")

    if _is_empty_result(raw_boxes, raw_texts, raw_scores):
        return []

    if raw_boxes is None or raw_texts is None or raw_scores is None:
        raise OcrOutputError("OCR provider output must include boxes, txts, and scores")

    boxes = _as_sequence(raw_boxes, field_name="boxes")
    texts = _as_sequence(raw_texts, field_name="txts")
    scores = _as_sequence(raw_scores, field_name="scores")

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


def _is_empty_result(
    boxes: object,
    texts: object,
    scores: object,
) -> bool:
    return all(_is_missing_or_empty(value) for value in (boxes, texts, scores))


def _is_missing_or_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return len(value) == 0
    return False


def _as_sequence(value: object, *, field_name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise OcrOutputError(f"OCR provider output field {field_name} must be a sequence")
    return cast(Sequence[object], value)
