from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal

import ijson  # type: ignore[import-untyped]
from fastapi import HTTPException, Request, status
from pydantic import BaseModel, ValidationError
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import FormParser, MultiPartException, MultiPartParser

MAX_JSON_STRING_ESCAPE_FACTOR = 6
MAX_JSON_BODY_OVERHEAD_BYTES = 64 * 1024
MAX_JSON_NESTING_DEPTH = 128
MAX_JSON_PARSE_CHUNK_BYTES = 64 * 1024
MAX_FORM_BODY_OVERHEAD_BYTES = 64 * 1024
MAX_FORM_FIELDS = 16


type JsonContainer = dict[str, object] | list[object]


@dataclass
class _ContainerFrame:
    value: JsonContainer
    pending_key: str | None = None


class JsonValueBuilder:
    def __init__(self) -> None:
        self._frames: list[_ContainerFrame] = []
        self.value: object | None = None
        self.complete = False

    def feed(self, event: str, value: object) -> None:
        if self.complete:
            raise ValueError("JSON value is duplicated.")
        if event == "map_key":
            if (
                not self._frames
                or not isinstance(self._frames[-1].value, dict)
                or not isinstance(value, str)
                or self._frames[-1].pending_key is not None
            ):
                raise ValueError("JSON object structure is invalid.")
            self._frames[-1].pending_key = value
            return
        if event == "start_map":
            container: JsonContainer = {}
            self._add(container)
            self._frames.append(_ContainerFrame(container))
            return
        if event == "start_array":
            container = []
            self._add(container)
            self._frames.append(_ContainerFrame(container))
            return
        if event in {"end_map", "end_array"}:
            if not self._frames:
                raise ValueError("JSON container structure is invalid.")
            frame = self._frames.pop()
            expected_type = dict if event == "end_map" else list
            if not isinstance(frame.value, expected_type):
                raise ValueError("JSON container structure is invalid.")
            if isinstance(frame.value, dict) and frame.pending_key is not None:
                raise ValueError("JSON object value is missing.")
            if not self._frames:
                self.complete = True
            return
        if event not in {
            "boolean",
            "double",
            "integer",
            "null",
            "number",
            "string",
        }:
            raise ValueError("JSON value is invalid.")
        self._add(value)
        if not self._frames:
            self.complete = True

    def _add(self, value: object) -> None:
        if not self._frames:
            if self.value is not None:
                raise ValueError("JSON value is duplicated.")
            self.value = value
            return
        frame = self._frames[-1]
        if isinstance(frame.value, list):
            frame.value.append(value)
            return
        if frame.pending_key is None:
            raise ValueError("JSON object key is missing.")
        if frame.pending_key in frame.value:
            raise ValueError("JSON object key is duplicated.")
        frame.value[frame.pending_key] = value
        frame.pending_key = None


class _JsonStringLimitScanner:
    def __init__(self, max_utf8_bytes: int) -> None:
        self._max_utf8_bytes = max_utf8_bytes
        self._in_string = False
        self._escaped = False
        self._unicode_digits = 0
        self._unicode_value = 0
        self._pending_high_surrogate: int | None = None
        self._decoded_utf8_bytes = 0

    def feed(self, chunk: bytes) -> None:
        for value in chunk:
            if not self._in_string:
                if value == 0x22:
                    self._start_string()
                continue
            if self._unicode_digits:
                self._feed_unicode_digit(value)
                continue
            if self._escaped:
                self._escaped = False
                if value == 0x75:
                    self._unicode_digits = 4
                    self._unicode_value = 0
                elif value in b'"\\/bfnrt':
                    self._add_decoded_bytes(1)
                else:
                    raise ValueError("JSON string escape is invalid.")
                continue
            if value == 0x5C:
                self._escaped = True
                continue
            if value == 0x22:
                if self._pending_high_surrogate is not None:
                    raise ValueError("JSON string surrogate is incomplete.")
                self._in_string = False
                continue
            if value < 0x20:
                raise ValueError("JSON string contains an unescaped control.")
            self._add_decoded_bytes(1)

    def _start_string(self) -> None:
        self._in_string = True
        self._escaped = False
        self._unicode_digits = 0
        self._unicode_value = 0
        self._pending_high_surrogate = None
        self._decoded_utf8_bytes = 0

    def _feed_unicode_digit(self, value: int) -> None:
        if 0x30 <= value <= 0x39:
            digit = value - 0x30
        elif 0x41 <= value <= 0x46:
            digit = value - 0x41 + 10
        elif 0x61 <= value <= 0x66:
            digit = value - 0x61 + 10
        else:
            raise ValueError("JSON unicode escape is invalid.")
        self._unicode_value = self._unicode_value * 16 + digit
        self._unicode_digits -= 1
        if self._unicode_digits == 0:
            self._add_code_unit(self._unicode_value)

    def _add_code_unit(self, value: int) -> None:
        if 0xD800 <= value <= 0xDBFF:
            if self._pending_high_surrogate is not None:
                raise ValueError("JSON surrogate pair is invalid.")
            self._pending_high_surrogate = value
            return
        if 0xDC00 <= value <= 0xDFFF:
            if self._pending_high_surrogate is None:
                raise ValueError("JSON surrogate pair is invalid.")
            self._pending_high_surrogate = None
            self._add_decoded_bytes(4)
            return
        if self._pending_high_surrogate is not None:
            raise ValueError("JSON surrogate pair is invalid.")
        if value < 0x80:
            self._add_decoded_bytes(1)
        elif value < 0x800:
            self._add_decoded_bytes(2)
        else:
            self._add_decoded_bytes(3)

    def _add_decoded_bytes(self, count: int) -> None:
        if self._pending_high_surrogate is not None:
            raise ValueError("JSON surrogate pair is invalid.")
        self._decoded_utf8_bytes += count
        if self._decoded_utf8_bytes > self._max_utf8_bytes:
            raise request_body_too_large()


