from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from fastapi import Request
from pydantic import ValidationError

from text_verification.api.body_readers import (
    JSON_MATERIALIZED_EVENT_OVERHEAD_BYTES,
    MAX_JSON_CONTAINER_ENTRIES,
    MAX_JSON_EVENTS,
    invalid_request_body,
    iter_bounded_json_events,
    request_body_too_large,
)
from text_verification.compatibility.models import ReportRequest
from text_verification.domain.documents import (
    DocumentPayloadLimitError,
    DocumentPayloadShapeError,
)
from text_verification.domain.text_edits import (
    MAX_REVISION_TEXT_CODEPOINTS,
    TextDiffLimitError,
    validate_revision_text,
)

type JsonContainer = dict[str, object] | list[object]
_SELECTED_REPORT_FIELDS = frozenset(
    {
        "filename",
        "issues",
        "stats",
        "summary",
    }
)
_REPORT_FIELDS = _SELECTED_REPORT_FIELDS | {"blocks", "text"}
_SCALAR_EVENTS = frozenset(
    {
        "boolean",
        "double",
        "integer",
        "null",
        "number",
        "string",
    }
)


@dataclass
class _ContainerFrame:
    value: JsonContainer
    pending_key: str | None = None


class _JsonValueBuilder:
    def __init__(self) -> None:
        self._frames: list[_ContainerFrame] = []
        self.value: object | None = None
        self.complete = False

    def feed(self, event: str, value: object) -> None:
        if self.complete:
            raise DocumentPayloadShapeError(
                "Report fields must not be duplicated."
            )
        if event == "map_key":
            if (
                not self._frames
                or not isinstance(self._frames[-1].value, dict)
                or not isinstance(value, str)
                or self._frames[-1].pending_key is not None
            ):
                raise DocumentPayloadShapeError(
                    "Report JSON object structure is invalid."
                )
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
                raise DocumentPayloadShapeError(
                    "Report JSON container structure is invalid."
                )
            frame = self._frames.pop()
            expected_type = dict if event == "end_map" else list
            if not isinstance(frame.value, expected_type):
                raise DocumentPayloadShapeError(
                    "Report JSON container structure is invalid."
                )
            if isinstance(frame.value, dict) and frame.pending_key is not None:
                raise DocumentPayloadShapeError(
                    "Report JSON object value is missing."
                )
            if not self._frames:
                self.complete = True
            return
        if event not in _SCALAR_EVENTS:
            raise DocumentPayloadShapeError(
                "Report JSON value is invalid."
            )
        self._add(value)
        if not self._frames:
            self.complete = True

    def _add(self, value: object) -> None:
        if not self._frames:
            if self.value is not None:
                raise DocumentPayloadShapeError(
                    "Report JSON value is duplicated."
                )
            self.value = value
            return
        frame = self._frames[-1]
        if isinstance(frame.value, list):
            frame.value.append(value)
            return
        if frame.pending_key is None:
            raise DocumentPayloadShapeError(
                "Report JSON object key is missing."
            )
        if frame.pending_key in frame.value:
            raise DocumentPayloadShapeError(
                "Report JSON object key is duplicated."
            )
        frame.value[frame.pending_key] = value
        frame.pending_key = None


