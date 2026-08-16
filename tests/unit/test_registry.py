from __future__ import annotations

import inspect
import json
import sqlite3
import struct
from pathlib import Path

import pytest

from contractcapsule.models import Principal
from contractcapsule.models.canonical import canonical_digest, canonical_json_bytes
from contractcapsule.storage.cas import (
    BlobAuthorizationError,
    BlobIntegrityError,
    FilesystemCAS,
)
from contractcapsule.storage.registry import (
    DefaultDenyPolicyResolver,
    PolicyDecision,
    PublicationConflict,
    PublicationIntegrityError,
    Registry,
    RegistryAuthorizationError,
    RegistryNotFound,
    VersionConflict,
)
from tests.m2_helpers import (
    CAS_BYTES,
    TrustedM3TestHarness,
    capsule_with_digest,
    sample_capsule_data,
)


class StubResolver:
    def __init__(self) -> None:
        self.permissions: dict[tuple[str, str, str], PolicyDecision] = {}

    def grant(
        self,
        principal: str,
        action: str,
        authority: str = "approved-project-policy",
        policies: frozenset[str] = frozenset({"team-auth"}),
    ) -> None:
        self.permissions[(principal, action, authority)] = PolicyDecision(
            allowed=True, allowed_access_policies=policies
        )

    def resolve(
        self,
        principal: Principal,
        action: str,
        authority: str,
        scope: object,
    ) -> PolicyDecision:
        del scope
        return self.permissions.get(
            (principal.principal_id, action, authority), PolicyDecision.deny()
        )


class MalformedResolver:
    def resolve(
        self,
        principal: Principal,
        action: str,
        authority: str,
        scope: object,
    ) -> PolicyDecision:
        del principal, action, authority, scope
        return PolicyDecision(
            allowed=1,  # type: ignore[arg-type]
            allowed_access_policies="team-auth",  # type: ignore[arg-type]
        )


def setup_registry(
    tmp_path: Path,
) -> tuple[Registry, FilesystemCAS, StubResolver, TrustedM3TestHarness]:
    resolver = StubResolver()
    resolver.grant("publisher", "publish")
    resolver.grant("reader", "read")
    cas = FilesystemCAS(tmp_path / "cas")
    cas.put_blob(CAS_BYTES, "text/plain")
    harness = TrustedM3TestHarness.create(tmp_path, cas)
    registry = Registry(
        tmp_path / "registry.sqlite3",
        cas,
        resolver,
        trust_root=harness.authority.trust_root(),
    )
    return registry, cas, resolver, harness


def test_default_resolver_denies_all() -> None:
    decision = DefaultDenyPolicyResolver().resolve(
        Principal("any"), "read", "authority", {"repositories": []}
    )
    assert decision == PolicyDecision.deny()


def test_first_publish_and_restart_get_preserve_immutable_fields(tmp_path: Path) -> None:
    registry, cas, resolver, harness = setup_registry(tmp_path)
    draft = harness.build_draft()
    capsule = draft.capsule
    published = harness.publish(draft, registry)
    assert canonical_digest(published.capsule) == canonical_digest(capsule)
    assert published.capsule.detached_signature == capsule.detached_signature
    assert not published.capsule.derived_artifacts
    assert not published.capsule.runtime_sidecar
    assert published.registry_status == "PUBLISHED"

    restarted = Registry(
        tmp_path / "registry.sqlite3",
        cas,
        resolver,
        trust_root=harness.authority.trust_root(),
    )
    loaded = restarted.get(
        capsule.control_manifest.capsule_id,
        capsule.control_manifest.version,
        Principal("reader"),
    )
    assert loaded == published
    assert loaded.capsule.control_manifest.lifecycle == "PUBLISHED"


def test_exact_republish_is_idempotent_without_timestamp_or_row_changes(tmp_path: Path) -> None:
    registry, _, _, harness = setup_registry(tmp_path)
    draft = harness.build_draft()
    first = harness.publish(draft, registry)
    counts_before = registry._table_counts()
    second = harness.publish(draft, registry)
    assert second == first
    assert second.published_at == first.published_at
    assert registry._table_counts() == counts_before


