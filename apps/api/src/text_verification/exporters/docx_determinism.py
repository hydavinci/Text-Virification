from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

DETERMINISTIC_DOCX_TIME = datetime(2000, 1, 1, tzinfo=UTC)
DETERMINISTIC_DOCX_ZIP_TIME = (2000, 1, 1, 0, 0, 0)
DETERMINISTIC_DOCX_REVISION_DATE = "2000-01-01T00:00:00Z"


class _BoundedBytesIO(io.BytesIO):
    def __init__(
        self,
        max_bytes: int | None,
        error_factory: Callable[[str], Exception],
    ) -> None:
        super().__init__()
        self._max_bytes = max_bytes
        self._error_factory = error_factory

    def write(self, data: Any) -> int:
        if self._max_bytes is not None:
            size = len(data)
            if max(len(self.getbuffer()), self.tell() + size) > self._max_bytes:
                raise self._error_factory(
                    "DOCX output exceeds the configured output size limit."
                )
        return super().write(data)


def save_deterministic_docx(
    document: Any,
    *,
    max_bytes: int | None = None,
    title: str | None = None,
    error_factory: Callable[[str], Exception] = ValueError,
) -> bytes:
    if title is not None:
        document.core_properties.title = title
    document.core_properties.created = DETERMINISTIC_DOCX_TIME
    document.core_properties.modified = DETERMINISTIC_DOCX_TIME
    stream = _BoundedBytesIO(max_bytes, error_factory)
    document.save(stream)
    return canonicalize_docx_archive(
        stream.getvalue(),
        max_bytes=max_bytes,
        error_factory=error_factory,
    )


def canonicalize_docx_archive(
    content: bytes,
    *,
    max_bytes: int | None = None,
    error_factory: Callable[[str], Exception] = ValueError,
) -> bytes:
    output = _BoundedBytesIO(max_bytes, error_factory)
    with zipfile.ZipFile(io.BytesIO(content)) as source:
        with zipfile.ZipFile(
            output,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as target:
            for source_info in sorted(
                source.infolist(),
                key=lambda info: info.filename,
            ):
                canonical_info = zipfile.ZipInfo(
                    source_info.filename,
                    DETERMINISTIC_DOCX_ZIP_TIME,
                )
                canonical_info.compress_type = zipfile.ZIP_DEFLATED
                canonical_info.create_system = 3
                canonical_info.external_attr = source_info.external_attr
                canonical_info.flag_bits = source_info.flag_bits & 0x800
                target.writestr(
                    canonical_info,
                    source.read(source_info),
                )
    return output.getvalue()
