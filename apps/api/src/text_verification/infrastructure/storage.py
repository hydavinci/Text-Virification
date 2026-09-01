from __future__ import annotations

import errno
import hashlib
import logging
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from text_verification.domain.capabilities import CapabilityProfile
from text_verification.domain.documents import FileType
from text_verification.infrastructure import document_storage

logger = logging.getLogger(__name__)

JOB_TEXT_FILE_ENCODINGS = ("utf-8", "utf-16", "gbk")

DocumentStorage = document_storage.DocumentStorage
InvalidUpload = document_storage.InvalidUpload
StoredUpload = document_storage.StoredDocument
UnsupportedFileType = document_storage.UnsupportedFileType
UploadCleanupFailed = document_storage.UploadCleanupFailed
UploadTooLarge = document_storage.UploadTooLarge
build_artifact_storage_key = document_storage.build_artifact_storage_key
validate_artifact_storage_key = document_storage.validate_artifact_storage_key
validate_artifact_identity = document_storage.validate_artifact_identity

@dataclass(frozen=True)
class PublishedArtifact:
    job_id: UUID
    artifact_id: UUID
    storage_key: str
    path: Path
    file_type: FileType
    size_bytes: int
    content_sha256: str
    created: bool


@dataclass(frozen=True)
class VerifiedArtifact:
    job_id: UUID
    artifact_id: UUID
    storage_key: str
    path: Path
    file_type: FileType
    size_bytes: int
    content_sha256: str
    created: bool