def test_same_id_version_different_digest_is_rejected_and_original_survives(
    tmp_path: Path,
) -> None:
    registry, _, _, harness = setup_registry(tmp_path)
    original_draft = harness.build_draft()
    original = original_draft.capsule
    harness.publish(original_draft, registry)
    changed_draft = harness.build_draft(source_bytes=b"different\n")
    with pytest.raises(VersionConflict):
        harness.publish(changed_draft, registry)
    assert registry.get(
        original.control_manifest.capsule_id,
        original.control_manifest.version,
        Principal("reader"),
    ).capsule.control_manifest.content_digest == original.control_manifest.content_digest


def test_same_digest_different_detached_envelope_is_not_idempotent(tmp_path: Path) -> None:
    registry, _, _, harness = setup_registry(tmp_path)
    validated = harness.promote_source()
    original_draft = harness.build_draft(validated_atom=validated)
    harness.publish(original_draft, registry)
    changed_draft = harness.build_draft(
        validated_atom=validated,
        detached_signature={
            "algorithm": "m3-test-only",
            "key_id": "m3-test-key",
            "value": "changed-test-signature",
            "envelope": {"x-purpose": "M2 test-contract migration"},
        },
    )
    assert (
        changed_draft.capsule.control_manifest.content_digest
        == original_draft.capsule.control_manifest.content_digest
    )
    with pytest.raises(PublicationConflict):
        harness.publish(changed_draft, registry)


def test_publish_revalidates_model_copy_that_bypassed_nested_invariants(
    tmp_path: Path,
) -> None:
    registry, _, _, _ = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    bypassed = capsule.model_copy(
        update={
            "detached_signature": capsule.detached_signature.model_copy(
                update={"key_id": "does-not-match-policy"}
            )
        }
    )
    with pytest.raises(PublicationIntegrityError, match="model validation"):
        registry.publish(bypassed, Principal("publisher"))
    assert registry._table_counts()["publications"] == 0


def test_unauthorized_duplicate_publish_does_not_confirm_existence(tmp_path: Path) -> None:
    registry, _, _, harness = setup_registry(tmp_path)
    validated = harness.promote_source()
    existing_draft = harness.build_draft(validated_atom=validated)
    harness.publish(existing_draft, registry)
    with pytest.raises(RegistryAuthorizationError) as existing:
        harness.publish(existing_draft, registry, Principal("unknown"))

    absent_draft = harness.build_draft(
        validated_atom=validated,
        capsule_id="com.example.absent",
    )
    with pytest.raises(RegistryAuthorizationError) as missing:
        harness.publish(absent_draft, registry, Principal("unknown"))
    assert str(existing.value) == str(missing.value)


def test_access_policy_can_only_narrow_resolver_permission(tmp_path: Path) -> None:
    registry, _, resolver, _ = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    resolver.grant("restricted-publisher", "publish", policies=frozenset())
    with pytest.raises(RegistryAuthorizationError):
        registry.publish(capsule, Principal("restricted-publisher"))


def test_malformed_policy_resolver_decision_fails_closed(tmp_path: Path) -> None:
    registry, cas, _, harness = setup_registry(tmp_path)
    draft = harness.build_draft()
    capsule = draft.capsule
    harness.publish(draft, registry)
    malformed = Registry(
        registry.database_path,
        cas,
        MalformedResolver(),
        trust_root=harness.authority.trust_root(),
    )
    digest = capsule.evidence_plane.records[0].content_digest

    with pytest.raises(RegistryNotFound):
        malformed.get(
            capsule.control_manifest.capsule_id,
            capsule.control_manifest.version,
            Principal("reader"),
        )
    with pytest.raises(BlobAuthorizationError):
        malformed.get_blob(digest, Principal("reader"))


