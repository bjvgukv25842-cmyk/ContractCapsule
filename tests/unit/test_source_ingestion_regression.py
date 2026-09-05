"""Pre-refactor characterizations of source identity and validation effects."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from contractcapsule.audit.quarantine import (
    QuarantineError,
    QuarantineStore,
    SecretDetectedError,
)
from contractcapsule.build.ingest import SourceInput, SourceMode, snapshot_source
from contractcapsule.models import Principal
from contractcapsule.storage.cas import FilesystemCAS

pytest_plugins = ("tests.integration.test_build_pipeline",)


@pytest.mark.parametrize("mode", ["CAS", "GIT_IMMUTABLE", "EXTERNAL_IMMUTABLE"])
def test_snapshot_identity_metadata_and_public_trust_are_preserved(
    git_source: tuple[Path, str, Principal], tmp_path: Path, mode: SourceMode
) -> None:
    root, revision, principal = git_source
    content = b"# Token policy\nTokens MUST expire within 15 minutes.\n"
    store = QuarantineStore()
    cas = FilesystemCAS(tmp_path / "cas")
    external = mode == "EXTERNAL_IMMUTABLE"
    source = SourceInput(
        mode=mode,
        path=None if external else root / "policy.md",
        repository_root=None if external else root,
        repository="https://example.invalid/project"
        if mode == "GIT_IMMUTABLE"
        else None,
        revision=f"sha1:{revision}" if mode == "GIT_IMMUTABLE" else None,
        content=content if external else None,
        uri="urn:example:policy" if external else None,
        source="publisher-record" if external else None,
        verification_method="publisher-checksum" if external else None,
        media_type="text/plain",
        cas=cas,
        quarantine=store,
    )
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    metadata = {
        "mode": mode,
        "repository": "https://example.invalid/project"
        if mode == "GIT_IMMUTABLE"
        else None,
        "revision": f"sha1:{revision}" if mode == "GIT_IMMUTABLE" else None,
        "path": "urn:example:policy" if external else "policy.md",
        "content_digest": digest,
        "media_type": "text/plain",
        "uri": "urn:example:policy" if external else None,
        "source": "publisher-record" if external else None,
        "verification_method": "publisher-checksum" if external else None,
        "access_policy": "repository-authorized",
        "generated": False,
    }
    # ASCII-only fixture values have the same JSON representation under JCS.
    identity_bytes = json.dumps(
        metadata, sort_keys=True, separators=(",", ":")
    ).encode()

    snapshot = snapshot_source(source, principal)

    assert (
        snapshot.snapshot_id
        == "snapshot-" + hashlib.sha256(identity_bytes).hexdigest()[:32]
    )
    assert snapshot.content == content
    for key, value in metadata.items():
        assert getattr(snapshot, "relative_path" if key == "path" else key) == value
    assert snapshot.path == (None if external else root / "policy.md")
    assert snapshot.repository_root == (None if external else root)
    assert snapshot.parser_kind == ("text" if external else "markdown")
    assert snapshot.principal_id == "m3-test"
    assert datetime.fromisoformat(snapshot.captured_at).utcoffset() == timedelta(0)
    assert snapshot.quarantine is store
    assert store._snapshots[snapshot.snapshot_id] is snapshot
    assert not store.has_deterministic_source_proof(snapshot)
    assert snapshot._source_proof is None
    assert cas.object_path(digest).is_file()


@pytest.mark.parametrize(
    ("filename", "content", "error_type", "message"),
    [
        ("bad.txt", b"\xff", SecretDetectedError, "evidence is not valid UTF-8"),
        ("bad.json", b"{", QuarantineError, "source JSON is invalid"),
        ("bad.yaml", b"[", QuarantineError, "source YAML is invalid"),
        (
            "secret.md",
            b"sk-test-1234567890",
            SecretDetectedError,
            "secret-like content is forbidden in source evidence",
        ),
    ],
)
def test_validation_failure_precedes_cas_and_registration(
    tmp_path: Path,
    filename: str,
    content: bytes,
    error_type: type[Exception],
    message: str,
) -> None:
    path = tmp_path / filename
    path.write_bytes(content)
    cas = FilesystemCAS(tmp_path / "cas")
    store = QuarantineStore()

    with pytest.raises(error_type) as caught:
        snapshot_source(
            SourceInput(path=path, cas=cas, quarantine=store), Principal("reader")
        )

    assert type(caught.value) is error_type
    assert str(caught.value) == message
    if content == b"\xff":
        assert isinstance(caught.value.__cause__, UnicodeDecodeError)
    assert not list(cas.root.rglob("*.blob"))
    assert not list(cas.root.rglob("*.lock"))
    assert store._snapshots == {}


@pytest.mark.parametrize("failure", ["missing", "outside", "git-mismatch"])
def test_locator_failure_precedes_content_validation_and_persistence(
    git_source: tuple[Path, str, Principal], tmp_path: Path, failure: str
) -> None:
    root, revision, principal = git_source
    path = root / "policy.md"
    messages = {
        "missing": "source path must be an existing regular file",
        "outside": "source path must be inside repository root",
        "git-mismatch": "source working tree differs from immutable commit",
    }
    if failure == "missing":
        path = root / "missing.md"
    else:
        if failure == "outside":
            path = tmp_path / "outside.md"
        path.write_bytes(b"sk-test-1234567890")
    cas = FilesystemCAS(tmp_path / "cas")
    store = QuarantineStore()
    source = SourceInput(
        path=path,
        repository_root=root,
        mode="GIT_IMMUTABLE",
        repository="https://example.invalid/project",
        revision=f"sha1:{revision}",
        cas=cas,
        quarantine=store,
    )

    with pytest.raises(QuarantineError) as caught:
        snapshot_source(source, principal)

    assert type(caught.value) is QuarantineError
    assert str(caught.value) == messages[failure]
    assert not list(cas.root.rglob("*.blob"))
    assert not list(cas.root.rglob("*.lock"))
    assert store._snapshots == {}