def max_revision_request_body_bytes(max_text_bytes: int) -> int:
    return (
        MAX_JSON_STRING_ESCAPE_FACTOR * max_text_bytes
        + MAX_JSON_BODY_OVERHEAD_BYTES
    )


def max_recheck_request_body_bytes(max_text_bytes: int) -> int:
    return 3 * max_text_bytes + MAX_FORM_BODY_OVERHEAD_BYTES


async def read_bounded_json_model[ModelT: BaseModel](
    request: Request,
    model: type[ModelT],
    *,
    max_bytes: int,
    max_materialized_bytes: int | None = None,
    max_string_utf8_bytes: int | None = None,
    preflight: Callable[[object], None] | None = None,
) -> ModelT:
    allowed_fields = set(model.model_fields)
    root_started = False
    root_complete = False
    current_key: str | None = None
    builders: dict[str, JsonValueBuilder] = {}
    materialized_bytes = 0
    try:
        async for prefix, event, value in iter_bounded_json_events(
            request,
            max_bytes=max_bytes,
            max_string_utf8_bytes=(
                max_bytes
                if max_string_utf8_bytes is None
                else max_string_utf8_bytes
            ),
        ):
            if prefix == "":
                if event == "start_map" and not root_started:
                    root_started = True
                    continue
                if event == "end_map" and root_started:
                    root_complete = True
                    continue
                if event == "map_key":
                    if (
                        not isinstance(value, str)
                        or value not in allowed_fields
                        or value in builders
                    ):
                        raise ValueError("JSON request field is invalid.")
                    current_key = value
                    continue
                raise ValueError("JSON request must contain one object.")
            top_level = prefix.split(".", 1)[0]
            if top_level not in allowed_fields:
                raise ValueError("JSON request field is invalid.")
            builder = builders.setdefault(
                top_level,
                JsonValueBuilder(),
            )
            materialized_bytes += _json_event_size(event, value)
            if materialized_bytes > (
                max_bytes
                if max_materialized_bytes is None
                else max_materialized_bytes
            ):
                raise request_body_too_large()
            builder.feed(event, value)
            if builder.complete and current_key == top_level:
                current_key = None
        if (
            not root_started
            or not root_complete
            or current_key is not None
            or any(not builder.complete for builder in builders.values())
        ):
            raise ValueError("JSON request is incomplete.")
        value = {
            key: builder.value
            for key, builder in builders.items()
        }
    except (ijson.JSONError, UnicodeDecodeError, ValueError) as error:
        raise invalid_request_body() from error
    if preflight is not None:
        preflight(value)
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise invalid_request_body() from error