def test_orphan_blob_and_unpublished_reference_are_not_readable(tmp_path: Path) -> None:
    registry, cas, _, _ = setup_registry(tmp_path)
    orphan = cas.put_blob(b"orphan", "text/plain")
    with pytest.raises(BlobAuthorizationError):
        registry.get_blob(orphan.digest, Principal("reader"))


def test_published_blob_read_uses_grant_and_revalidates_tamper(tmp_path: Path) -> None:
    registry, cas, _, harness = setup_registry(tmp_path)
    draft = harness.build_draft()
    capsule = draft.capsule
    harness.publish(draft, registry)
    digest = capsule.evidence_plane.records[0].content_digest
    assert registry.get_blob(digest, Principal("reader")) == CAS_BYTES
    path = cas.object_path(digest)
    path.chmod(0o644)
    path.write_bytes(b"tampered")
    with pytest.raises(BlobIntegrityError):
        registry.get_blob(digest, Principal("reader"))


def test_registry_rejects_cas_media_type_header_tamper(tmp_path: Path) -> None:
    registry, cas, _, harness = setup_registry(tmp_path)
    draft = harness.build_draft()
    capsule = draft.capsule
    harness.publish(draft, registry)
    digest = capsule.evidence_plane.records[0].content_digest
    path = cas.object_path(digest)
    raw = path.read_bytes()
    magic_length = len(b"CCS-CAS-1\0")
    (header_length,) = struct.unpack(">I", raw[magic_length : magic_length + 4])
    header_start = magic_length + 4
    header = json.loads(raw[header_start : header_start + header_length])
    header["media_type"] = "application/json"
    changed = canonical_json_bytes(header)
    path.chmod(0o644)
    path.write_bytes(
        raw[:magic_length]
        + struct.pack(">I", len(changed))
        + changed
        + raw[header_start + header_length :]
    )

    with pytest.raises(PublicationIntegrityError, match="media type"):
        registry.get(
            capsule.control_manifest.capsule_id,
            capsule.control_manifest.version,
            Principal("reader"),
        )
    with pytest.raises(BlobIntegrityError, match="media type"):
        registry.get_blob(digest, Principal("reader"))


def test_shared_blob_grants_are_union_of_individually_authorized_publications(
    tmp_path: Path,
) -> None:
    registry, _, resolver, harness = setup_registry(tmp_path)
    validated = harness.promote_source()
    first_draft = harness.build_draft(validated_atom=validated)
    first = first_draft.capsule
    harness.publish(first_draft, registry)

    second_draft = harness.build_draft(
        validated_atom=validated,
        capsule_id="com.example.second",
        authority="other-authority",
    )
    resolver.grant("publisher", "publish", "other-authority")
    resolver.grant("other-reader", "read", "other-authority")
    harness.publish(second_draft, registry)

    digest = first.evidence_plane.records[0].content_digest
    assert registry.get_blob(digest, Principal("reader")) == CAS_BYTES
    assert registry.get_blob(digest, Principal("other-reader")) == CAS_BYTES
    with pytest.raises(BlobAuthorizationError):
        registry.get_blob(digest, Principal("unknown"))


def test_transaction_failure_rolls_back_publication_references_and_grants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, _, _, harness = setup_registry(tmp_path)
    draft = harness.build_draft()

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected grant failure")

    monkeypatch.setattr(registry, "_insert_grants", fail)
    with pytest.raises(RuntimeError, match="injected"):
        harness.publish(draft, registry)
    assert registry._table_counts() == {
        "publications": 0,
        "evidence_references": 0,
        "digest_grants": 0,
    }


def test_cas_integrity_failure_inside_publish_leaves_no_registry_rows(
    tmp_path: Path,
) -> None:
    registry, cas, _, _ = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    cas.object_path(capsule.evidence_plane.records[0].content_digest).unlink()
    with pytest.raises(BlobIntegrityError):
        registry.publish(capsule, Principal("publisher"))
    assert registry._table_counts() == {
        "publications": 0,
        "evidence_references": 0,
        "digest_grants": 0,
    }


