from __future__ import annotations

import hashlib
import inspect
import json
import struct
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from contractcapsule.models import Principal
from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.storage.cas import (
    BlobAuthorizationError,
    BlobIntegrityError,
    BlobMetadataConflict,
    FilesystemCAS,
)


class AllowDigest:
    def __init__(self, digest: str | None = None) -> None:
        self.digest = digest

    def can_read_blob(self, digest: str, principal: Principal) -> bool:
        return self.digest == digest and principal.principal_id == "reader"


class TruthyButInvalidAuthorizer:
    def can_read_blob(self, digest: str, principal: Principal) -> bool:
        del digest, principal
        return 1  # type: ignore[return-value]


def test_identical_bytes_have_same_digest_and_duplicate_write_is_idempotent(
    tmp_path: Path,
) -> None:
    cas = FilesystemCAS(tmp_path)
    first = cas.put_blob(b"same", "text/plain")
    second = cas.put_blob(b"same", "text/plain")
    assert first == second
    assert first.digest.startswith("sha256:")
    assert len(list((tmp_path / "objects").rglob("*.blob"))) == 1


def test_same_bytes_with_different_media_type_is_immutable_conflict(tmp_path: Path) -> None:
    cas = FilesystemCAS(tmp_path)
    cas.put_blob(b"same", "text/plain")
    with pytest.raises(BlobMetadataConflict):
        cas.put_blob(b"same", "application/octet-stream")


def test_put_does_not_grant_read_and_default_is_deny(tmp_path: Path) -> None:
    cas = FilesystemCAS(tmp_path)
    ref = cas.put_blob(b"private", "text/plain")
    with pytest.raises(BlobAuthorizationError):
        cas.get_blob(ref.digest, Principal("writer"))


def test_non_boolean_authorizer_result_fails_closed(tmp_path: Path) -> None:
    writer = FilesystemCAS(tmp_path)
    ref = writer.put_blob(b"private", "text/plain")
    cas = FilesystemCAS(tmp_path, authorizer=TruthyButInvalidAuthorizer())
    with pytest.raises(BlobAuthorizationError):
        cas.get_blob(ref.digest, Principal("reader"))


def test_authorized_read_revalidates_content_and_detects_tamper(tmp_path: Path) -> None:
    temporary = FilesystemCAS(tmp_path)
    ref = temporary.put_blob(b"evidence", "text/plain")
    cas = FilesystemCAS(tmp_path, authorizer=AllowDigest(ref.digest))
    assert cas.get_blob(ref.digest, Principal("reader")) == b"evidence"

    path = cas.object_path(ref.digest)
    path.chmod(0o644)
    path.write_bytes(b"tampered")
    with pytest.raises(BlobIntegrityError):
        cas.get_blob(ref.digest, Principal("reader"))


@pytest.mark.parametrize("digest", ["../secret", "sha256:abc", "SHA256:" + "a" * 64])
def test_invalid_digest_never_reaches_filesystem(tmp_path: Path, digest: str) -> None:
    cas = FilesystemCAS(tmp_path, authorizer=AllowDigest(digest))
    with pytest.raises(ValueError):
        cas.get_blob(digest, Principal("reader"))


def test_existing_corrupt_object_is_never_overwritten(tmp_path: Path) -> None:
    cas = FilesystemCAS(tmp_path)
    ref = cas.put_blob(b"original", "text/plain")
    path = cas.object_path(ref.digest)
    path.chmod(0o644)
    path.write_bytes(b"corrupt")
    with pytest.raises(BlobIntegrityError):
        cas.put_blob(b"original", "text/plain")
    assert path.read_bytes() == b"corrupt"