async def read_bounded_report_request(
    request: Request,
    *,
    max_body_bytes: int,
    max_retained_bytes: int,
    max_document_utf8_bytes: int,
    max_blocks: int,
    max_total_codepoints: int,
    max_total_utf8_bytes: int,
) -> ReportRequest:
    root_started = False
    root_complete = False
    top_level_keys: set[str] = set()
    selected_builders: dict[str, _JsonValueBuilder] = {}
    retained_bytes = 0
    event_count = 0
    container_entry_count = 0
    container_keys: list[set[str] | None] = []
    current_root_key: str | None = None
    text_seen = False
    blocks_seen = False
    blocks_complete = False
    in_block = False
    block_count = 0
    block_text_seen = False
    block_id_seen = False
    total_codepoints = 0
    total_utf8_bytes = 0

    def charge_retained(event: str, value: object) -> None:
        nonlocal retained_bytes
        retained_bytes += JSON_MATERIALIZED_EVENT_OVERHEAD_BYTES
        if isinstance(value, str):
            retained_bytes += len(value.encode("utf-8"))
        elif isinstance(value, bool | int | float | Decimal):
            retained_bytes += len(str(value))
        elif value is None:
            retained_bytes += 4
        if retained_bytes > max_retained_bytes:
            raise request_body_too_large()

    def charge_document_text(value: str) -> None:
        nonlocal total_codepoints, total_utf8_bytes
        total_codepoints += len(value)
        total_utf8_bytes += len(value.encode("utf-8"))
        if (
            total_codepoints > max_total_codepoints
            or total_utf8_bytes > max_total_utf8_bytes
        ):
            raise DocumentPayloadLimitError(
                "Canonical report text exceeds the configured limit."
            )

    try:
        async for prefix, event, value in iter_bounded_json_events(
            request,
            max_bytes=max_body_bytes,
            max_string_utf8_bytes=max(
                max_document_utf8_bytes,
                max_retained_bytes,
            ),
        ):
            event_count += 1
            if event_count > MAX_JSON_EVENTS:
                raise request_body_too_large()
            if event in _SCALAR_EVENTS or event in {"start_array", "start_map"}:
                container_entry_count += 1
                if container_entry_count > MAX_JSON_CONTAINER_ENTRIES:
                    raise request_body_too_large()

            if event == "start_map":
                container_keys.append(set())
            elif event == "start_array":
                container_keys.append(None)
            elif event == "map_key":
                if (
                    not container_keys
                    or container_keys[-1] is None
                    or not isinstance(value, str)
                    or value in container_keys[-1]
                ):
                    raise DocumentPayloadShapeError(
                        "Report JSON object keys must be unique strings."
                    )
                charge_retained(event, value)
                container_keys[-1].add(value)
                if len(container_keys) == 1:
                    if value not in _REPORT_FIELDS:
                        raise DocumentPayloadShapeError(
                            "Report request contains an unknown field."
                        )
                    current_root_key = value
            elif event in {"end_map", "end_array"}:
                expected_map = event == "end_map"
                if (
                    not container_keys
                    or (container_keys[-1] is not None) != expected_map
                ):
                    raise DocumentPayloadShapeError(
                        "Report JSON container structure is invalid."
                    )
                container_keys.pop()

            if prefix == "":
                if event == "start_map":
                    if root_started:
                        raise DocumentPayloadShapeError(
                            "Report request must contain one JSON object."
                        )
                    root_started = True
                    continue
                if event == "end_map":
                    root_complete = True
                    current_root_key = None
                    continue
                if event == "map_key":
                    if not isinstance(value, str) or value in top_level_keys:
                        raise DocumentPayloadShapeError(
                            "Report fields must not be duplicated."
                        )
                    top_level_keys.add(value)
                    continue
                raise DocumentPayloadShapeError(
                    "Report request must contain one JSON object."
                )

            top_level = current_root_key
            if top_level is None:
                raise DocumentPayloadShapeError(
                    "Report JSON value is missing its root field."
                )
            if top_level in _SELECTED_REPORT_FIELDS:
                if event != "map_key":
                    charge_retained(event, value)
                builder = selected_builders.setdefault(
                    top_level,
                    _JsonValueBuilder(),
                )
                builder.feed(event, value)
                continue

            if prefix == "text":
                if text_seen or event != "string" or not isinstance(value, str):
                    raise DocumentPayloadShapeError(
                        "Canonical report text must be a string."
                    )
                validate_revision_text(
                    value,
                    max_codepoints=MAX_REVISION_TEXT_CODEPOINTS,
                    max_utf8_bytes=max_document_utf8_bytes,
                )
                charge_document_text(value)
                text_seen = True
                continue

            if prefix == "blocks":
                if event == "start_array" and not blocks_seen:
                    blocks_seen = True
                    continue
                if event == "end_array" and blocks_seen and not in_block:
                    blocks_complete = True
                    continue
                raise DocumentPayloadShapeError(
                    "Canonical report blocks must be an array."
                )

            if prefix == "blocks.item":
                if event == "start_map" and not in_block:
                    block_count += 1
                    if block_count > max_blocks:
                        raise DocumentPayloadLimitError(
                            "Canonical report block count exceeds the configured limit."
                        )
                    in_block = True
                    block_text_seen = False
                    block_id_seen = False
                    continue
                if event == "end_map" and in_block:
                    if not block_text_seen or not block_id_seen:
                        raise DocumentPayloadShapeError(
                            "Canonical report blocks require block_id and text."
                        )
                    in_block = False
                    continue
                if event == "map_key" and in_block:
                    continue
                raise DocumentPayloadShapeError(
                    "Canonical report blocks must contain objects."
                )

            if prefix == "blocks.item.text":
                if (
                    not in_block
                    or block_text_seen
                    or event != "string"
                    or not isinstance(value, str)
                ):
                    raise DocumentPayloadShapeError(
                        "Canonical report block text must be a string."
                    )
                charge_document_text(value)
                block_text_seen = True
                continue

            if prefix == "blocks.item.block_id":
                if (
                    not in_block
                    or block_id_seen
                    or event != "string"
                    or not isinstance(value, str)
                ):
                    raise DocumentPayloadShapeError(
                        "Canonical report block ID must be a string."
                    )
                block_id_seen = True

        if not root_started or not root_complete:
            raise DocumentPayloadShapeError(
                "Report request must contain one JSON object."
            )
        if blocks_seen and (
            not blocks_complete
            or in_block
            or not text_seen
        ):
            raise DocumentPayloadShapeError(
                "Canonical report text and blocks are incomplete."
            )
        values = {
            key: builder.value
            for key, builder in selected_builders.items()
            if builder.complete
        }
        if len(values) != len(selected_builders):
            raise DocumentPayloadShapeError(
                "Report request fields are incomplete."
            )
        return ReportRequest.model_validate(values)
    except DocumentPayloadLimitError as error:
        raise request_body_too_large() from error
    except (
        DocumentPayloadShapeError,
        TextDiffLimitError,
        UnicodeEncodeError,
        ValidationError,
    ) as error:
        raise invalid_request_body() from error