async def iter_bounded_json_events(
    request: Request,
    *,
    max_bytes: int,
    max_string_utf8_bytes: int,
) -> AsyncGenerator[tuple[str, str, object], None]:
    events = ijson.sendable_list()
    parser = ijson.parse_coro(events)
    scanner = _JsonStringLimitScanner(max_string_utf8_bytes)
    nesting_depth = 0
    try:
        async for chunk in _bounded_stream(request, max_bytes=max_bytes):
            for start in range(0, len(chunk), MAX_JSON_PARSE_CHUNK_BYTES):
                part = chunk[start : start + MAX_JSON_PARSE_CHUNK_BYTES]
                scanner.feed(part)
                parser.send(part)
                batch = tuple(events)
                events.clear()
                for parsed_event in batch:
                    if parsed_event[1] in {"start_array", "start_map"}:
                        nesting_depth += 1
                        if nesting_depth > MAX_JSON_NESTING_DEPTH:
                            raise ValueError(
                                "JSON nesting exceeds the configured limit."
                            )
                    yield parsed_event
                    if parsed_event[1] in {"end_array", "end_map"}:
                        nesting_depth -= 1
        parser.close()
        for event in tuple(events):
            if event[1] in {"start_array", "start_map"}:
                nesting_depth += 1
                if nesting_depth > MAX_JSON_NESTING_DEPTH:
                    raise ValueError(
                        "JSON nesting exceeds the configured limit."
                    )
            yield event
            if event[1] in {"end_array", "end_map"}:
                nesting_depth -= 1
    except (ijson.JSONError, UnicodeDecodeError, ValueError) as error:
        raise invalid_request_body() from error


def _json_event_size(event: str, value: object) -> int:
    if isinstance(value, str):
        size = len(value.encode("utf-8"))
    elif isinstance(value, bool | int | float | Decimal):
        size = len(str(value))
    elif value is None:
        size = 4
    else:
        size = 0
    if event in {
        "end_array",
        "end_map",
        "map_key",
        "start_array",
        "start_map",
    }:
        size += 1
    return size


async def read_bounded_form_model[ModelT: BaseModel](
    request: Request,
    model: type[ModelT],
    *,
    max_body_bytes: int,
    max_part_bytes: int,
) -> ModelT:
    content_type = request.headers.get("content-type", "").lower()
    stream = _bounded_stream(request, max_bytes=max_body_bytes)
    try:
        if content_type.startswith("multipart/form-data"):
            form = await MultiPartParser(
                request.headers,
                stream,
                max_files=0,
                max_fields=MAX_FORM_FIELDS,
                max_part_size=max_part_bytes,
            ).parse()
        elif content_type.startswith("application/x-www-form-urlencoded"):
            form = await FormParser(
                request.headers,
                stream,
                max_fields=MAX_FORM_FIELDS,
                max_part_size=max_part_bytes,
            ).parse()
        else:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Request body must use form encoding.",
            )
    except MultiPartException as error:
        if "maximum size" in str(error).lower():
            raise request_body_too_large() from error
        raise invalid_request_body() from error
    values = _unique_text_fields(form)
    try:
        return model.model_validate(values)
    except ValidationError as error:
        raise invalid_request_body() from error


async def read_bounded_body(
    request: Request,
    *,
    max_bytes: int,
) -> bytes:
    body = bytearray()
    async for chunk in _bounded_stream(request, max_bytes=max_bytes):
        body.extend(chunk)
    return bytes(body)


async def _bounded_stream(
    request: Request,
    *,
    max_bytes: int,
) -> AsyncGenerator[bytes, None]:
    _validate_content_length(request, max_bytes=max_bytes)
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise request_body_too_large()
        if chunk:
            yield chunk


def _validate_content_length(request: Request, *, max_bytes: int) -> None:
    raw_content_length = request.headers.get("content-length")
    if raw_content_length is None:
        return
    try:
        content_length = int(raw_content_length)
    except ValueError as error:
        raise invalid_request_body() from error
    if content_length < 0:
        raise invalid_request_body()
    if content_length > max_bytes:
        raise request_body_too_large()


def _unique_text_fields(form: FormData) -> Mapping[str, str]:
    values: dict[str, str] = {}
    for key, value in form.multi_items():
        if key in values or isinstance(value, UploadFile):
            raise invalid_request_body()
        values[key] = value
    return values


def invalid_request_body() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": "invalid_request_body",
            "stage": "validation",
            "message": "The request body is invalid.",
            "retryable": False,
        },
    )


def request_body_too_large() -> HTTPException:
    return HTTPException(
        status.HTTP_413_CONTENT_TOO_LARGE,
        detail={
            "code": "request_body_too_large",
            "stage": "validation",
            "message": "The request body exceeds the configured maximum size.",
            "retryable": False,
        },
    )
