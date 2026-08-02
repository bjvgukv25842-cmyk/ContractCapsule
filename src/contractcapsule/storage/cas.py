"""Local immutable filesystem CAS with fail-closed public reads."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import struct
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from contractcapsule.models import Principal
from contractcapsule.models.base import (
    DIGEST_PATTERN,
    MEDIA_TYPE_PATTERN,
    reject_surrogates,
)
from contractcapsule.models.canonical import canonical_json_bytes

_MAGIC = b"CCS-CAS-1\x00"
_HEADER_LENGTH = struct.Struct(">I")
_DIGEST_RE = re.compile(DIGEST_PATTERN)
_MEDIA_TYPE_RE = re.compile(MEDIA_TYPE_PATTERN)


class BlobError(RuntimeError):
    """Base class for CAS failures."""


class BlobAuthorizationError(BlobError):
    """The trusted authorization path did not explicitly allow a read."""


class BlobIntegrityError(BlobError):
    """A stored object is missing, malformed, or does not match its digest."""


class BlobMetadataConflict(BlobError):
    """Existing immutable bytes were associated with different metadata."""


@dataclass(frozen=True, slots=True)
class BlobRef:
    digest: str
    media_type: str
    size: int


@dataclass(frozen=True, slots=True)
class StoredBlob:
    ref: BlobRef
    data: bytes


class BlobAuthorizer(Protocol):
    def can_read_blob(self, digest: str, principal: Principal) -> bool: ...


class _DenyAllBlobAuthorizer:
    def can_read_blob(self, digest: str, principal: Principal) -> bool:
        del digest, principal
        return False


def _validate_digest(digest: str) -> str:
    if _DIGEST_RE.fullmatch(digest) is None:
        raise ValueError("digest must be sha256 followed by 64 lowercase hexadecimal digits")
    return digest


def _validate_media_type(media_type: str) -> str:
    reject_surrogates(media_type)
    if _MEDIA_TYPE_RE.fullmatch(media_type) is None:
        raise ValueError("media_type is not a canonical media type")
    return media_type


class FilesystemCAS:
    """Digest-addressed immutable storage within one local trust domain."""

    def __init__(
        self,
        root: Path,
        authorizer: BlobAuthorizer | None = None,
    ) -> None:
        self.root = root
        self._authorizer = authorizer or _DenyAllBlobAuthorizer()
        if root.is_symlink():
            raise BlobIntegrityError("CAS root must not be a symbolic link")
        root.mkdir(parents=True, exist_ok=True)
        self._ensure_real_directory(root)
        self._ensure_real_directory(root / "objects", create=True)
        self._ensure_real_directory(root / "objects/sha256", create=True)
        self._ensure_real_directory(root / "locks", create=True)
        self._ensure_real_directory(root / "locks/sha256", create=True)

    @staticmethod
    def _ensure_real_directory(path: Path, *, create: bool = False) -> None:
        if path.is_symlink():
            raise BlobIntegrityError(f"CAS directory is a symbolic link: {path.name}")
        if create:
            path.mkdir(exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise BlobIntegrityError(f"CAS directory is missing or invalid: {path.name}")

    def _validate_object_directory(self, path: Path, *, create: bool = False) -> None:
        self._ensure_real_directory(self.root)
        self._ensure_real_directory(self.root / "objects")
        self._ensure_real_directory(self.root / "objects/sha256")
        self._ensure_real_directory(path.parent, create=create)

    def _lock_path(self, digest: str) -> Path:
        hex_digest = _validate_digest(digest).removeprefix("sha256:")
        return self.root / "locks/sha256" / hex_digest[:2] / f"{hex_digest[2:]}.lock"

    @contextmanager
    def _digest_lock(self, digest: str, *, exclusive: bool) -> Iterator[None]:
        lock_path = self._lock_path(digest)
        self._ensure_real_directory(self.root)
        self._ensure_real_directory(self.root / "locks")
        self._ensure_real_directory(self.root / "locks/sha256")
        self._ensure_real_directory(lock_path.parent, create=True)
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as error:
            raise BlobIntegrityError("CAS digest lock is unavailable") from error
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise BlobIntegrityError("CAS digest lock is not a regular file")
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(descriptor, operation)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def object_path(self, digest: str) -> Path:
        hex_digest = _validate_digest(digest).removeprefix("sha256:")
        return self.root / "objects/sha256" / hex_digest[:2] / f"{hex_digest[2:]}.blob"

    @staticmethod
    def _envelope(data: bytes, media_type: str, digest: str) -> bytes:
        header = canonical_json_bytes(
            {"digest": digest, "media_type": media_type, "size": len(data)}
        )
        return _MAGIC + _HEADER_LENGTH.pack(len(header)) + header + data

    @staticmethod
    def _link_no_replace(temporary: Path, final: Path) -> None:
        os.link(temporary, final, follow_symlinks=False)

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def put_blob(self, data: bytes, media_type: str) -> BlobRef:
        if not isinstance(data, bytes):
            raise TypeError("CAS data must be bytes")
        media_type = _validate_media_type(media_type)
        digest = f"sha256:{hashlib.sha256(data).hexdigest()}"
        expected = BlobRef(digest=digest, media_type=media_type, size=len(data))
        final = self.object_path(digest)
        with self._digest_lock(digest, exclusive=True):
            return self._put_locked(data, media_type, expected, final)

    def _put_locked(
        self,
        data: bytes,
        media_type: str,
        expected: BlobRef,
        final: Path,
    ) -> BlobRef:
        self._validate_object_directory(final, create=True)

        if final.exists() or final.is_symlink():
            stored = self._read_verified_unlocked(expected.digest)
            if stored.ref.media_type != media_type:
                raise BlobMetadataConflict("immutable object already has another media type")
            return stored.ref

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".ccs-cas-", suffix=".tmp", dir=final.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(self._envelope(data, media_type, expected.digest))
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(
                    stream.fileno(), stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
                )
            try:
                self._link_no_replace(temporary, final)
                try:
                    self._fsync_directory(final.parent)
                except OSError:
                    temporary_stat = temporary.stat(follow_symlinks=False)
                    final_stat = final.stat(follow_symlinks=False)
                    if (
                        temporary_stat.st_dev == final_stat.st_dev
                        and temporary_stat.st_ino == final_stat.st_ino
                    ):
                        final.unlink()
                    raise
                return expected
            except FileExistsError:
                stored = self._read_verified_unlocked(expected.digest)
                if stored.ref.media_type != media_type:
                    raise BlobMetadataConflict(
                        "immutable object already has another media type"
                    )
                return stored.ref
        finally:
            temporary.unlink(missing_ok=True)

    def _read_verified(self, digest: str) -> StoredBlob:
        with self._digest_lock(digest, exclusive=False):
            return self._read_verified_unlocked(digest)

    def _read_verified_unlocked(self, digest: str) -> StoredBlob:
        path = self.object_path(digest)
        self._validate_object_directory(path)
        if path.is_symlink() or not path.is_file():
            raise BlobIntegrityError("CAS object is missing or not a regular file")
        try:
            raw = path.read_bytes()
            if not raw.startswith(_MAGIC) or len(raw) < len(_MAGIC) + _HEADER_LENGTH.size:
                raise BlobIntegrityError("CAS envelope is malformed")
            offset = len(_MAGIC)
            (header_length,) = _HEADER_LENGTH.unpack(
                raw[offset : offset + _HEADER_LENGTH.size]
            )
            offset += _HEADER_LENGTH.size
            if header_length == 0 or offset + header_length > len(raw):
                raise BlobIntegrityError("CAS envelope header length is invalid")
            header_bytes = raw[offset : offset + header_length]
            data = raw[offset + header_length :]
            header = json.loads(header_bytes.decode("utf-8"))
            if (
                not isinstance(header, dict)
                or set(header) != {"digest", "media_type", "size"}
                or canonical_json_bytes(header) != header_bytes
            ):
                raise BlobIntegrityError("CAS envelope header is not canonical JCS")
            media_type = _validate_media_type(header["media_type"])
            stored_digest = _validate_digest(header["digest"])
            size = header["size"]
        except BlobIntegrityError:
            raise
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BlobIntegrityError("CAS envelope is malformed") from error
        actual = f"sha256:{hashlib.sha256(data).hexdigest()}"
        if (
            stored_digest != digest
            or actual != digest
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size != len(data)
        ):
            raise BlobIntegrityError("CAS object failed digest or size verification")
        return StoredBlob(BlobRef(digest, media_type, size), data)

    def get_blob(self, digest: str, principal: Principal) -> bytes:
        _validate_digest(digest)
        try:
            allowed = self._authorizer.can_read_blob(digest, principal)
        except Exception as error:
            raise BlobAuthorizationError("blob read is not authorized") from error
        if allowed is not True:
            raise BlobAuthorizationError("blob read is not authorized")
        return self._read_verified(digest).data


def put_blob(data: bytes, media_type: str, *, cas: FilesystemCAS) -> BlobRef:
    """Required functional interface with an explicitly injected store."""

    return cas.put_blob(data, media_type)


def get_blob(digest: str, principal: Principal, *, cas: FilesystemCAS) -> bytes:
    """Required functional interface with fail-closed injected authorization."""

    return cas.get_blob(digest, principal)