def test_publish_does_not_mutate_lifecycle_to_published(tmp_path: Path) -> None:
    registry, _, _, _ = setup_registry(tmp_path)
    data = sample_capsule_data()
    data["control_manifest"]["lifecycle"] = "VALIDATED"
    capsule = capsule_with_digest(data)
    with pytest.raises(PublicationIntegrityError, match="PUBLISHED lifecycle"):
        registry.publish(capsule, Principal("publisher"))
    assert capsule.control_manifest.lifecycle == "VALIDATED"
    assert registry._table_counts()["publications"] == 0


def test_registry_detects_missing_reference_row_instead_of_repairing_it(tmp_path: Path) -> None:
    registry, _, _, harness = setup_registry(tmp_path)
    draft = harness.build_draft()
    harness.publish(draft, registry)
    with sqlite3.connect(registry.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM digest_grants")
    with pytest.raises(PublicationIntegrityError):
        harness.publish(draft, registry)


def test_registry_get_missing_and_unauthorized_are_both_non_disclosing(tmp_path: Path) -> None:
    registry, _, _, harness = setup_registry(tmp_path)
    draft = harness.build_draft()
    capsule = draft.capsule
    harness.publish(draft, registry)
    with pytest.raises(RegistryNotFound) as denied:
        registry.get(
            capsule.control_manifest.capsule_id,
            capsule.control_manifest.version,
            Principal("unknown"),
        )
    with pytest.raises(RegistryNotFound) as absent:
        registry.get("com.example.missing", "1.0.0", Principal("unknown"))
    assert str(denied.value) == str(absent.value)


def test_blob_access_policy_cannot_expand_a_resolver_read_grant(tmp_path: Path) -> None:
    registry, _, resolver, harness = setup_registry(tmp_path)
    draft = harness.build_draft()
    capsule = draft.capsule
    harness.publish(draft, registry)
    resolver.grant("narrow-reader", "read", policies=frozenset())
    digest = capsule.evidence_plane.records[0].content_digest
    with pytest.raises(BlobAuthorizationError):
        registry.get_blob(digest, Principal("narrow-reader"))


def test_tampered_grant_cannot_authorize_an_unreferenced_cas_object(tmp_path: Path) -> None:
    registry, cas, _, harness = setup_registry(tmp_path)
    draft = harness.build_draft()
    harness.publish(draft, registry)
    orphan = cas.put_blob(b"other secret", "text/plain")
    with sqlite3.connect(registry.database_path) as connection:
        connection.execute("UPDATE digest_grants SET digest = ?", (orphan.digest,))
    with pytest.raises(BlobAuthorizationError):
        registry.get_blob(orphan.digest, Principal("reader"))


def test_unauthorized_get_does_not_expose_corrupt_existing_record(tmp_path: Path) -> None:
    registry, _, _, harness = setup_registry(tmp_path)
    draft = harness.build_draft()
    capsule = draft.capsule
    harness.publish(draft, registry)
    with sqlite3.connect(registry.database_path) as connection:
        connection.execute(
            "UPDATE publications SET immutable_record_jcs = ?",
            ("not-json",),
        )
    with pytest.raises(RegistryNotFound, match="unavailable"):
        registry.get(
            capsule.control_manifest.capsule_id,
            capsule.control_manifest.version,
            Principal("unknown"),
        )
    with pytest.raises(PublicationIntegrityError):
        registry.get(
            capsule.control_manifest.capsule_id,
            capsule.control_manifest.version,
            Principal("reader"),
        )


def test_sql_implementation_has_no_replace_or_public_mutation_api() -> None:
    source = inspect.getsource(Registry).upper()
    assert "INSERT OR REPLACE" not in source
    assert "REPLACE INTO" not in source
    assert not hasattr(Registry, "update")
    assert not hasattr(Registry, "delete")
