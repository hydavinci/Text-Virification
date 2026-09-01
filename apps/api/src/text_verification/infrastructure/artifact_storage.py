from __future__ import annotations

import errno
import hashlib
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from text_verification.domain.documents import FileType
from text_verification.infrastructure.document_storage import (
    ARTIFACT_NAMESPACE,
    InvalidUpload,
    UploadTooLarge,
    validate_artifact_identity,
    validate_artifact_storage_key,
)


class ArtifactNotFoundError(InvalidUpload):
    pass


@dataclass(frozen=True)
class _DirectoryLink:
    parent_fd: int
    name: str
    child_fd: int


@dataclass(frozen=True)
class _FileSignature:
    device: int
    inode: int
    size_bytes: int
    modified_ns: int
    changed_ns: int


@dataclass(frozen=True)
class ArtifactOrphanCandidate:
    job_id: UUID
    artifact_id: UUID
    file_type: FileType
    storage_key: str
    path_storage_key: str


class ArtifactVerificationHandle:
    def __init__(
        self,
        *,
        root: Path,
        job_id: UUID,
        artifact_id: UUID,
        storage_key: str,
        path: Path,
        file_type: FileType,
        size_bytes: int,
        content_sha256: str,
        created: bool,
        directory_links: tuple[_DirectoryLink, ...],
        directory_fds: tuple[int, ...],
        parent_fd: int,
        leaf_name: str,
        file_fd: int,
        file_signature: _FileSignature,
    ) -> None:
        self.root = root
        self.job_id = job_id
        self.artifact_id = artifact_id
        self.storage_key = storage_key
        self.path = path
        self.file_type = file_type
        self.size_bytes = size_bytes
        self.content_sha256 = content_sha256
        self.created = created
        self._directory_links = directory_links
        self._directory_fds = directory_fds
        self._parent_fd = parent_fd
        self._leaf_name = leaf_name
        self._file_fd = file_fd
        self._file_signature = file_signature
        self._closed = False
        self._unlinked = False

    def __enter__(self) -> ArtifactVerificationHandle:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def assert_current(self) -> None:
        if self._closed:
            raise RuntimeError("Artifact verification handle is closed.")
        for link in self._directory_links:
            child = os.fstat(link.child_fd)
            try:
                named = os.stat(
                    link.name,
                    dir_fd=link.parent_fd,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise InvalidUpload(
                    "Artifact directory entry no longer names the verified directory."
                ) from error
            if (
                not stat.S_ISDIR(child.st_mode)
                or not stat.S_ISDIR(named.st_mode)
                or (child.st_dev, child.st_ino) != (named.st_dev, named.st_ino)
            ):
                raise InvalidUpload(
                    "Artifact directory entry no longer names the verified directory."
                )

        current = os.fstat(self._file_fd)
        try:
            named_file = os.stat(
                self._leaf_name,
                dir_fd=self._parent_fd,
                follow_symlinks=False,
            )
        except OSError as error:
            raise InvalidUpload(
                "Artifact directory entry no longer names the verified file."
            ) from error
        if (
            not stat.S_ISREG(current.st_mode)
            or not stat.S_ISREG(named_file.st_mode)
            or (current.st_dev, current.st_ino)
            != (named_file.st_dev, named_file.st_ino)
            or _file_signature(current) != self._file_signature
        ):
            raise InvalidUpload(
                "Artifact directory entry no longer names the verified file."
            )

    def unlink_created_if_current(self) -> bool:
        if not self.created or self._unlinked:
            return False
        self.assert_current()
        os.unlink(self._leaf_name, dir_fd=self._parent_fd)
        self._unlinked = True
        return True

    def close(self) -> None:
        if self._closed:
            return
        os.close(self._file_fd)
        for descriptor in reversed(self._directory_fds):
            os.close(descriptor)
        self._closed = True


class ArtifactStorage:
    def __init__(self, root: Path, max_artifact_bytes: int) -> None:
        self._root = root
        self._max_artifact_bytes = max_artifact_bytes

    def publish_verified(
        self,
        job_id: UUID,
        artifact_id: UUID,
        storage_key: str,
        file_type: FileType | str,
        data: bytes,
    ) -> ArtifactVerificationHandle:
        if not self._supports_descriptor_operations():
            raise InvalidUpload(
                "Safe artifact publication requires descriptor-relative "
                "no-follow filesystem operations."
            )
        resolved_file_type = file_type if isinstance(file_type, FileType) else FileType(file_type)
        relative_path = validate_artifact_identity(
            job_id,
            artifact_id,
            resolved_file_type,
            storage_key,
        )
        if len(data) > self._max_artifact_bytes:
            raise UploadTooLarge(
                f"Artifact exceeds the {self._max_artifact_bytes} byte upload limit."
            )
        expected_size = len(data)
        expected_digest = hashlib.sha256(data).hexdigest()
        directory_links, directory_fds, parent_fd = self._open_directory_chain(
            relative_path,
            create=True,
        )
        leaf_name = relative_path.name
        temp_name = f".{leaf_name}.{uuid4().hex}.uploading"
        temp_fd = -1
        file_fd = -1
        created = False
        created_inode: tuple[int, int] | None = None
        temp_unlinked = False
        try:
            temp_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            _write_all(temp_fd, data)
            os.fsync(temp_fd)
            temp_stat = os.fstat(temp_fd)
            created_inode = (temp_stat.st_dev, temp_stat.st_ino)
            try:
                os.link(
                    temp_name,
                    leaf_name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                created = True
            except FileExistsError:
                created = False

            os.unlink(temp_name, dir_fd=parent_fd)
            temp_unlinked = True
            file_fd = os.open(
                leaf_name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            size_bytes, content_sha256, file_signature = _hash_stable_file(file_fd)
            if created and (
                file_signature.device,
                file_signature.inode,
            ) != created_inode:
                raise InvalidUpload(
                    "Published artifact entry does not name the created inode."
                )
            if size_bytes != expected_size or content_sha256 != expected_digest:
                message = (
                    "Published artifact fingerprint does not match its content."
                    if created
                    else "Artifact key already exists with different content."
                )
                raise InvalidUpload(message)
            file_signature = _file_signature(os.fstat(file_fd))
            handle = self._build_handle(
                job_id=job_id,
                artifact_id=artifact_id,
                storage_key=storage_key,
                relative_path=relative_path,
                file_type=resolved_file_type,
                size_bytes=size_bytes,
                content_sha256=content_sha256,
                created=created,
                directory_links=directory_links,
                directory_fds=directory_fds,
                parent_fd=parent_fd,
                leaf_name=leaf_name,
                file_fd=file_fd,
                file_signature=file_signature,
            )
            file_fd = -1
            directory_fds = ()
            return handle
        except Exception:
            if created and created_inode is not None:
                _unlink_named_inode(parent_fd, leaf_name, created_inode)
            raise
        finally:
            if file_fd >= 0:
                os.close(file_fd)
            if temp_fd >= 0:
                os.close(temp_fd)
            if not temp_unlinked:
                try:
                    os.unlink(temp_name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
            for descriptor in reversed(directory_fds):
                os.close(descriptor)

    def open_verified(
        self,
        job_id: UUID,
        artifact_id: UUID,
        storage_key: str,
        file_type: FileType | str,
        *,
        expected_size: int,
        expected_digest: str,
    ) -> ArtifactVerificationHandle:
        if not self._supports_descriptor_operations():
            raise InvalidUpload(
                "Safe artifact verification requires descriptor-relative "
                "no-follow filesystem operations."
            )
        resolved_file_type = file_type if isinstance(file_type, FileType) else FileType(file_type)
        relative_path = validate_artifact_identity(
            job_id,
            artifact_id,
            resolved_file_type,
            storage_key,
        )
        directory_links, directory_fds, parent_fd = self._open_directory_chain(
            relative_path,
            create=False,
        )
        file_fd = -1
        try:
            try:
                file_fd = os.open(
                    relative_path.name,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError as error:
                raise ArtifactNotFoundError(
                    "Reserved artifact file is missing."
                ) from error
            size_bytes, content_sha256, file_signature = _hash_stable_file(file_fd)
            if size_bytes != expected_size or content_sha256 != expected_digest:
                raise InvalidUpload(
                    "Artifact fingerprint does not match the pending reservation."
                )
            handle = self._build_handle(
                job_id=job_id,
                artifact_id=artifact_id,
                storage_key=storage_key,
                relative_path=relative_path,
                file_type=resolved_file_type,
                size_bytes=size_bytes,
                content_sha256=content_sha256,
                created=False,
                directory_links=directory_links,
                directory_fds=directory_fds,
                parent_fd=parent_fd,
                leaf_name=relative_path.name,
                file_fd=file_fd,
                file_signature=file_signature,
            )
            file_fd = -1
            directory_fds = ()
            return handle
        finally:
            if file_fd >= 0:
                os.close(file_fd)
            for descriptor in reversed(directory_fds):
                os.close(descriptor)

    def delete_owned(self, job_id: UUID, storage_key: str) -> bool:
        relative_path = validate_artifact_storage_key(job_id, storage_key)
        return self._delete_regular_file(relative_path)

    def is_artifact_missing(
        self,
        job_id: UUID,
        artifact_id: UUID,
        storage_key: str,
        file_type: FileType | str,
    ) -> bool:
        resolved_file_type = file_type if isinstance(file_type, FileType) else FileType(file_type)
        relative_path = validate_artifact_identity(
            job_id,
            artifact_id,
            resolved_file_type,
            storage_key,
        )
        try:
            _, directory_fds, parent_fd = self._open_directory_chain(
                relative_path,
                create=False,
            )
        except ArtifactNotFoundError:
            return True
        try:
            try:
                stat_result = os.stat(
                    relative_path.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return True
            if not stat.S_ISREG(stat_result.st_mode):
                raise InvalidUpload("Artifact is not a regular file.")
            return False
        finally:
            for descriptor in reversed(directory_fds):
                os.close(descriptor)

    def delete_stale_candidate(
        self,
        candidate: ArtifactOrphanCandidate,
        older_than: datetime,
        *,
        prune_empty_directories: bool,
    ) -> bool:
        relative_path = _orphan_candidate_relative_path(candidate)
        deleted = self._delete_regular_file(relative_path, older_than=older_than)
        if deleted and prune_empty_directories:
            self._prune_empty_orphan_directories(relative_path)
        return deleted

    def _delete_regular_file(
        self,
        relative_path: PurePosixPath,
        *,
        older_than: datetime | None = None,
    ) -> bool:
        if not self._supports_descriptor_operations():
            raise InvalidUpload(
                "Safe artifact deletion requires descriptor-relative "
                "no-follow filesystem operations."
            )
        try:
            _, directory_fds, parent_fd = self._open_directory_chain(
                relative_path,
                create=False,
            )
        except ArtifactNotFoundError:
            return False
        try:
            try:
                stat_result = os.stat(
                    relative_path.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return False
            if not stat.S_ISREG(stat_result.st_mode):
                raise InvalidUpload("Artifact is not a regular file.")
            if (
                older_than is not None
                and datetime.fromtimestamp(stat_result.st_mtime, UTC) >= older_than
            ):
                return False
            os.unlink(relative_path.name, dir_fd=parent_fd)
            return True
        finally:
            for descriptor in reversed(directory_fds):
                os.close(descriptor)

    def _prune_empty_orphan_directories(
        self,
        relative_path: PurePosixPath,
    ) -> None:
        if os.rmdir not in os.supports_dir_fd:
            return
        try:
            directory_links, directory_fds, _ = self._open_directory_chain(
                relative_path,
                create=False,
            )
        except ArtifactNotFoundError:
            return
        try:
            artifact_links = directory_links[-len(relative_path.parts[:-1]) :]
            if not artifact_links or artifact_links[0].name != ARTIFACT_NAMESPACE:
                raise InvalidUpload("Artifact path has an unexpected namespace.")
            for link in reversed(artifact_links[1:]):
                child = os.fstat(link.child_fd)
                try:
                    named = os.stat(
                        link.name,
                        dir_fd=link.parent_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    continue
                if (
                    not stat.S_ISDIR(child.st_mode)
                    or not stat.S_ISDIR(named.st_mode)
                    or (child.st_dev, child.st_ino) != (named.st_dev, named.st_ino)
                ):
                    raise InvalidUpload(
                        "Artifact directory entry no longer names the verified directory."
                    )
                try:
                    os.rmdir(link.name, dir_fd=link.parent_fd)
                except OSError:
                    break
        finally:
            for descriptor in reversed(directory_fds):
                os.close(descriptor)

    def _build_handle(
        self,
        *,
        job_id: UUID,
        artifact_id: UUID,
        storage_key: str,
        relative_path: PurePosixPath,
        file_type: FileType,
        size_bytes: int,
        content_sha256: str,
        created: bool,
        directory_links: tuple[_DirectoryLink, ...],
        directory_fds: tuple[int, ...],
        parent_fd: int,
        leaf_name: str,
        file_fd: int,
        file_signature: _FileSignature,
    ) -> ArtifactVerificationHandle:
        return ArtifactVerificationHandle(
            root=self._root,
            job_id=job_id,
            artifact_id=artifact_id,
            storage_key=storage_key,
            path=self._root.joinpath(*relative_path.parts),
            file_type=file_type,
            size_bytes=size_bytes,
            content_sha256=content_sha256,
            created=created,
            directory_links=directory_links,
            directory_fds=directory_fds,
            parent_fd=parent_fd,
            leaf_name=leaf_name,
            file_fd=file_fd,
            file_signature=file_signature,
        )

    def _open_directory_chain(
        self,
        relative_path: PurePosixPath,
        *,
        create: bool,
    ) -> tuple[tuple[_DirectoryLink, ...], tuple[int, ...], int]:
        if create:
            self._root.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptors: list[int] = []
        links: list[_DirectoryLink] = []
        try:
            if self._root == self._root.parent:
                root_fd = os.open(self._root, flags)
                descriptors.append(root_fd)
            else:
                root_parent_fd = os.open(self._root.parent, flags)
                descriptors.append(root_parent_fd)
                root_fd = os.open(
                    self._root.name,
                    flags,
                    dir_fd=root_parent_fd,
                )
                descriptors.append(root_fd)
                links.append(
                    _DirectoryLink(
                        parent_fd=root_parent_fd,
                        name=self._root.name,
                        child_fd=root_fd,
                    )
                )
            current_fd = root_fd
            for part in relative_path.parts[:-1]:
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                child_fd = os.open(part, flags, dir_fd=current_fd)
                descriptors.append(child_fd)
                links.append(
                    _DirectoryLink(
                        parent_fd=current_fd,
                        name=part,
                        child_fd=child_fd,
                    )
                )
                current_fd = child_fd
            return tuple(links), tuple(descriptors), current_fd
        except OSError as error:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
            if error.errno == errno.ENOENT and not create:
                raise ArtifactNotFoundError(
                    "Reserved artifact directory is missing."
                ) from error
            if error.errno in {
                errno.ELOOP,
                errno.ENOTDIR,
                errno.ENOENT,
            }:
                raise InvalidUpload(
                    "Artifact path contains an unsafe directory entry."
                ) from error
            raise

    def _supports_descriptor_operations(self) -> bool:
        required_dir_fd = (os.open, os.mkdir, os.unlink, os.link, os.stat)
        return (
            hasattr(os, "O_DIRECTORY")
            and hasattr(os, "O_NOFOLLOW")
            and all(operation in os.supports_dir_fd for operation in required_dir_fd)
            and os.link in os.supports_follow_symlinks
            and os.stat in os.supports_follow_symlinks
        )


def _orphan_candidate_relative_path(
    candidate: ArtifactOrphanCandidate,
) -> PurePosixPath:
    canonical_path = validate_artifact_identity(
        candidate.job_id,
        candidate.artifact_id,
        candidate.file_type,
        candidate.storage_key,
    )
    candidate_path = validate_artifact_storage_key(
        candidate.job_id,
        candidate.path_storage_key,
    )
    if candidate_path == canonical_path:
        return candidate_path
    temporary_prefix = f".{canonical_path.name}."
    temporary_suffix = ".uploading"
    if (
        candidate_path.parts[:-1] != canonical_path.parts[:-1]
        or not candidate_path.name.startswith(temporary_prefix)
        or not candidate_path.name.endswith(temporary_suffix)
    ):
        raise InvalidUpload("Artifact orphan candidate does not have canonical identity.")
    temporary_id = candidate_path.name[
        len(temporary_prefix) : -len(temporary_suffix)
    ]
    try:
        if UUID(temporary_id).hex != temporary_id:
            raise ValueError("Artifact temporary upload ID is not canonical.")
    except ValueError as error:
        raise InvalidUpload(
            "Artifact orphan candidate does not have canonical identity."
        ) from error
    return candidate_path


def _hash_stable_file(
    descriptor: int,
) -> tuple[int, str, _FileSignature]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise InvalidUpload("Artifact is not a regular file.")
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    after = os.fstat(descriptor)
    before_signature = _file_signature(before)
    after_signature = _file_signature(after)
    if (
        before_signature.device,
        before_signature.inode,
        before_signature.size_bytes,
        before_signature.modified_ns,
    ) != (
        after_signature.device,
        after_signature.inode,
        after_signature.size_bytes,
        after_signature.modified_ns,
    ):
        raise InvalidUpload("Artifact changed while it was being hashed.")
    return after.st_size, digest.hexdigest(), after_signature


def _file_signature(stat_result: os.stat_result) -> _FileSignature:
    return _FileSignature(
        device=stat_result.st_dev,
        inode=stat_result.st_ino,
        size_bytes=stat_result.st_size,
        modified_ns=stat_result.st_mtime_ns,
        changed_ns=stat_result.st_ctime_ns,
    )


def _write_all(descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written == 0:
            raise OSError("Artifact write made no progress.")
        remaining = remaining[written:]


def _unlink_named_inode(
    parent_fd: int,
    leaf_name: str,
    expected_inode: tuple[int, int],
) -> bool:
    try:
        named = os.stat(
            leaf_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return False
    if (named.st_dev, named.st_ino) != expected_inode:
        return False
    os.unlink(leaf_name, dir_fd=parent_fd)
    return True
