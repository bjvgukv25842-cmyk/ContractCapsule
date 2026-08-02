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
from tests.m2_helpers import CAS_BYTES, capsule_with_digest, sample_capsule_data


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


def setup_registry(tmp_path: Path) -> tuple[Registry, FilesystemCAS, StubResolver]:
    resolver = StubResolver()
    resolver.grant("publisher", "publish")
    resolver.grant("reader", "read")
    cas = FilesystemCAS(tmp_path / "cas")
    cas.put_blob(CAS_BYTES, "text/plain")
    registry = Registry(tmp_path / "registry.sqlite3", cas, resolver)
    return registry, cas, resolver


def test_default_resolver_denies_all() -> None:
    decision = DefaultDenyPolicyResolver().resolve(
        Principal("any"), "read", "authority", {"repositories": []}
    )
    assert decision == PolicyDecision.deny()


def test_first_publish_and_restart_get_preserve_immutable_fields(tmp_path: Path) -> None:
    registry, cas, resolver = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    published = registry.publish(capsule, Principal("publisher"))
    assert canonical_digest(published.capsule) == canonical_digest(capsule)
    assert published.capsule.detached_signature == capsule.detached_signature
    assert not published.capsule.derived_artifacts
    assert not published.capsule.runtime_sidecar
    assert published.registry_status == "PUBLISHED"

    restarted = Registry(tmp_path / "registry.sqlite3", cas, resolver)
    loaded = restarted.get(
        capsule.control_manifest.capsule_id,
        capsule.control_manifest.version,
        Principal("reader"),
    )
    assert loaded == published
    assert loaded.capsule.control_manifest.lifecycle == "PUBLISHED"


def test_exact_republish_is_idempotent_without_timestamp_or_row_changes(tmp_path: Path) -> None:
    registry, _, _ = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    first = registry.publish(capsule, Principal("publisher"))
    counts_before = registry._table_counts()
    second = registry.publish(capsule, Principal("publisher"))
    assert second == first
    assert second.published_at == first.published_at
    assert registry._table_counts() == counts_before


def test_same_id_version_different_digest_is_rejected_and_original_survives(
    tmp_path: Path,
) -> None:
    registry, _, _ = setup_registry(tmp_path)
    original = capsule_with_digest()
    registry.publish(original, Principal("publisher"))
    changed_data = sample_capsule_data()
    changed_data["semantic_payload"]["atoms"][0]["statement"] = "different"
    changed = capsule_with_digest(changed_data)
    with pytest.raises(VersionConflict):
        registry.publish(changed, Principal("publisher"))
    assert registry.get(
        original.control_manifest.capsule_id,
        original.control_manifest.version,
        Principal("reader"),
    ).capsule.control_manifest.content_digest == original.control_manifest.content_digest


def test_same_digest_different_detached_envelope_is_not_idempotent(tmp_path: Path) -> None:
    registry, _, _ = setup_registry(tmp_path)
    original = capsule_with_digest()
    registry.publish(original, Principal("publisher"))
    changed = original.model_copy(
        update={
            "detached_signature": original.detached_signature.model_copy(
                update={"value": "base64:AQ=="}
            )
        }
    )
    with pytest.raises(PublicationConflict):
        registry.publish(changed, Principal("publisher"))


def test_publish_revalidates_model_copy_that_bypassed_nested_invariants(
    tmp_path: Path,
) -> None:
    registry, _, _ = setup_registry(tmp_path)
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
    registry, _, _ = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    registry.publish(capsule, Principal("publisher"))
    with pytest.raises(RegistryAuthorizationError) as existing:
        registry.publish(capsule, Principal("unknown"))

    absent_data = sample_capsule_data()
    absent_data["control_manifest"]["capsule_id"] = "com.example.absent"
    absent = capsule_with_digest(absent_data)
    with pytest.raises(RegistryAuthorizationError) as missing:
        registry.publish(absent, Principal("unknown"))
    assert str(existing.value) == str(missing.value)


def test_access_policy_can_only_narrow_resolver_permission(tmp_path: Path) -> None:
    registry, _, resolver = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    resolver.grant("restricted-publisher", "publish", policies=frozenset())
    with pytest.raises(RegistryAuthorizationError):
        registry.publish(capsule, Principal("restricted-publisher"))


def test_malformed_policy_resolver_decision_fails_closed(tmp_path: Path) -> None:
    registry, cas, _ = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    registry.publish(capsule, Principal("publisher"))
    malformed = Registry(registry.database_path, cas, MalformedResolver())
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
    registry, cas, _ = setup_registry(tmp_path)
    orphan = cas.put_blob(b"orphan", "text/plain")
    with pytest.raises(BlobAuthorizationError):
        registry.get_blob(orphan.digest, Principal("reader"))


