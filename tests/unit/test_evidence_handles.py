"""Native evidence reads repeat authorization and exact source verification."""

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

import pytest

from contractcapsule.audit.quarantine import ApprovalAuthority, QuarantineStore
from contractcapsule.build.atomize import bind_evidence, extract_candidate_atoms
from contractcapsule.build.ingest import (
    SourceInput,
    TrustedDeterministicCollector,
    snapshot_source,
)
from contractcapsule.build.publish import BuildRequest, build_capsule, publish_draft
from contractcapsule.compile.errors import CompileError
from contractcapsule.compile.evidence import NativeEvidenceResolver, _source_span
from contractcapsule.models.base import Principal
from contractcapsule.models.view import TaskContext
from contractcapsule.resolve.policies import StaticEligibilityAuthorizer
from contractcapsule.storage.cas import FilesystemCAS
from contractcapsule.storage.registry import PublishedCapsule, Registry
from tests.m4_helpers import FixtureRegistryPolicy, M4Fixture
from tests.unit.test_eligibility import (
    AS_OF,
    READER,
    access_grant,
    freshness_for,
    task_context,
)


def service(fixture: M4Fixture, pub: PublishedCapsule) -> NativeEvidenceResolver:
    return NativeEvidenceResolver(
        registry=fixture.registry,
        authorizer=StaticEligibilityAuthorizer(grants=(access_grant(),)),
        freshness=freshness_for(pub),
        git_roots={},
        external_sources={},
    )


def test_real_cas_excerpt_and_expansion_are_exact(tmp_path: Path) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish(atoms=({"statement": "  MUST retain exact source.\r\n"},))
    resolver = service(fixture, pub)
    result = resolver.resolve(
        pub, pub.capsule.semantic_payload.atoms[0], READER, task_context(), AS_OF
    )
    assert len(result) == 1
    assert result[0].excerpt == "  MUST retain exact source.\r\n"
    assert result[0].full_text == result[0].excerpt
    assert resolver.expand(result[0].handle, READER, task_context(), AS_OF) == result[0]


def test_current_permissions_are_rechecked_on_expansion(tmp_path: Path) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish()
    resolver = service(fixture, pub)
    item = resolver.resolve(
        pub, pub.capsule.semantic_payload.atoms[0], READER, task_context(), AS_OF
    )[0]
    denied = replace(resolver, authorizer=StaticEligibilityAuthorizer())
    with pytest.raises(CompileError, match="EVIDENCE_UNAUTHORIZED"):
        denied.expand(item.handle, READER, task_context(), AS_OF)
    with pytest.raises(CompileError):
        resolver.expand(item.handle, Principal("unknown"), task_context(), AS_OF)


@pytest.mark.parametrize(
    "field", ["content_digest", "span_digest", "resolver_version", "atom_ids"]
)
def test_handle_tampering_is_rejected(tmp_path: Path, field: str) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish()
    resolver = service(fixture, pub)
    item = resolver.resolve(
        pub, pub.capsule.semantic_payload.atoms[0], READER, task_context(), AS_OF
    )[0]
    value: object = ("not-an-atom",) if field == "atom_ids" else "sha256:" + "0" * 64
    changed = item.handle.model_copy(update={field: value})
    with pytest.raises(CompileError, match="EVIDENCE_"):
        resolver.expand(changed, READER, task_context(), AS_OF)


def test_wrong_atom_does_not_reuse_a_valid_publication(tmp_path: Path) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish()
    item = pub.capsule.semantic_payload.atoms[0].model_copy(
        update={"statement": "forged"}
    )
    with pytest.raises(CompileError, match="EVIDENCE_"):
        service(fixture, pub).resolve(pub, item, READER, task_context(), AS_OF)


@pytest.mark.parametrize("fault", ["span_digest", "span_lines"])
def test_verified_core_with_unresolvable_source_span_is_rejected(
    tmp_path: Path, fault: str
) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish()
    record = pub.capsule.evidence_plane.records[0]
    source_map = dict(record.extensions["x-source-map"])
    if fault == "span_digest":
        source_map["span_digest"] = "sha256:" + "0" * 64
    else:
        source_map["start_line"] = source_map["end_line"] = 999
    changed = record.model_copy(update={"extensions": {"x-source-map": source_map}})
    data = fixture.registry.get_blob(record.content_digest, READER)
    # Pure extraction boundary: this malformed copied record is not a publication proof.
    with pytest.raises(CompileError, match="EVIDENCE_"):
        _source_span(changed, data)


