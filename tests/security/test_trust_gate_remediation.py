from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from contractcapsule.audit.quarantine import (
    ApprovalAuthority,
    CandidateAtom,
    HumanApproval,
    PublicationPermit,
    QuarantineError,
    QuarantineStore,
    TrustLevel,
    _HmacApprovalVerifier,
)
from contractcapsule.build.atomize import bind_evidence, extract_candidate_atoms
from contractcapsule.build.ingest import (
    SourceInput,
    SourceSnapshot,
    TrustedDeterministicCollector,
    snapshot_source,
)
from contractcapsule.build.publish import (
    BuildError,
    BuildRequest,
    DraftCapsule,
    _loader_attestation,
    _LoaderReceipt,
    build_capsule,
    publish_draft,
)
from contractcapsule.models import Capsule, Principal
from contractcapsule.models.canonical import canonical_digest, canonical_json_bytes
from contractcapsule.storage.cas import FilesystemCAS
from contractcapsule.storage.registry import (
    PolicyDecision,
    PublicationIntegrityError,
    Registry,
)


class _AllowPolicy:
    def resolve(
        self,
        principal: Principal,
        action: str,
        authority: str,
        scope: object,
    ) -> PolicyDecision:
        del principal, action, authority, scope
        return PolicyDecision(True, frozenset({"repository-authorized", "team-auth"}))


class _AllowAllVerifier:
    def verify(self, approval: HumanApproval) -> bool:
        del approval
        return True


class _ForgedVerifier(_HmacApprovalVerifier):
    def verify(self, approval: HumanApproval) -> bool:
        del approval
        return True


class _FakeRegistry:
    def publish(self, capsule: object, principal: object, **kwargs: object) -> object:
        del capsule, principal, kwargs
        return object()


def _m3_fixture(
    tmp_path: Path,
    *,
    generated: bool = True,
    expires_at: datetime | None = None,
) -> tuple[
    ApprovalAuthority,
    QuarantineStore,
    Principal,
    SourceSnapshot,
    CandidateAtom,
    DraftCapsule,
]:
    path = tmp_path / "policy.md"
    path.write_text("# Policy\nThe service MUST use TLS.\n", encoding="utf-8")
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    trust_root_factory = getattr(authority, "trust_root", None)
    store = (
        QuarantineStore(trust_root=trust_root_factory())
        if trust_root_factory is not None
        else QuarantineStore(approval_verifier=authority.verifier())
    )
    principal = Principal("builder")
    cas = FilesystemCAS(tmp_path / "cas")
    snapshot = snapshot_source(
        SourceInput(
            path=path,
            mode="CAS",
            cas=cas,
            quarantine=store,
            generated=generated,
        ),
        principal,
    )
    candidates = extract_candidate_atoms(snapshot)
    candidate = candidates[1]
    binding = bind_evidence(candidate, snapshot)
    approval = authority.issue(
        candidate,
        (binding,),
        "reviewer",
        expires_at=expires_at,
    )
    validated = store.promote(candidate.candidate_id, approval)
    draft = build_capsule(
        BuildRequest(
            atoms=(validated,),
            quarantine=store,
            lifecycle="PUBLISHED",
            detached_signature={
                "algorithm": "m3-test-only",
                "key_id": "m3-test-key",
                "value": "test-signature-not-production",
                "envelope": {"x-purpose": "trust-gate-remediation"},
            },
        )
    )
    return authority, store, principal, snapshot, candidate, draft


def _registry(
    tmp_path: Path,
    authority: ApprovalAuthority | None = None,
) -> Registry:
    trust_root_factory = getattr(authority, "trust_root", None) if authority else None
    return Registry(
        tmp_path / "registry.sqlite3",
        FilesystemCAS(tmp_path / "cas"),
        resolver=_AllowPolicy(),
        **(
            {"trust_root": trust_root_factory()}
            if trust_root_factory is not None
            else {}
        ),
    )


def _with_current_digest(capsule: Capsule) -> Capsule:
    manifest = capsule.control_manifest.model_copy(
        update={"content_digest": "sha256:" + "0" * 64}
    )
    unsigned = capsule.model_copy(update={"control_manifest": manifest})
    return unsigned.model_copy(
        update={
            "control_manifest": manifest.model_copy(
                update={"content_digest": canonical_digest(unsigned)}
            )
        }
    )


def _without_m3_marker(capsule: Capsule) -> Capsule:
    manifest = capsule.control_manifest.model_copy(update={"extensions": {}})
    payload = capsule.semantic_payload.model_copy(
        update={
            "atoms": tuple(
                atom.model_copy(update={"extensions": {}})
                for atom in capsule.semantic_payload.atoms
            )
        }
    )
    return _with_current_digest(
        capsule.model_copy(
            update={"control_manifest": manifest, "semantic_payload": payload}
        )
    )


