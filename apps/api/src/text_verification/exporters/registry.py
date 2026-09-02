from __future__ import annotations

from collections.abc import Iterable

from text_verification.domain.documents import ExportFormat, FileType
from text_verification.domain.ports import Exporter
from text_verification.registry_errors import DuplicateCapabilityError, MissingCapabilityError


class ExporterRegistry:
    def __init__(self, exporters: Iterable[Exporter[...]] = ()) -> None:
        self._exporters: dict[FileType | ExportFormat, Exporter[...]] = {}
        for exporter in exporters:
            self.register(exporter)

    def register(self, exporter: Exporter[...]) -> None:
        file_type = exporter.file_type
        if file_type in self._exporters:
            raise DuplicateCapabilityError("exporter", file_type.value)
        self._exporters[file_type] = exporter

    def get(self, file_type: FileType | ExportFormat) -> Exporter[...]:
        try:
            return self._exporters[file_type]
        except KeyError as error:
            raise MissingCapabilityError("exporter", file_type.value) from error