def native_publication(
    tmp_path: Path, mode: Literal["GIT_IMMUTABLE", "EXTERNAL_IMMUTABLE"]
):
    path = tmp_path / "source.md"
    path.write_bytes(b"# Evidence\r\nMUST keep native bytes.\r\n")
    authority = ApprovalAuthority({"reviewer": b"native-evidence-test"})
    store = QuarantineStore(trust_root=authority.trust_root())
    principal = Principal("publisher")
    source_args: dict[str, Any] = {
        "quarantine": store,
        "access_policy": "team-auth",
        "generated": mode != "GIT_IMMUTABLE",
    }
    if mode == "GIT_IMMUTABLE":
        for command in [
            ("init", "-q"),
            ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "M4 Test"),
            ("remote", "add", "origin", "https://example.invalid/repo"),
            ("add", "source.md"),
            ("commit", "-qm", "fixture"),
        ]:
            subprocess.run(
                ["git", *command], cwd=tmp_path, check=True, capture_output=True
            )
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
        ).strip()
        source = SourceInput(
            path=path,
            mode=mode,
            repository="https://example.invalid/repo",
            repository_root=tmp_path,
            revision="sha1:" + revision,
            **source_args,
        )
    else:
        source = SourceInput(
            mode=mode,
            content=path.read_bytes(),
            uri="https://example.invalid/evidence",
            source="test-author",
            verification_method="test-checksum",
            **source_args,
        )
    snapshot = (
        TrustedDeterministicCollector(store, authority.trust_root()).snapshot(
            source, principal
        )
        if mode == "GIT_IMMUTABLE"
        else snapshot_source(source, principal)
    )
    candidate = extract_candidate_atoms(snapshot)[1]
    binding = bind_evidence(candidate, snapshot)
    approval = authority.issue(candidate, (binding,), "reviewer")
    atom = store.promote(candidate.candidate_id, approval)
    draft = build_capsule(
        BuildRequest(
            atoms=(atom,),
            quarantine=store,
            tenant="example",
            lifecycle="PUBLISHED",
            environments=("prod",),
            detached_signature={
                "algorithm": "m3-test-only",
                "key_id": "m3-test-key",
                "value": "test-only",
                "envelope": {},
            },
        )
    )
    registry = Registry(
        tmp_path / "registry.sqlite3",
        FilesystemCAS(tmp_path / "cas"),
        FixtureRegistryPolicy(),
        trust_root=authority.trust_root(),
    )
    pub = publish_draft(draft, principal, registry)
    task = TaskContext(
        task_id="native",
        tenant="example",
        repository=pub.capsule.control_manifest.scope.repositories[0],
        paths=(pub.capsule.control_manifest.scope.paths[0],),
        environment="prod",
        text="native",
    )
    resolver = NativeEvidenceResolver(
        registry=registry,
        authorizer=StaticEligibilityAuthorizer(grants=(access_grant(),)),
        freshness=freshness_for(pub),
        git_roots={"https://example.invalid/repo": tmp_path},
        external_sources={"https://example.invalid/evidence": path},
    )
    return pub, task, resolver, path


@pytest.mark.parametrize("mode", ["GIT_IMMUTABLE", "EXTERNAL_IMMUTABLE"])
def test_native_modes_resolve_exact_bytes_without_network(
    tmp_path: Path, mode: Literal["GIT_IMMUTABLE", "EXTERNAL_IMMUTABLE"]
) -> None:
    pub, task, resolver, path = native_publication(tmp_path, mode)
    with patch("requests.get", side_effect=AssertionError("network forbidden")):
        result = resolver.resolve(
            pub, pub.capsule.semantic_payload.atoms[0], READER, task, AS_OF
        )[0]
    assert result.excerpt == "MUST keep native bytes.\r\n"
    assert result.full_text == "# Evidence\r\nMUST keep native bytes.\r\n"
    path.write_bytes(b"changed current file\n")
    if mode == "GIT_IMMUTABLE":
        assert resolver.expand(result.handle, READER, task, AS_OF) == result
    else:
        with pytest.raises(CompileError, match="EVIDENCE_INTEGRITY"):
            resolver.expand(result.handle, READER, task, AS_OF)