class JobStorage(DocumentStorage):
    def __init__(self, root: Path, max_upload_bytes: int) -> None:
        super().__init__(
            root,
            max_upload_bytes,
            profile=CapabilityProfile.ASYNCHRONOUS_JOB,
            text_file_encodings=JOB_TEXT_FILE_ENCODINGS,
            original_name_normalizer=document_storage.preserve_original_name,
            cleanup_logger_name=logger.name,
            cleanup_failure_log_message="cleanup_orphaned_job_delete_failed",
            cleanup_failure_id_field="job_id",
            allow_existing_directory=True,
            strict_cleanup_failures=True,
        )

    def document_directory(self, document_id: UUID) -> Path:
        return self.job_directory(document_id)

    def job_directory(self, job_id: UUID) -> Path:
        return self._root / str(job_id)

    def delete(self, document_id: UUID) -> None:
        self.delete_job(document_id)

    def delete_job(self, job_id: UUID) -> None:
        self._delete_job_directory(self.job_directory(job_id))

    def publish_artifact(
        self,
        job_id: UUID,
        artifact_id: UUID,
        storage_key: str,
        file_type: FileType | str,
        data: bytes,
    ) -> PublishedArtifact:
        resolved_file_type = file_type if isinstance(file_type, FileType) else FileType(file_type)
        relative_path = validate_artifact_identity(
            job_id,
            artifact_id,
            resolved_file_type,
            storage_key,
        )
        if len(data) > self._max_upload_bytes:
            raise UploadTooLarge(
                f"Artifact exceeds the {self._max_upload_bytes} byte upload limit."
            )
        expected_size = len(data)
        expected_digest = hashlib.sha256(data).hexdigest()
        if self._supports_descriptor_artifact_operations():
            created = self._publish_artifact_descriptor_relative(
                relative_path,
                data,
                expected_size=expected_size,
                expected_digest=expected_digest,
            )
        else:
            created = self._publish_artifact_fallback(
                relative_path,
                data,
                expected_size=expected_size,
                expected_digest=expected_digest,
            )
        return PublishedArtifact(
            job_id=job_id,
            artifact_id=artifact_id,
            storage_key=storage_key,
            path=self._root.joinpath(*relative_path.parts),
            file_type=resolved_file_type,
            size_bytes=expected_size,
            content_sha256=expected_digest,
            created=created,
        )

    def verify_artifact(self, artifact: PublishedArtifact) -> VerifiedArtifact:
        relative_path = validate_artifact_identity(
            artifact.job_id,
            artifact.artifact_id,
            artifact.file_type,
            artifact.storage_key,
        )
        if self._supports_descriptor_artifact_operations():
            with self._open_artifact_parent(relative_path, create=False) as (
                parent_fd,
                leaf_name,
            ):
                size_bytes, content_sha256 = self._fingerprint_at(
                    parent_fd,
                    leaf_name,
                )
        else:
            artifact_path = self._safe_artifact_path(relative_path, create_parent=False)
            size_bytes, content_sha256 = self._fingerprint_path(artifact_path)
        if (
            size_bytes != artifact.size_bytes
            or content_sha256 != artifact.content_sha256
        ):
            raise InvalidUpload("Artifact fingerprint changed after publication.")
        return VerifiedArtifact(
            job_id=artifact.job_id,
            artifact_id=artifact.artifact_id,
            storage_key=artifact.storage_key,
            path=self._root.joinpath(*relative_path.parts),
            file_type=artifact.file_type,
            size_bytes=size_bytes,
            content_sha256=content_sha256,
            created=artifact.created,
        )

    def delete_artifact(self, job_id: UUID, storage_key: str) -> bool:
        validate_artifact_storage_key(job_id, storage_key)
        return self.delete_storage_key(storage_key)

    def compensate_published_artifact(self, artifact: PublishedArtifact) -> bool:
        if not artifact.created:
            return False
        relative_path = validate_artifact_identity(
            artifact.job_id,
            artifact.artifact_id,
            artifact.file_type,
            artifact.storage_key,
        )
        try:
            if self._supports_descriptor_artifact_operations():
                with self._open_artifact_parent(relative_path, create=False) as (
                    parent_fd,
                    leaf_name,
                ):
                    descriptor = os.open(
                        leaf_name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=parent_fd,
                    )
                    try:
                        current_size, current_digest = self._fingerprint_descriptor(
                            descriptor
                        )
                        opened = os.fstat(descriptor)
                        named = os.stat(
                            leaf_name,
                            dir_fd=parent_fd,
                            follow_symlinks=False,
                        )
                        if (opened.st_dev, opened.st_ino) != (
                            named.st_dev,
                            named.st_ino,
                        ):
                            return False
                        if (
                            current_size != artifact.size_bytes
                            or current_digest != artifact.content_sha256
                        ):
                            return False
                        os.unlink(leaf_name, dir_fd=parent_fd)
                    finally:
                        os.close(descriptor)
            else:
                artifact_path = self._safe_artifact_path(
                    relative_path,
                    create_parent=False,
                )
                descriptor = os.open(
                    artifact_path,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                )
                try:
                    current_size, current_digest = self._fingerprint_descriptor(
                        descriptor
                    )
                    opened = os.fstat(descriptor)
                    named = artifact_path.lstat()
                    if (opened.st_dev, opened.st_ino) != (
                        named.st_dev,
                        named.st_ino,
                    ):
                        return False
                    if (
                        current_size != artifact.size_bytes
                        or current_digest != artifact.content_sha256
                    ):
                        return False
                    artifact_path.unlink()
                finally:
                    os.close(descriptor)
        except (FileNotFoundError, InvalidUpload, OSError):
            return False
        self._prune_empty_storage_directories(
            self._root.joinpath(*relative_path.parts).parent
        )
        return True

    def delete_orphaned_artifacts(
        self,
        referenced_storage_keys: set[str],
        older_than: datetime,
    ) -> list[str]:
        artifact_root = self._root / document_storage.ARTIFACT_NAMESPACE
        if not artifact_root.exists() and not artifact_root.is_symlink():
            return []
        if self._is_reparse_point(artifact_root) or not artifact_root.is_dir():
            self._log_orphaned_artifact_failure(
                document_storage.ARTIFACT_NAMESPACE,
                InvalidUpload("Artifact root is an unsafe directory."),
            )
            return []

        deleted: list[str] = []
        with os.scandir(artifact_root) as job_entries:
            for job_entry in job_entries:
                job_path = Path(job_entry.path)
                if job_entry.is_symlink() or self._is_reparse_point(job_path):
                    self._log_orphaned_artifact_failure(
                        job_path.relative_to(self._root).as_posix(),
                        InvalidUpload("Artifact job directory is a reparse point."),
                    )
                    continue
                if not job_entry.is_dir(follow_symlinks=False):
                    continue
                try:
                    job_id = UUID(job_entry.name)
                except ValueError:
                    continue
                if str(job_id) != job_entry.name:
                    continue
                job_mtime = datetime.fromtimestamp(
                    job_entry.stat(follow_symlinks=False).st_mtime,
                    UTC,
                )
                self._sweep_artifact_directory(
                    job_id,
                    job_path,
                    referenced_storage_keys,
                    older_than,
                    deleted,
                )
                if job_mtime < older_than:
                    try:
                        job_path.rmdir()
                    except OSError:
                        pass
        return deleted

    def _sweep_artifact_directory(
        self,
        job_id: UUID,
        directory: Path,
        referenced_storage_keys: set[str],
        older_than: datetime,
        deleted: list[str],
    ) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                storage_key = path.relative_to(self._root).as_posix()
                try:
                    stat_result = entry.stat(follow_symlinks=False)
                    if entry.is_symlink() or self._is_reparse_point(path):
                        raise InvalidUpload(
                            "Artifact orphan candidate is a reparse point."
                        )
                    if entry.is_dir(follow_symlinks=False):
                        directory_mtime = datetime.fromtimestamp(
                            stat_result.st_mtime,
                            UTC,
                        )
                        self._sweep_artifact_directory(
                            job_id,
                            path,
                            referenced_storage_keys,
                            older_than,
                            deleted,
                        )
                        if directory_mtime < older_than:
                            try:
                                path.rmdir()
                            except OSError:
                                pass
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        raise InvalidUpload(
                            "Artifact orphan candidate is not a regular file."
                        )
                    if storage_key in referenced_storage_keys:
                        continue
                    if datetime.fromtimestamp(stat_result.st_mtime, UTC) >= older_than:
                        continue
                    if self._delete_stale_artifact(job_id, storage_key, older_than):
                        deleted.append(storage_key)
                except Exception as error:
                    self._log_orphaned_artifact_failure(storage_key, error)

    def _delete_stale_artifact(
        self,
        job_id: UUID,
        storage_key: str,
        older_than: datetime,
    ) -> bool:
        relative_path = validate_artifact_storage_key(job_id, storage_key)
        if self._supports_descriptor_artifact_operations():
            with self._open_artifact_parent(relative_path, create=False) as (
                parent_fd,
                leaf_name,
            ):
                stat_result = os.stat(
                    leaf_name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                if not stat.S_ISREG(stat_result.st_mode):
                    raise InvalidUpload(
                        "Artifact orphan candidate is not a regular file."
                    )
                if datetime.fromtimestamp(stat_result.st_mtime, UTC) >= older_than:
                    return False
                os.unlink(leaf_name, dir_fd=parent_fd)
        else:
            artifact_path = self._safe_artifact_path(
                relative_path,
                create_parent=False,
            )
            stat_result = artifact_path.lstat()
            if datetime.fromtimestamp(stat_result.st_mtime, UTC) >= older_than:
                return False
            artifact_path.unlink()
        return True

    def _log_orphaned_artifact_failure(
        self,
        storage_key: str,
        error: Exception,
    ) -> None:
        logger.warning(
            "cleanup_orphaned_artifact_delete_failed",
            extra={
                "storage_key": storage_key,
                "error_type": type(error).__name__,
            },
        )

    def _publish_artifact_descriptor_relative(
        self,
        relative_path: PurePosixPath,
        data: bytes,
        *,
        expected_size: int,
        expected_digest: str,
    ) -> bool:
        path_parts = relative_path.parts
        temp_name = f".{path_parts[-1]}.{uuid4().hex}.uploading"
        with self._open_artifact_parent(relative_path, create=True) as (
            parent_fd,
            leaf_name,
        ):
            temp_fd = -1
            try:
                temp_fd = os.open(
                    temp_name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=parent_fd,
                )
                self._write_fd(temp_fd, data)
                os.fsync(temp_fd)
                os.close(temp_fd)
                temp_fd = -1
                try:
                    os.link(
                        temp_name,
                        leaf_name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    size_bytes, content_sha256 = self._fingerprint_at(
                        parent_fd,
                        leaf_name,
                    )
                    if (
                        size_bytes != expected_size
                        or content_sha256 != expected_digest
                    ):
                        raise InvalidUpload(
                            "Artifact key already exists with different content."
                        ) from None
                    return False
                size_bytes, content_sha256 = self._fingerprint_at(
                    parent_fd,
                    leaf_name,
                )
                if size_bytes != expected_size or content_sha256 != expected_digest:
                    raise InvalidUpload(
                        "Published artifact fingerprint does not match its content."
                    )
                return True
            finally:
                if temp_fd >= 0:
                    os.close(temp_fd)
                try:
                    os.unlink(temp_name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass

    def _publish_artifact_fallback(
        self,
        relative_path: PurePosixPath,
        data: bytes,
        *,
        expected_size: int,
        expected_digest: str,
    ) -> bool:
        artifact_path = self._safe_artifact_path(relative_path, create_parent=True)
        temp_path = artifact_path.with_name(
            f".{artifact_path.name}.{uuid4().hex}.uploading"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        temp_fd = os.open(temp_path, flags, 0o600)
        try:
            self._write_fd(temp_fd, data)
            os.fsync(temp_fd)
        finally:
            os.close(temp_fd)
        try:
            try:
                os.link(temp_path, artifact_path, follow_symlinks=False)
            except TypeError:
                os.link(temp_path, artifact_path)
        except FileExistsError:
            size_bytes, content_sha256 = self._fingerprint_path(artifact_path)
            if size_bytes != expected_size or content_sha256 != expected_digest:
                raise InvalidUpload(
                    "Artifact key already exists with different content."
                ) from None
            return False
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
        size_bytes, content_sha256 = self._fingerprint_path(artifact_path)
        if size_bytes != expected_size or content_sha256 != expected_digest:
            raise InvalidUpload(
                "Published artifact fingerprint does not match its content."
            )
        return True

    @contextmanager
    def _open_artifact_parent(
        self,
        relative_path: PurePosixPath,
        *,
        create: bool,
    ) -> Iterator[tuple[int, str]]:
        path_parts = relative_path.parts
        if create:
            self._root.mkdir(parents=True, exist_ok=True)
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptors: list[int] = []
        try:
            current_fd = os.open(self._root, directory_flags)
            descriptors.append(current_fd)
            for part in path_parts[:-1]:
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
                descriptors.append(next_fd)
                current_fd = next_fd
            yield current_fd, path_parts[-1]
        except OSError as error:
            if error.errno in {
                errno.ELOOP,
                errno.ENOTDIR,
                errno.ENOENT,
            }:
                raise InvalidUpload(
                    "Artifact storage path crosses an unsafe directory component "
                    "or reparse point."
                ) from error
            raise
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    def _safe_artifact_path(
        self,
        relative_path: PurePosixPath,
        *,
        create_parent: bool,
    ) -> Path:
        path_parts = relative_path.parts
        if create_parent:
            self._root.mkdir(parents=True, exist_ok=True)
        current = self._root
        self._assert_safe_directory_component(current)
        for part in path_parts[:-1]:
            current /= part
            if create_parent:
                try:
                    current.mkdir()
                except FileExistsError:
                    pass
            self._assert_safe_directory_component(current)
        artifact_path = current / path_parts[-1]
        if artifact_path.exists() or artifact_path.is_symlink():
            self._assert_safe_regular_file(artifact_path)
        return artifact_path

    def _assert_safe_directory_component(self, path: Path) -> None:
        try:
            stat_result = path.lstat()
        except FileNotFoundError as error:
            raise InvalidUpload("Artifact storage directory is missing.") from error
        if self._is_reparse_point(path) or not stat.S_ISDIR(stat_result.st_mode):
            raise InvalidUpload(
                "Artifact storage path crosses an unsafe directory component "
                "or reparse point."
            )
        if not self._is_within_root(path):
            raise InvalidUpload("Artifact storage path escapes the storage root.")

    def _assert_safe_regular_file(self, path: Path) -> None:
        stat_result = path.lstat()
        if self._is_reparse_point(path) or not stat.S_ISREG(stat_result.st_mode):
            raise InvalidUpload("Artifact storage key is not a safe regular file.")
        if not self._is_within_root(path):
            raise InvalidUpload("Artifact storage path escapes the storage root.")

    def _fingerprint_at(self, parent_fd: int, leaf_name: str) -> tuple[int, str]:
        try:
            descriptor = os.open(
                leaf_name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.EISDIR, errno.ENOENT}:
                raise InvalidUpload(
                    "Artifact storage key is not a safe regular file."
                ) from error
            raise
        try:
            return self._fingerprint_descriptor(descriptor)
        finally:
            os.close(descriptor)

    def _fingerprint_path(self, path: Path) -> tuple[int, str]:
        self._assert_safe_regular_file(path)
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            before = os.fstat(descriptor)
            current = path.lstat()
            if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                raise InvalidUpload("Artifact changed during verification.")
            return self._fingerprint_descriptor(descriptor)
        finally:
            os.close(descriptor)

    def _fingerprint_descriptor(self, descriptor: int) -> tuple[int, str]:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise InvalidUpload("Artifact storage key is not a regular file.")
        digest = hashlib.sha256()
        os.lseek(descriptor, 0, os.SEEK_SET)
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise InvalidUpload("Artifact changed during fingerprint verification.")
        return after.st_size, digest.hexdigest()

    def _write_fd(self, descriptor: int, data: bytes) -> None:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]

    def _supports_descriptor_artifact_operations(self) -> bool:
        required = (os.open, os.mkdir, os.unlink, os.link)
        return (
            hasattr(os, "O_DIRECTORY")
            and hasattr(os, "O_NOFOLLOW")
            and all(operation in os.supports_dir_fd for operation in required)
            and os.link in os.supports_follow_symlinks
        )

    def _delete_directory(self, document_directory: Path) -> None:
        self._delete_job_directory(document_directory)

    def _delete_job_directory(self, job_directory: Path) -> None:
        super()._delete_directory(job_directory)