def test_published_blob_read_uses_grant_and_revalidates_tamper(tmp_path: Path) -> None:
    registry, cas, _ = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    registry.publish(capsule, Principal("publisher"))
    digest = capsule.evidence_plane.records[0].content_digest
    assert registry.get_blob(digest, Principal("reader")) == CAS_BYTES
    path = cas.object_path(digest)
    path.chmod(0o644)
    path.write_bytes(b"tampered")
    with pytest.raises(BlobIntegrityError):
        registry.get_blob(digest, Principal("reader"))


def test_registry_rejects_cas_media_type_header_tamper(tmp_path: Path) -> None:
    registry, cas, _ = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    registry.publish(capsule, Principal("publisher"))
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
    registry, _, resolver = setup_registry(tmp_path)
    first = capsule_with_digest()
    registry.publish(first, Principal("publisher"))

    second_data = sample_capsule_data()
    second_data["control_manifest"]["capsule_id"] = "com.example.second"
    second_data["control_manifest"]["authority"] = "other-authority"
    second_data["semantic_payload"]["atoms"][0]["authority"] = "other-authority"
    second = capsule_with_digest(second_data)
    resolver.grant("publisher", "publish", "other-authority")
    resolver.grant("other-reader", "read", "other-authority")
    registry.publish(second, Principal("publisher"))

    digest = first.evidence_plane.records[0].content_digest
    assert registry.get_blob(digest, Principal("reader")) == CAS_BYTES
    assert registry.get_blob(digest, Principal("other-reader")) == CAS_BYTES
    with pytest.raises(BlobAuthorizationError):
        registry.get_blob(digest, Principal("unknown"))


def test_transaction_failure_rolls_back_publication_references_and_grants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, _, _ = setup_registry(tmp_path)
    capsule = capsule_with_digest()

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected grant failure")

    monkeypatch.setattr(registry, "_insert_grants", fail)
    with pytest.raises(RuntimeError, match="injected"):
        registry.publish(capsule, Principal("publisher"))
    assert registry._table_counts() == {
        "publications": 0,
        "evidence_references": 0,
        "digest_grants": 0,
    }


def test_cas_integrity_failure_inside_publish_leaves_no_registry_rows(
    tmp_path: Path,
) -> None:
    registry, cas, _ = setup_registry(tmp_path)
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
    registry, _, _ = setup_registry(tmp_path)
    data = sample_capsule_data()
    data["control_manifest"]["lifecycle"] = "VALIDATED"
    capsule = capsule_with_digest(data)
    with pytest.raises(PublicationIntegrityError, match="PUBLISHED lifecycle"):
        registry.publish(capsule, Principal("publisher"))
    assert capsule.control_manifest.lifecycle == "VALIDATED"
    assert registry._table_counts()["publications"] == 0


def test_registry_detects_missing_reference_row_instead_of_repairing_it(tmp_path: Path) -> None:
    registry, _, _ = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    registry.publish(capsule, Principal("publisher"))
    with sqlite3.connect(registry.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM digest_grants")
    with pytest.raises(PublicationIntegrityError):
        registry.publish(capsule, Principal("publisher"))


def test_registry_get_missing_and_unauthorized_are_both_non_disclosing(tmp_path: Path) -> None:
    registry, _, _ = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    registry.publish(capsule, Principal("publisher"))
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
    registry, _, resolver = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    registry.publish(capsule, Principal("publisher"))
    resolver.grant("narrow-reader", "read", policies=frozenset())
    digest = capsule.evidence_plane.records[0].content_digest
    with pytest.raises(BlobAuthorizationError):
        registry.get_blob(digest, Principal("narrow-reader"))


def test_tampered_grant_cannot_authorize_an_unreferenced_cas_object(tmp_path: Path) -> None:
    registry, cas, _ = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    registry.publish(capsule, Principal("publisher"))
    orphan = cas.put_blob(b"other secret", "text/plain")
    with sqlite3.connect(registry.database_path) as connection:
        connection.execute("UPDATE digest_grants SET digest = ?", (orphan.digest,))
    with pytest.raises(BlobAuthorizationError):
        registry.get_blob(orphan.digest, Principal("reader"))


def test_unauthorized_get_does_not_expose_corrupt_existing_record(tmp_path: Path) -> None:
    registry, _, _ = setup_registry(tmp_path)
    capsule = capsule_with_digest()
    registry.publish(capsule, Principal("publisher"))
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