def test_unknown_external_mapping_never_fetches(tmp_path: Path) -> None:
    pub, task, resolver, _ = native_publication(tmp_path, "EXTERNAL_IMMUTABLE")
    resolver = replace(resolver, external_sources={})
    with (
        patch("requests.get", side_effect=AssertionError("network forbidden")),
        pytest.raises(CompileError, match="EVIDENCE_UNAVAILABLE"),
    ):
        resolver.resolve(
            pub, pub.capsule.semantic_payload.atoms[0], READER, task, AS_OF
        )


def test_cas_tamper_after_handle_creation_blocks_expansion(tmp_path: Path) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish()
    resolver = service(fixture, pub)
    source = resolver.resolve(
        pub, pub.capsule.semantic_payload.atoms[0], READER, task_context(), AS_OF
    )[0]
    path = fixture.harness.cas.object_path(source.handle.content_digest)
    path.chmod(0o600)
    path.write_bytes(b"corrupted CAS envelope")
    with pytest.raises(CompileError, match="^EVIDENCE_"):
        resolver.expand(source.handle, READER, task_context(), AS_OF)


def test_source_config_is_copied_and_symlink_source_rejected(tmp_path: Path) -> None:
    pub, task, resolver, path = native_publication(tmp_path, "EXTERNAL_IMMUTABLE")
    mappings = dict(resolver.external_sources)
    resolver = replace(resolver, external_sources=mappings)
    mappings.clear()
    assert resolver.resolve(
        pub, pub.capsule.semantic_payload.atoms[0], READER, task, AS_OF
    )
    original = path.rename(tmp_path / "original.md")
    path.symlink_to(original)
    with pytest.raises(CompileError, match="^EVIDENCE_UNAVAILABLE$"):
        resolver.resolve(
            pub, pub.capsule.semantic_payload.atoms[0], READER, task, AS_OF
        )


def test_missing_git_root_and_changed_repository_identity_block(tmp_path: Path) -> None:
    pub, task, resolver, _ = native_publication(tmp_path, "GIT_IMMUTABLE")
    with pytest.raises(CompileError, match="^EVIDENCE_UNAVAILABLE$"):
        replace(resolver, git_roots={}).resolve(
            pub, pub.capsule.semantic_payload.atoms[0], READER, task, AS_OF
        )
    subprocess.run(
        ["git", "config", "remote.origin.url", "https://example.invalid/other"],
        cwd=tmp_path,
        check=True,
    )
    with pytest.raises(CompileError, match="^EVIDENCE_UNAVAILABLE$"):
        resolver.resolve(
            pub, pub.capsule.semantic_payload.atoms[0], READER, task, AS_OF
        )


def test_scanner_fault_prevents_material_return(tmp_path: Path) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish()
    with (
        patch(
            "contractcapsule.compile.evidence.scan_secrets",
            side_effect=RuntimeError("private details"),
        ),
        pytest.raises(CompileError, match="^SECRET_DETECTED$"),
    ):
        service(fixture, pub).resolve(
            pub, pub.capsule.semantic_payload.atoms[0], READER, task_context(), AS_OF
        )


def test_legacy_cas_without_span_map_uses_exact_full_blob(tmp_path: Path) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish()
    record = pub.capsule.evidence_plane.records[0].model_copy(update={"extensions": {}})
    content = fixture.registry.get_blob(record.content_digest, READER)
    assert _source_span(record, content) == (content.decode("utf-8"), None)


def test_external_full_blob_drift_blocks_even_when_excerpt_is_unchanged(
    tmp_path: Path,
) -> None:
    pub, task, resolver, path = native_publication(tmp_path, "EXTERNAL_IMMUTABLE")
    item = resolver.resolve(
        pub, pub.capsule.semantic_payload.atoms[0], READER, task, AS_OF
    )[0]
    path.write_bytes(b"# Replaced\r\nMUST keep native bytes.\r\n")
    with pytest.raises(CompileError, match="^EVIDENCE_INTEGRITY$"):
        resolver.expand(item.handle, READER, task, AS_OF)