def _m3_git_fixture(
    tmp_path: Path,
) -> tuple[
    ApprovalAuthority,
    QuarantineStore,
    Principal,
    Path,
    DraftCapsule,
]:
    repository_root = tmp_path / "authoritative-repository"
    repository_root.mkdir()
    for args in (
        ("init", "-q"),
        ("config", "user.email", "test@example.invalid"),
        ("config", "user.name", "M3 test"),
        ("remote", "add", "origin", "https://example.invalid/project"),
    ):
        subprocess.run(
            ["git", *args], cwd=repository_root, check=True, capture_output=True
        )
    source_path = repository_root / "policy.md"
    source_path.write_text("# Policy\nThe service MUST use TLS.\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "policy.md"],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "authoritative fixture"],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository_root, text=True
    ).strip()
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    store = QuarantineStore(trust_root=authority.trust_root())
    principal = Principal("builder")
    collector = TrustedDeterministicCollector(store, authority.trust_root())
    snapshot = collector.snapshot(
        SourceInput(
            path=source_path,
            mode="GIT_IMMUTABLE",
            repository="https://example.invalid/project",
            revision=f"sha1:{revision}",
            repository_root=repository_root,
            quarantine=store,
            generated=False,
        ),
        principal,
    )
    candidate = extract_candidate_atoms(snapshot)[1]
    binding = bind_evidence(candidate, snapshot)
    approval = authority.issue(candidate, (binding,), "reviewer")
    validated = store.promote(candidate.candidate_id, approval)
    draft = build_capsule(
        BuildRequest(
            atoms=(validated,),
            quarantine=store,
            lifecycle="PUBLISHED",
            detached_signature={
                "algorithm": "m3-test-only",
                "key_id": "m3-test-key",
                "value": "test-signature-not-production",
                "envelope": {"x-purpose": "post-permit-source-recheck"},
            },
        )
    )
    return authority, store, principal, repository_root, draft