def test_concurrent_writes_publish_one_complete_object(tmp_path: Path) -> None:
    cas = FilesystemCAS(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        refs = list(pool.map(lambda _: cas.put_blob(b"concurrent", "text/plain"), range(32)))
    assert len({ref.digest for ref in refs}) == 1
    assert cas._read_verified(refs[0].digest).data == b"concurrent"
    assert len(list((tmp_path / "objects").rglob("*.blob"))) == 1


def test_failed_atomic_commit_leaves_no_visible_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cas = FilesystemCAS(tmp_path)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("injected link failure")

    monkeypatch.setattr(cas, "_link_no_replace", fail)
    with pytest.raises(OSError, match="injected"):
        cas.put_blob(b"never-visible", "text/plain")
    assert not list((tmp_path / "objects").rglob("*.blob"))


def test_post_link_commit_failure_removes_newly_linked_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cas = FilesystemCAS(tmp_path)

    def fail(directory: Path) -> None:
        del directory
        raise OSError("injected directory sync failure")

    monkeypatch.setattr(cas, "_fsync_directory", fail)
    with pytest.raises(OSError, match="directory sync"):
        cas.put_blob(b"not-committed", "text/plain")
    assert not list((tmp_path / "objects").rglob("*.blob"))


def test_concurrent_writer_cannot_observe_an_uncommitted_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cas = FilesystemCAS(tmp_path)
    linked = threading.Event()
    release_first_sync = threading.Event()
    second_done = threading.Event()
    real_link = cas._link_no_replace
    real_sync = cas._fsync_directory
    sync_calls = 0

    def observed_link(temporary: Path, final: Path) -> None:
        real_link(temporary, final)
        linked.set()

    def first_sync_fails(directory: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 1:
            assert release_first_sync.wait(timeout=2)
            raise OSError("injected first directory sync failure")
        real_sync(directory)

    monkeypatch.setattr(cas, "_link_no_replace", observed_link)
    monkeypatch.setattr(cas, "_fsync_directory", first_sync_fails)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cas.put_blob, b"serialized", "text/plain")
        assert linked.wait(timeout=2)
        second = pool.submit(cas.put_blob, b"serialized", "text/plain")
        second.add_done_callback(lambda _: second_done.set())
        second_done.wait(timeout=0.2)
        release_first_sync.set()
        with pytest.raises(OSError, match="first directory sync"):
            first.result(timeout=2)
        ref = second.result(timeout=2)

    assert cas._read_verified(ref.digest).data == b"serialized"


def test_atomic_commit_implementation_does_not_use_overwrite_replace() -> None:
    source = inspect.getsource(FilesystemCAS)
    assert "os.replace" not in source
    assert "os.link" in source


def test_noncanonical_or_duplicate_cas_header_is_treated_as_tamper(tmp_path: Path) -> None:
    cas = FilesystemCAS(tmp_path)
    ref = cas.put_blob(b"header", "text/plain")
    path = cas.object_path(ref.digest)
    raw = path.read_bytes()
    magic_length = len(b"CCS-CAS-1\0")
    (header_length,) = struct.unpack(">I", raw[magic_length : magic_length + 4])
    header_start = magic_length + 4
    header = raw[header_start : header_start + header_length]
    changed_header = b" " + header
    tampered = (
        raw[:magic_length]
        + struct.pack(">I", len(changed_header))
        + changed_header
        + raw[header_start + header_length :]
    )
    path.chmod(0o644)
    path.write_bytes(tampered)
    with pytest.raises(BlobIntegrityError):
        cas._read_verified(ref.digest)


def test_unknown_canonical_cas_header_field_is_treated_as_tamper(tmp_path: Path) -> None:
    cas = FilesystemCAS(tmp_path)
    ref = cas.put_blob(b"header-extra", "text/plain")
    path = cas.object_path(ref.digest)
    raw = path.read_bytes()
    magic_length = len(b"CCS-CAS-1\0")
    (header_length,) = struct.unpack(">I", raw[magic_length : magic_length + 4])
    header_start = magic_length + 4
    header = json.loads(raw[header_start : header_start + header_length])
    header["unknown"] = "field"
    changed_header = canonical_json_bytes(header)
    tampered = (
        raw[:magic_length]
        + struct.pack(">I", len(changed_header))
        + changed_header
        + raw[header_start + header_length :]
    )
    path.chmod(0o644)
    path.write_bytes(tampered)
    with pytest.raises(BlobIntegrityError):
        cas._read_verified(ref.digest)


def test_symlinked_internal_storage_directory_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "cas"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "objects").symlink_to(outside, target_is_directory=True)

    with pytest.raises(BlobIntegrityError, match="symbolic link"):
        FilesystemCAS(root)


def test_symlinked_digest_prefix_cannot_redirect_a_write(tmp_path: Path) -> None:
    cas = FilesystemCAS(tmp_path / "cas")
    outside = tmp_path / "outside"
    outside.mkdir()
    prefix = hashlib.sha256(b"redirect").hexdigest()[:2]
    prefix_path = cas.root / "objects" / "sha256" / prefix
    prefix_path.symlink_to(outside, target_is_directory=True)

    with pytest.raises(BlobIntegrityError, match="symbolic link"):
        cas.put_blob(b"redirect", "text/plain")
    assert not list(outside.iterdir())
