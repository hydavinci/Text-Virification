from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable

import pytest
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from text_verification.api import body_readers
from text_verification.api.body_readers import read_bounded_json_model


class _ReaderPayload(BaseModel):
    values: list[object] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
    note: str = ""


def _request(chunks: Iterable[bytes]) -> Request:
    bodies = list(chunks)
    messages = iter(
        [
            {
                "type": "http.request",
                "body": body,
                "more_body": index < len(bodies) - 1,
            }
            for index, body in enumerate(bodies)
        ]
    )

    async def receive() -> dict[str, object]:
        return next(
            messages,
            {"type": "http.request", "body": b"", "more_body": False},
        )

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )


def _read(
    payload: object,
    *,
    max_materialized_bytes: int,
    chunk_size: int | None = None,
) -> _ReaderPayload:
    body = json.dumps(payload, separators=(",", ":")).encode()
    chunks = (
        [body]
        if chunk_size is None
        else [
            body[start : start + chunk_size]
            for start in range(0, len(body), chunk_size)
        ]
    )
    return asyncio.run(
        read_bounded_json_model(
            _request(chunks),
            _ReaderPayload,
            max_bytes=len(body),
            max_materialized_bytes=max_materialized_bytes,
        )
    )


def test_materialized_budget_rejects_ten_thousand_empty_array_entries() -> None:
    with pytest.raises(HTTPException) as raised:
        _read({"values": [""] * 10_000}, max_materialized_bytes=16)

    assert raised.value.status_code == 413


def test_reader_enforces_container_entry_count_before_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        body_readers,
        "MAX_JSON_CONTAINER_ENTRIES",
        2,
        raising=False,
    )

    with pytest.raises(HTTPException) as raised:
        _read({"values": ["", "", ""]}, max_materialized_bytes=512)

    assert raised.value.status_code == 413


def test_reader_enforces_stream_event_count_before_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        body_readers,
        "MAX_JSON_EVENTS",
        5,
        raising=False,
    )

    with pytest.raises(HTTPException) as raised:
        _read({"values": [""]}, max_materialized_bytes=512)

    assert raised.value.status_code == 413


@pytest.mark.parametrize(
    "payload",
    [
        {"metadata": {chr(0x100 + index): "" for index in range(24)}},
        {"values": [[[[[[]]]]]]},
    ],
)
def test_materialized_budget_accounts_for_wide_maps_and_nested_containers(
    payload: object,
) -> None:
    with pytest.raises(HTTPException) as raised:
        _read(payload, max_materialized_bytes=100)

    assert raised.value.status_code == 413


def test_chunked_reader_accepts_ordinary_empty_optional_values() -> None:
    parsed = _read(
        {
            "values": [""],
            "metadata": {"empty": ""},
            "note": "",
        },
        max_materialized_bytes=512,
        chunk_size=3,
    )

    assert parsed == _ReaderPayload(
        values=[""],
        metadata={"empty": ""},
        note="",
    )