def _assert_old_permit_rejected_at_final_gate(
    registry: Registry,
    capsule: Capsule,
    principal: Principal,
    permit: PublicationPermit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_gate_entered = False
    original = registry._validate_m3_publication

    def track_final_gate(
        candidate: Capsule, publisher: Principal, proof: object | None
    ) -> object:
        nonlocal final_gate_entered
        final_gate_entered = True
        return original(candidate, publisher, proof)

    monkeypatch.setattr(registry, "_validate_m3_publication", track_final_gate)
    with pytest.raises(PublicationIntegrityError) as caught:
        registry.publish(capsule, principal, publication_permit=permit)
    assert final_gate_entered
    assert str(caught.value) == (
        "M3 trust permit capsule_digest does not match publication"
    )


def test_direct_registry_publish_rejects_m3_p1_without_trust_proof(
    tmp_path: Path,
) -> None:
    _authority, _store, principal, _snapshot, _candidate, draft = _m3_fixture(
        tmp_path, generated=True
    )
    with pytest.raises(PublicationIntegrityError, match="trust proof"):
        _registry(tmp_path).publish(draft.capsule, principal)


def test_direct_registry_publish_rejects_unmarked_p1_without_trust_proof(
    tmp_path: Path,
) -> None:
    """The M3 gate is mandatory even when a capsule omits the builder marker."""

    _authority, _store, _principal, _snapshot, _candidate, draft = _m3_fixture(
        tmp_path, generated=False
    )
    manifest = draft.capsule.control_manifest.model_copy(
        update={"extensions": {}, "content_digest": "sha256:" + "0" * 64}
    )
    payload = draft.capsule.semantic_payload.model_copy(
        update={
            "atoms": tuple(
                atom.model_copy(update={"extensions": {}})
                for atom in draft.capsule.semantic_payload.atoms
            )
        }
    )
    unsigned = draft.capsule.model_copy(
        update={"control_manifest": manifest, "semantic_payload": payload}
    )
    capsule = unsigned.model_copy(
        update={
            "control_manifest": manifest.model_copy(
                update={"content_digest": canonical_digest(unsigned)}
            )
        }
    )
    registry = _registry(tmp_path)
    with pytest.raises(PublicationIntegrityError, match="trust proof"):
        registry.publish(capsule, Principal("publisher"))


def test_configured_registry_rejects_p1_when_m3_marker_is_stripped(
    tmp_path: Path,
) -> None:
    authority, _store, principal, _snapshot, _candidate, draft = _m3_fixture(
        tmp_path, generated=True
    )
    unsigned_manifest = draft.capsule.control_manifest.model_copy(
        update={"extensions": {}, "content_digest": "sha256:" + "0" * 64}
    )
    unsigned_payload = draft.capsule.semantic_payload.model_copy(
        update={
            "atoms": tuple(
                atom.model_copy(update={"extensions": {}})
                for atom in draft.capsule.semantic_payload.atoms
            )
        }
    )
    unsigned = draft.capsule.model_copy(
        update={
            "control_manifest": unsigned_manifest,
            "semantic_payload": unsigned_payload,
        }
    )
    stripped = unsigned.model_copy(
        update={
            "control_manifest": unsigned_manifest.model_copy(
                update={"content_digest": canonical_digest(unsigned)}
            )
        }
    )
    with pytest.raises(PublicationIntegrityError, match="trust proof"):
        _registry(tmp_path, authority).publish(stripped, principal)


def test_direct_registry_publish_rejects_unmarked_p0_without_trust_proof(
    tmp_path: Path,
) -> None:
    """P0 itself activates the mandatory gate even without provenance markers."""

    _authority, _store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    atom = draft.capsule.semantic_payload.atoms[0].model_copy(
        update={"compression_class": "P0_EXACT"}
    )
    p0 = _without_m3_marker(
        draft.capsule.model_copy(
            update={
                "semantic_payload": draft.capsule.semantic_payload.model_copy(
                    update={"atoms": (atom,)}
                )
            }
        )
    )
    with pytest.raises(PublicationIntegrityError, match="M3 trust proof is required"):
        _registry(tmp_path).publish(p0, principal)


def test_real_p0_evidence_approval_promotion_loader_registry_path_succeeds(
    tmp_path: Path,
) -> None:
    from tests.m2_helpers import TrustedM3TestHarness

    cas = FilesystemCAS(tmp_path / "cas")
    harness = TrustedM3TestHarness.create(tmp_path, cas, principal_id="builder")
    draft = harness.build_draft(compression_class="P0_EXACT")
    published = harness.publish(
        draft,
        Registry(
            tmp_path / "p0-registry.sqlite3",
            cas,
            resolver=_AllowPolicy(),
            trust_root=harness.authority.trust_root(),
        ),
    )
    assert published.capsule.semantic_payload.atoms[0].compression_class == "P0_EXACT"
    assert published.registry_status == "PUBLISHED"


def test_p0_old_permit_cannot_target_a_changed_version(tmp_path: Path) -> None:
    from tests.m2_helpers import TrustedM3TestHarness

    cas = FilesystemCAS(tmp_path / "cas")
    harness = TrustedM3TestHarness.create(tmp_path, cas, principal_id="builder")
    draft = harness.build_draft(compression_class="P0_EXACT")
    permit = harness.store.issue_publication_permit(
        draft.capsule,
        draft._validated_atoms,
        harness.principal,
        loader_attestation=draft._loader_attestation,
    )
    changed = _with_current_digest(
        draft.capsule.model_copy(
            update={
                "control_manifest": draft.capsule.control_manifest.model_copy(
                    update={"version": "2.3.1"}
                )
            }
        )
    )
    with pytest.raises(
        PublicationIntegrityError,
        match="M3 trust permit capsule_digest does not match publication",
    ):
        Registry(
            tmp_path / "p0-registry.sqlite3",
            cas,
            resolver=_AllowPolicy(),
            trust_root=harness.authority.trust_root(),
        ).publish(changed, harness.principal, publication_permit=permit)


def test_publish_draft_rejects_unpromoted_draft_even_with_loader_shape(
    tmp_path: Path,
) -> None:
    authority, store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    forged = DraftCapsule(
        capsule=draft.capsule,
        atom_ids=draft.atom_ids,
        package_path=draft.package_path,
        validation_pipeline=draft.validation_pipeline,
        _loader_receipt=draft._loader_receipt,
    )
    # The receipt alone must not be enough; the draft must retain the store-issued
    # validation context used to issue a final publication permit.
    with pytest.raises(BuildError, match="quarantine"):
        publish_draft(forged, principal, _registry(tmp_path, authority))
    assert store.pending(_candidate.candidate_id) is False


def test_publish_draft_rejects_non_registry_publication_sink(tmp_path: Path) -> None:
    _authority, _store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    with pytest.raises((TypeError, BuildError), match="Registry|registry"):
        publish_draft(draft, principal, _FakeRegistry())  # type: ignore[arg-type]


def test_publish_draft_requires_loader_attestation_not_a_copyable_receipt(
    tmp_path: Path,
) -> None:
    authority, store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    forged = DraftCapsule(
        capsule=draft.capsule,
        atom_ids=draft.atom_ids,
        package_path=draft.package_path,
        validation_pipeline=draft.validation_pipeline,
        _loader_receipt=draft._loader_receipt,
        _quarantine=store,
        _validated_atoms=draft._validated_atoms,
    )
    with pytest.raises(BuildError, match="attestation"):
        publish_draft(forged, principal, _registry(tmp_path, authority))


def test_forged_loader_receipt_cannot_mint_attestation_without_loader_pass(
    tmp_path: Path,
) -> None:
    """A constructible receipt must not be enough to mint a loader proof."""

    _authority, store, _principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    capability = store._loader_capability()
    forged_receipt = _LoaderReceipt(
        draft.capsule.control_manifest.content_digest,
        capability,
    )
    with pytest.raises(BuildError, match="receipt|loader|load"):
        _loader_attestation(
            draft.capsule,
            None,
            forged_receipt,
            store._loader_identity,
            capability,
        )


def test_ephemeral_build_retains_loader_package_for_final_revalidation(
    tmp_path: Path,
) -> None:
    """The final Registry gate must have authoritative package bytes to reload."""

    _authority, _store, _principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    assert draft.package_path is not None
    assert draft.package_path.is_dir()


def test_final_publish_rejects_missing_loader_package(
    tmp_path: Path,
) -> None:
    authority, _store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    assert draft.package_path is not None
    shutil.rmtree(draft.package_path)
    with pytest.raises(PublicationIntegrityError, match="loader package|attestation"):
        publish_draft(draft, principal, _registry(tmp_path, authority))


def test_final_publish_rejects_unloaded_detached_signature_variant(
    tmp_path: Path,
) -> None:
    authority, _store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    assert draft.capsule.detached_signature is not None
    changed = draft.capsule.model_copy(
        update={
            "detached_signature": draft.capsule.detached_signature.model_copy(
                update={"value": "base64:bmV3LXNpZ25hdHVyZQ=="}
            )
        }
    )
    forged = replace(draft, capsule=changed)
    with pytest.raises(
        (BuildError, PublicationIntegrityError), match="loader|package|digest"
    ):
        publish_draft(forged, principal, _registry(tmp_path, authority))


def test_build_rejects_secret_in_serialized_signature_envelope(tmp_path: Path) -> None:
    _authority, store, _principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    with pytest.raises(QuarantineError, match="secret"):
        build_capsule(
            BuildRequest(
                atoms=draft._validated_atoms,
                quarantine=store,
                lifecycle="PUBLISHED",
                detached_signature={
                    "algorithm": "m3-test-only",
                    "key_id": "m3-test-key",
                    "value": "test-signature-not-production",
                    "envelope": {"x-note": "api_key=abcdefghijklmnop"},
                },
            )
        )


def test_public_permit_requires_loader_attestation(
    tmp_path: Path,
) -> None:
    _authority, store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    with pytest.raises(QuarantineError, match="loader attestation"):
        store.issue_publication_permit(draft.capsule, draft._validated_atoms, principal)


def test_manual_publication_permit_without_quarantine_issuer_is_rejected(
    tmp_path: Path,
) -> None:
    authority, store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    permit = store.issue_publication_permit(
        draft.capsule,
        draft._validated_atoms,
        principal,
        loader_attestation=draft._loader_attestation,
    )
    forged = PublicationPermit(
        payload=permit.payload,
        signature=permit.signature,
        source_bytes=permit.source_bytes,
        loader_attestation=permit.loader_attestation,
        issuer_capability=object(),
    )
    with pytest.raises(PublicationIntegrityError, match="trust proof"):
        _registry(tmp_path, authority).publish(
            draft.capsule, principal, publication_permit=forged
        )


def test_allow_all_verifier_cannot_be_installed_as_a_trust_root() -> None:
    with pytest.raises((TypeError, QuarantineError), match="trusted|verifier"):
        QuarantineStore(approval_verifier=_AllowAllVerifier())


def test_approval_set_is_part_of_trust_root_identity() -> None:
    first = ApprovalAuthority({"reviewer": b"test-secret"}).trust_root()
    expanded = ApprovalAuthority(
        {"reviewer": b"test-secret", "second-reviewer": b"other-secret"}
    ).trust_root()
    assert first.root_id != expanded.root_id


def test_subclassed_verifier_cannot_cross_quarantine_composition_boundary() -> None:
    with pytest.raises(TypeError, match="trust-root verifier"):
        QuarantineStore(approval_verifier=_ForgedVerifier({}, "trusted-human-review"))


def test_final_gate_rejects_unknown_secret_scanner_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    import contractcapsule.audit.quarantine as quarantine_module

    monkeypatch.setattr(quarantine_module, "SECRET_SCANNER_VERSION", "unknown-v0")
    permit = store.issue_publication_permit(
        draft.capsule,
        draft._validated_atoms,
        principal,
        loader_attestation=draft._loader_attestation,
    )
    with pytest.raises(PublicationIntegrityError, match="scanner"):
        _registry(tmp_path, authority).publish(
            draft.capsule, principal, publication_permit=permit
        )


def test_final_gate_rechecks_approval_is_external_to_source_principal(
    tmp_path: Path,
) -> None:
    authority, store, principal, snapshot, _candidate, draft = _m3_fixture(tmp_path)
    store._snapshots[snapshot.snapshot_id] = replace(
        snapshot, principal_id=draft._validated_atoms[0].approval.approver_id
    )
    permit = store.issue_publication_permit(
        draft.capsule,
        draft._validated_atoms,
        principal,
        loader_attestation=draft._loader_attestation,
    )
    with pytest.raises(PublicationIntegrityError, match="external|approval"):
        _registry(tmp_path, authority).publish(
            draft.capsule, principal, publication_permit=permit
        )


def test_default_quarantine_store_cannot_be_replaced_twice(tmp_path: Path) -> None:
    script = """
from contractcapsule.audit.quarantine import ApprovalAuthority, QuarantineStore, configure_default_store
authority = ApprovalAuthority({'reviewer': b'secret'})
try:
    configure_default_store(QuarantineStore(trust_root=authority.trust_root()))
except Exception as error:
    assert 'trusted startup' in str(error) or 'explicit' in str(error)
else:
    raise AssertionError('public caller configured the default store')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={"PYTHONPATH": str(Path(__file__).parents[2] / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_default_quarantine_store_cannot_be_initialized_by_public_caller(
    tmp_path: Path,
) -> None:
    script = """
from contractcapsule.audit.quarantine import ApprovalAuthority, QuarantineStore, configure_default_store
authority = ApprovalAuthority({'reviewer': b'secret'})
try:
    configure_default_store(QuarantineStore(trust_root=authority.trust_root()))
except Exception as error:
    assert 'trusted startup' in str(error) or 'explicit' in str(error)
else:
    raise AssertionError('public caller initialized the default trust store')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={"PYTHONPATH": str(Path(__file__).parents[2] / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_git_source_proof_requires_verified_repository_root(tmp_path: Path) -> None:
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    store = QuarantineStore(trust_root=authority.trust_root())
    snapshot = SourceSnapshot(
        snapshot_id="snapshot-forged",
        content=b"The service MUST use TLS.\n",
        content_digest="sha256:"
        + hashlib.sha256(b"The service MUST use TLS.\n").hexdigest(),
        mode="GIT_IMMUTABLE",
        media_type="text/plain",
        captured_at="2026-01-01T00:00:00Z",
        principal_id="builder",
        relative_path="policy.md",
        path=tmp_path / "policy.md",
        repository_root=None,
        repository="https://example.invalid/project",
        revision="sha1:" + "a" * 40,
        parser_kind="markdown",
        quarantine=store,
    )
    with pytest.raises(
        QuarantineError, match="repository root|collector capability|source path"
    ):
        store._issue_deterministic_source_proof(
            snapshot, store._deterministic_source_token
        )


def test_generated_false_external_source_remains_t3(tmp_path: Path) -> None:
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    trust_root_factory = getattr(authority, "trust_root", None)
    store = (
        QuarantineStore(trust_root=trust_root_factory())
        if trust_root_factory is not None
        else QuarantineStore(approval_verifier=authority.verifier())
    )
    snapshot = snapshot_source(
        SourceInput(
            mode="EXTERNAL_IMMUTABLE",
            content=b"The service MUST use TLS.\n",
            uri="https://example.invalid/policy",
            source="fixture",
            verification_method="checksum",
            quarantine=store,
            generated=False,
        ),
        Principal("builder"),
    )
    candidate = extract_candidate_atoms(snapshot)[0]
    assert candidate.trust_level == TrustLevel.T3
    assert candidate.status == "candidate"


def test_generated_false_caller_cas_source_remains_t3(tmp_path: Path) -> None:
    path = tmp_path / "claimed-deterministic.md"
    path.write_text("The service MUST use TLS.\n", encoding="utf-8")
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    store = QuarantineStore(trust_root=authority.trust_root())
    snapshot = snapshot_source(
        SourceInput(
            path=path,
            mode="CAS",
            quarantine=store,
            generated=False,
        ),
        Principal("builder"),
    )
    candidate = extract_candidate_atoms(snapshot)[0]
    assert candidate.trust_level == TrustLevel.T3
    assert candidate.status == "candidate"


def test_uncomposed_git_source_cannot_self_promote_to_t2(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    for args in (
        ("init", "-q"),
        ("config", "user.email", "test@example.invalid"),
        ("config", "user.name", "M3 test"),
        ("remote", "add", "origin", "https://example.invalid/project"),
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    source_path = root / "policy.md"
    source_path.write_text("# Policy\nThe service MUST use TLS.\n", encoding="utf-8")
    subprocess.run(["git", "add", "policy.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True)
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    store = QuarantineStore()
    snapshot = snapshot_source(
        SourceInput(
            path=source_path,
            mode="GIT_IMMUTABLE",
            repository="https://example.invalid/project",
            revision=f"sha1:{revision}",
            repository_root=root,
            quarantine=store,
            generated=False,
        ),
        Principal("builder"),
    )
    candidate = extract_candidate_atoms(snapshot)[0]
    assert candidate.trust_level == TrustLevel.T3
    assert candidate.status == "candidate"


def test_generated_false_git_input_needs_trusted_collector_for_t2(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    for args in (
        ("init", "-q"),
        ("config", "user.email", "test@example.invalid"),
        ("config", "user.name", "M3 test"),
        ("remote", "add", "origin", "https://example.invalid/project"),
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    source_path = root / "policy.md"
    source_path.write_text("# Policy\nThe service MUST use TLS.\n", encoding="utf-8")
    subprocess.run(["git", "add", "policy.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True)
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    store = QuarantineStore(trust_root=authority.trust_root())
    snapshot = snapshot_source(
        SourceInput(
            path=source_path,
            mode="GIT_IMMUTABLE",
            repository="https://example.invalid/project",
            revision=f"sha1:{revision}",
            repository_root=root,
            quarantine=store,
            generated=False,
        ),
        Principal("builder"),
    )
    candidate = extract_candidate_atoms(snapshot)[0]
    assert candidate.trust_level == TrustLevel.T3
    assert candidate.status == "candidate"


def test_snapshot_identity_cannot_be_rebound_to_another_principal(
    tmp_path: Path,
) -> None:
    path = tmp_path / "policy.md"
    path.write_text("# Policy\nThe service MUST use TLS.\n", encoding="utf-8")
    store = QuarantineStore()
    source = SourceInput(path=path, mode="CAS", quarantine=store)
    snapshot_source(source, Principal("first-builder"))
    with pytest.raises(QuarantineError, match="identity collision|principal"):
        snapshot_source(source, Principal("second-builder"))


def test_final_registry_reloads_unchanged_authoritative_git_object(
    tmp_path: Path,
) -> None:
    authority, store, principal, _repository_root, draft = _m3_git_fixture(tmp_path)
    permit = store.issue_publication_permit(
        draft.capsule,
        draft._validated_atoms,
        principal,
        loader_attestation=draft._loader_attestation,
    )
    published = _registry(tmp_path, authority).publish(
        draft.capsule, principal, publication_permit=permit
    )
    assert published.registry_status == "PUBLISHED"


def test_final_registry_rejects_authoritative_git_identity_drift_after_permit(
    tmp_path: Path,
) -> None:
    authority, store, principal, repository_root, draft = _m3_git_fixture(tmp_path)
    permit = store.issue_publication_permit(
        draft.capsule,
        draft._validated_atoms,
        principal,
        loader_attestation=draft._loader_attestation,
    )
    subprocess.run(
        [
            "git",
            "config",
            "remote.origin.url",
            "https://example.invalid/different-project",
        ],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )

    with pytest.raises(
        PublicationIntegrityError,
        match="M3 authoritative source revalidation failed",
    ):
        _registry(tmp_path, authority).publish(
            draft.capsule, principal, publication_permit=permit
        )


def test_final_publish_rejects_candidate_content_change_with_old_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    issue = getattr(store, "issue_publication_permit", None)
    assert issue is not None, "M3 trust permit API is required"
    permit = issue(
        draft.capsule,
        draft._validated_atoms,
        principal,
        loader_attestation=draft._loader_attestation,
    )
    changed = _with_current_digest(
        draft.capsule.model_copy(
            update={
                "semantic_payload": draft.capsule.semantic_payload.model_copy(
                    update={
                        "atoms": (
                            draft.capsule.semantic_payload.atoms[0].model_copy(
                                update={"statement": "Changed after approval"}
                            ),
                        )
                    }
                )
            }
        )
    )
    _assert_old_permit_rejected_at_final_gate(
        _registry(tmp_path, authority), changed, principal, permit, monkeypatch
    )


def test_final_publish_rejects_evidence_replacement_with_old_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    issue = getattr(store, "issue_publication_permit", None)
    assert issue is not None, "M3 trust permit API is required"
    permit = issue(
        draft.capsule,
        draft._validated_atoms,
        principal,
        loader_attestation=draft._loader_attestation,
    )
    record = draft.capsule.evidence_plane.records[0]
    changed_record = record.model_copy(update={"retention": "replacement-retention"})
    changed = _with_current_digest(
        draft.capsule.model_copy(
            update={
                "evidence_plane": draft.capsule.evidence_plane.model_copy(
                    update={"records": (changed_record,)}
                )
            }
        )
    )
    _assert_old_permit_rejected_at_final_gate(
        _registry(tmp_path, authority), changed, principal, permit, monkeypatch
    )


def test_final_publish_rejects_detached_signature_change_with_old_loader_proof(
    tmp_path: Path,
) -> None:
    """Loader proof must cover immutable publication fields outside CCS identity."""

    authority, store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    permit = store.issue_publication_permit(
        draft.capsule,
        draft._validated_atoms,
        principal,
        loader_attestation=draft._loader_attestation,
    )
    assert draft.capsule.detached_signature is not None
    changed_signature = draft.capsule.detached_signature.model_copy(
        update={"value": "different-signature-envelope"}
    )
    changed = draft.capsule.model_copy(update={"detached_signature": changed_signature})
    # Detached signatures are intentionally excluded from CCS canonical identity, so
    # this is the exact edge case that the loader publication projection must bind.
    assert canonical_digest(changed) == canonical_digest(draft.capsule)
    with pytest.raises(
        PublicationIntegrityError,
        match="loader|publication|projection|attestation",
    ):
        _registry(tmp_path, authority).publish(
            changed, principal, publication_permit=permit
        )


def test_final_publish_rejects_false_trust_level_even_with_new_permit(
    tmp_path: Path,
) -> None:
    _authority, store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    atom = draft.capsule.semantic_payload.atoms[0]
    extensions = dict(atom.extensions)
    trust = dict(extensions["x-trust"])
    trust["level"] = "T0"
    extensions["x-trust"] = trust
    altered_payload = draft.capsule.semantic_payload.model_copy(
        update={"atoms": (atom.model_copy(update={"extensions": extensions}),)}
    )
    zero_manifest = draft.capsule.control_manifest.model_copy(
        update={"content_digest": "sha256:" + "0" * 64}
    )
    altered = draft.capsule.model_copy(
        update={"control_manifest": zero_manifest, "semantic_payload": altered_payload}
    )
    altered = altered.model_copy(
        update={
            "control_manifest": zero_manifest.model_copy(
                update={"content_digest": canonical_digest(altered)}
            )
        }
    )
    with pytest.raises(QuarantineError, match="loader attestation"):
        store.issue_publication_permit(
            altered,
            draft._validated_atoms,
            principal,
            loader_attestation=draft._loader_attestation,
        )


def test_final_publish_rejects_expired_approval_after_build(
    tmp_path: Path,
) -> None:
    authority, store, principal, _snapshot, _candidate, draft = _m3_fixture(
        tmp_path,
        expires_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    issue = getattr(store, "issue_publication_permit", None)
    assert issue is not None, "M3 trust permit API is required"
    permit = issue(
        draft.capsule,
        draft._validated_atoms,
        principal,
        loader_attestation=draft._loader_attestation,
    )
    time.sleep(1.1)
    # An approval that expires between build and publish must be checked again.
    with pytest.raises(PublicationIntegrityError, match="expired|approval|trust"):
        _registry(tmp_path, authority).publish(
            draft.capsule, principal, publication_permit=permit
        )


def test_final_publish_rejects_capsule_or_version_replay_of_old_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    issue = getattr(store, "issue_publication_permit", None)
    assert issue is not None, "M3 trust permit API is required"
    permit = issue(
        draft.capsule,
        draft._validated_atoms,
        principal,
        loader_attestation=draft._loader_attestation,
    )
    changed = _with_current_digest(
        draft.capsule.model_copy(
            update={
                "control_manifest": draft.capsule.control_manifest.model_copy(
                    update={"version": "0.2.0"}
                )
            }
        )
    )
    _assert_old_permit_rejected_at_final_gate(
        _registry(tmp_path, authority), changed, principal, permit, monkeypatch
    )


def test_secret_scanner_failure_at_final_publish_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    issue = getattr(store, "issue_publication_permit", None)
    assert issue is not None, "M3 trust permit API is required"
    permit = issue(
        draft.capsule,
        draft._validated_atoms,
        principal,
        loader_attestation=draft._loader_attestation,
    )

    def unavailable(_data: bytes | str) -> None:
        raise RuntimeError("scanner unavailable")

    monkeypatch.setattr("contractcapsule.audit.quarantine.scan_secrets", unavailable)
    with pytest.raises(PublicationIntegrityError, match="secret|scan|trust"):
        _registry(tmp_path, authority).publish(
            draft.capsule, principal, publication_permit=permit
        )


def test_direct_validated_atom_construction_cannot_create_publish_permit(
    tmp_path: Path,
) -> None:
    _authority, store, principal, _snapshot, candidate, _draft = _m3_fixture(tmp_path)
    with pytest.raises((TypeError, QuarantineError)):
        store.issue_publication_permit(candidate, (), principal)  # type: ignore[arg-type]


def test_valid_m3_build_publish_path_uses_registry_trust_root(tmp_path: Path) -> None:
    authority, _store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    registry = _registry(tmp_path, authority)
    published = publish_draft(draft, principal, registry)
    assert published.registry_status == "PUBLISHED"
    assert (
        registry.get(
            published.capsule.control_manifest.capsule_id,
            published.capsule.control_manifest.version,
            principal,
        )
        == published
    )


def test_m3_attestation_denormalized_principal_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    authority, _store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    registry = _registry(tmp_path, authority)
    published = publish_draft(draft, principal, registry)
    with sqlite3.connect(registry.database_path) as connection:
        connection.execute(
            "UPDATE m3_trust_attestations SET principal_id = ?",
            ("attacker",),
        )
    with pytest.raises(PublicationIntegrityError, match="attestation|principal"):
        registry.get(
            published.capsule.control_manifest.capsule_id,
            published.capsule.control_manifest.version,
            principal,
        )


def test_m3_attestation_rejects_persisted_detached_signature_tamper(
    tmp_path: Path,
) -> None:
    authority, _store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    registry = _registry(tmp_path, authority)
    published = publish_draft(draft, principal, registry)
    tampered_signature = {
        "algorithm": "m3-test-only",
        "key_id": "m3-test-key",
        "value": "tampered-after-publication",
        "envelope": {"x-purpose": "trust-gate-remediation"},
    }
    with sqlite3.connect(registry.database_path) as connection:
        connection.execute(
            "UPDATE publications SET detached_signature_jcs = ?",
            (canonical_json_bytes(tampered_signature).decode("utf-8"),),
        )

    with pytest.raises(
        PublicationIntegrityError,
        match="attestation|publication|projection",
    ):
        registry.get(
            published.capsule.control_manifest.capsule_id,
            published.capsule.control_manifest.version,
            principal,
        )


def test_m3_attestation_all_trust_bindings_are_immutable(tmp_path: Path) -> None:
    authority, _store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    registry = _registry(tmp_path, authority)
    published = publish_draft(draft, principal, registry)
    with sqlite3.connect(registry.database_path) as connection:
        row = connection.execute(
            "SELECT permit_payload_jcs, source_subjects_jcs FROM m3_trust_attestations"
        ).fetchone()
    assert row is not None
    original_payload, original_subjects = row

    def assert_payload_tamper_rejected(payload: dict[str, object]) -> None:
        with sqlite3.connect(registry.database_path) as connection:
            connection.execute(
                "UPDATE m3_trust_attestations SET permit_payload_jcs = ?",
                (canonical_json_bytes(payload).decode("utf-8"),),
            )
        with pytest.raises(PublicationIntegrityError, match="attestation|signature"):
            registry.get(
                published.capsule.control_manifest.capsule_id,
                published.capsule.control_manifest.version,
                principal,
            )
        with sqlite3.connect(registry.database_path) as connection:
            connection.execute(
                "UPDATE m3_trust_attestations SET permit_payload_jcs = ?",
                (original_payload,),
            )

    mutations = (
        ("capsule_id", lambda value: value.__setitem__("capsule_id", "tampered")),
        (
            "candidate",
            lambda value: value["atoms"][0].__setitem__("statement", "tampered"),
        ),
        (
            "evidence",
            lambda value: value["atoms"][0]["bindings"][0].__setitem__(
                "content_digest", "sha256:" + "0" * 64
            ),
        ),
        (
            "approval",
            lambda value: value["atoms"][0]["approval"].__setitem__(
                "decision", "reject"
            ),
        ),
        (
            "source",
            lambda value: value["source_subjects"][0].__setitem__(
                "snapshot_id", "tampered"
            ),
        ),
        (
            "policy",
            lambda value: value.__setitem__("policy_version", "tampered"),
        ),
        (
            "verifier",
            lambda value: value.__setitem__("trust_root_id", "tampered"),
        ),
        (
            "scanner",
            lambda value: value.__setitem__("scanner_version", "tampered"),
        ),
    )
    for _label, mutate in mutations:
        payload = json.loads(original_payload)
        mutate(payload)
        assert_payload_tamper_rejected(payload)

    subjects = json.loads(original_subjects)
    subjects[0]["binding_id"] = "tampered"
    with sqlite3.connect(registry.database_path) as connection:
        connection.execute(
            "UPDATE m3_trust_attestations SET source_subjects_jcs = ?",
            (canonical_json_bytes(subjects).decode("utf-8"),),
        )
    with pytest.raises(PublicationIntegrityError, match="source subject|attestation"):
        registry.get(
            published.capsule.control_manifest.capsule_id,
            published.capsule.control_manifest.version,
            principal,
        )


def test_generated_candidate_with_evidence_and_human_approval_can_publish(
    tmp_path: Path,
) -> None:
    authority, _store, principal, _snapshot, _candidate, draft = _m3_fixture(tmp_path)
    published = publish_draft(draft, principal, _registry(tmp_path, authority))
    assert published.capsule.semantic_payload.atoms[0].status == "validated"
    assert (
        published.capsule.semantic_payload.atoms[0].compression_class == "P1_STRUCTURED"
    )
