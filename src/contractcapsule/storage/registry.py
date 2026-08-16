"""Immutable SQLite Registry for published CCS-2.1 capsule versions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from contractcapsule.models import Capsule, Principal
from contractcapsule.models.canonical import (
    canonical_digest,
    canonical_json_bytes,
    capsule_wire_dict,
)
from contractcapsule.storage.cas import (
    BlobAuthorizationError,
    BlobIntegrityError,
    FilesystemCAS,
)


class RegistryError(RuntimeError):
    """Base class for immutable Registry failures."""


class RegistryAuthorizationError(RegistryError):
    """A trusted policy resolver did not authorize publication."""


class RegistryNotFound(RegistryError):
    """Generic non-disclosing result for absent or unreadable versions."""


class VersionConflict(RegistryError):
    """The capsule ID and version already identify a different digest."""


class PublicationConflict(RegistryError):
    """An apparent replay differs in another immutable publication field."""


class PublicationIntegrityError(RegistryError):
    """Stored publication rows no longer form the immutable committed record."""


_M3_LOADER_PROFILE = "CCS-2.1-m3-loader-v1"
_M3_SECRET_SCANNER_VERSION = "m3-secret-scanner-v1"
_M3_LOADER_PIPELINE = (
    "strict-json",
    "json-schema",
    "python-semantics",
    "digest-and-reference-integrity",
    "load_capsule",
)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    allowed_access_policies: frozenset[str]

    @classmethod
    def deny(cls) -> PolicyDecision:
        return cls(False, frozenset())


class PolicyResolver(Protocol):
    def resolve(
        self,
        principal: Principal,
        action: str,
        authority: str,
        scope: object,
    ) -> PolicyDecision: ...


class DefaultDenyPolicyResolver:
    def resolve(
        self,
        principal: Principal,
        action: str,
        authority: str,
        scope: object,
    ) -> PolicyDecision:
        del principal, action, authority, scope
        return PolicyDecision.deny()


@dataclass(frozen=True, slots=True)
class PublishedCapsule:
    capsule: Capsule
    registry_status: str
    published_at: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(clock: Callable[[], datetime]) -> str:
    value = clock().astimezone(UTC).isoformat(timespec="microseconds")
    return value.replace("+00:00", "Z")


def _scope_dict(capsule: Capsule) -> dict[str, Any]:
    scope = capsule.control_manifest.scope
    return {
        "repositories": list(scope.repositories),
        "paths": list(scope.paths),
        "environments": list(scope.environments),
    }


def _signature_dict(capsule: Capsule) -> dict[str, Any] | None:
    signature = capsule.detached_signature
    if signature is None:
        return None
    return {
        "algorithm": signature.algorithm,
        "key_id": signature.key_id,
        "value": signature.value,
        "envelope": dict(signature.envelope),
    }


def _publication_core(capsule: Capsule) -> dict[str, Any]:
    wire = capsule_wire_dict(capsule)
    wire.pop("detached_signature", None)
    wire.pop("derived_artifacts", None)
    wire.pop("runtime_sidecar", None)
    return wire


def _jcs_text(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _is_m3_capsule(capsule: Capsule) -> bool:
    """Return whether the capsule carries explicit M3 provenance metadata.

    The marker is part of the canonical core, so adding or removing it changes
    the digest. Unmarked pre-M3 rows remain readable and exactly replayable, but
    a new P0/P1 publication is gated regardless of this marker.
    """

    manifest_extensions = capsule.control_manifest.extensions
    if (
        manifest_extensions.get("x-builder-profile") == "CCS-2.1-m3-v1"
        or manifest_extensions.get("x-m3-trust-required") is True
    ):
        return True
    for atom in capsule.semantic_payload.atoms:
        if isinstance(atom.extensions.get("x-trust"), Mapping):
            return True
    return False


def _permit_class() -> type[Any] | None:
    """Load the M3 permit type lazily to avoid an import-cycle at startup."""

    try:
        from contractcapsule.audit.quarantine import PublicationPermit
    except (ImportError, AttributeError):
        return None
    return PublicationPermit


def _permit_issuer_class() -> type[Any] | None:
    try:
        from contractcapsule.audit.quarantine import _PublicationIssuer
    except (ImportError, AttributeError):
        return None
    return _PublicationIssuer


def _trust_root_class() -> type[Any] | None:
    try:
        from contractcapsule.audit.quarantine import TrustRoot
    except (ImportError, AttributeError):
        return None
    return TrustRoot


class Registry:
    """Append-only publication registry; it exposes no update or delete API."""

    def __init__(
        self,
        database_path: Path,
        cas: FilesystemCAS,
        resolver: PolicyResolver | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
        trust_root: Any | None = None,
    ) -> None:
        self.database_path = database_path
        self._cas = cas
        self._resolver = resolver or DefaultDenyPolicyResolver()
        self._clock = clock
        # The trust root is fixed when the Registry service is composed.  It is
        # intentionally not accepted by ``publish`` so callers cannot swap the
        # verifier on a per-request basis.
        root_type = _trust_root_class()
        if trust_root is not None and (
            root_type is None or type(trust_root) is not root_type
        ):
            raise TypeError("trust_root must be the sealed TrustRoot implementation")
        self._trust_root = trust_root
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._composition_sealed = True

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_composition_sealed", False) and name in {
            "_resolver",
            "_trust_root",
            "_cas",
            "_clock",
        }:
            raise AttributeError("Registry trust composition is immutable")
        object.__setattr__(self, name, value)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _requires_m3_gate(self, capsule: Capsule) -> bool:
        # Every P0/P1 publication crosses the same M3 trust gate, regardless of
        # whether a caller attempts to strip the builder marker.  The marker is
        # useful provenance, but it is not an authorization switch.
        return _is_m3_capsule(capsule) or any(
            atom.compression_class in {"P0_EXACT", "P1_STRUCTURED"}
            for atom in capsule.semantic_payload.atoms
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS publications (
                    publication_id INTEGER PRIMARY KEY,
                    capsule_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    content_digest TEXT NOT NULL,
                    lifecycle TEXT NOT NULL,
                    authority TEXT NOT NULL,
                    scope_jcs TEXT NOT NULL,
                    immutable_record_jcs TEXT NOT NULL,
                    detached_signature_jcs TEXT,
                    published_at TEXT NOT NULL,
                    UNIQUE (capsule_id, version)
                );
                CREATE TABLE IF NOT EXISTS evidence_references (
                    publication_id INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    evidence_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    content_digest TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    access_policy TEXT NOT NULL,
                    immutable_record_jcs TEXT NOT NULL,
                    PRIMARY KEY (publication_id, evidence_id),
                    UNIQUE (publication_id, ordinal),
                    FOREIGN KEY (publication_id) REFERENCES publications(publication_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS digest_grants (
                    publication_id INTEGER NOT NULL,
                    evidence_id TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    access_policy TEXT NOT NULL,
                    PRIMARY KEY (publication_id, evidence_id, digest),
                    FOREIGN KEY (publication_id, evidence_id)
                        REFERENCES evidence_references(publication_id, evidence_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS m3_trust_attestations (
                    publication_id INTEGER PRIMARY KEY,
                    policy_version TEXT NOT NULL,
                    trust_root_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    permit_payload_jcs TEXT NOT NULL,
                    permit_signature TEXT NOT NULL,
                    source_subjects_jcs TEXT NOT NULL,
                    FOREIGN KEY (publication_id) REFERENCES publications(publication_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                """
            )

    def _decision(
        self, capsule: Capsule, principal: Principal, action: str
    ) -> PolicyDecision:
        return self._decision_for_claims(
            principal,
            action,
            capsule.control_manifest.authority,
            _scope_dict(capsule),
        )

    def _decision_for_claims(
        self,
        principal: Principal,
        action: str,
        authority: str,
        scope: object,
    ) -> PolicyDecision:
        try:
            decision = self._resolver.resolve(
                principal,
                action,
                authority,
                scope,
            )
        except Exception:  # noqa: BLE001 - policy-resolver failures must deny access.
            return PolicyDecision.deny()
        if (
            not isinstance(decision, PolicyDecision)
            or type(decision.allowed) is not bool
            or type(decision.allowed_access_policies) is not frozenset
            or any(
                type(policy) is not str or not policy
                for policy in decision.allowed_access_policies
            )
        ):
            return PolicyDecision.deny()
        return decision

    @staticmethod
    def _access_policies(capsule: Capsule) -> frozenset[str]:
        return frozenset(record.access_policy for record in capsule.evidence_plane.records)

    def _authorize_publish(self, capsule: Capsule, principal: Principal) -> None:
        decision = self._decision(capsule, principal, "publish")
        if not decision.allowed or not self._access_policies(capsule) <= decision.allowed_access_policies:
            raise RegistryAuthorizationError("publication is not authorized")

    def _authorize_read(self, capsule: Capsule, principal: Principal) -> bool:
        decision = self._decision(capsule, principal, "read")
        return decision.allowed and self._access_policies(capsule) <= decision.allowed_access_policies

    @staticmethod
    def _evidence_records(capsule: Capsule) -> list[dict[str, Any]]:
        wire_records = capsule_wire_dict(capsule)["evidence_plane"]["records"]
        return [dict(record) for record in wire_records]

    def _validate_candidate(self, capsule: Capsule) -> None:
        manifest = capsule.control_manifest
        if manifest.lifecycle != "PUBLISHED":
            raise PublicationIntegrityError("publish requires PUBLISHED lifecycle")
        if canonical_digest(capsule) != manifest.content_digest:
            raise PublicationIntegrityError("candidate content digest does not match core")
        for record in capsule.evidence_plane.records:
            if record.mode == "CAS":
                stored = self._cas._read_verified(record.content_digest)
                if stored.ref.media_type != record.media_type:
                    raise PublicationIntegrityError("CAS evidence media type mismatch")

    @staticmethod
    def _permit_payload(permit: Any) -> Mapping[str, Any]:
        payload = getattr(permit, "payload", None)
        if not isinstance(payload, Mapping):
            raise PublicationIntegrityError("trust permit payload is invalid")
        # PublicationPermit stores a recursively frozen mapping (tuples and
        # mapping proxies).  Convert it back to ordinary JSON containers at the
        # Registry boundary so structural checks cannot accidentally reject or
        # accept based on the in-memory representation.
        try:
            from contractcapsule.models.base import thaw_json

            thawed = thaw_json(payload)
        except (TypeError, ValueError) as error:
            raise PublicationIntegrityError("trust permit payload is invalid") from error
        if not isinstance(thawed, Mapping):
            raise PublicationIntegrityError("trust permit payload is invalid")
        return thawed

    def _verify_permit_signature(self, permit: Any) -> Mapping[str, Any]:
        """Verify a sealed permit against this Registry's fixed trust root.

        The concrete permit implementation lives in ``audit.quarantine``.  The
        Registry intentionally accepts only that type and a configured TrustRoot;
        arbitrary caller supplied objects/verifiers are rejected even when they
        expose a permissive ``verify`` method.
        """

        permit_type = _permit_class()
        issuer_type = _permit_issuer_class()
        root_type = _trust_root_class()
        issuer = getattr(permit, "issuer_capability", None)
        if (
            permit_type is None
            or issuer_type is None
            or root_type is None
            or type(permit) is not permit_type
            or type(self._trust_root) is not root_type
            or type(issuer) is not issuer_type
        ):
            raise PublicationIntegrityError("M3 trust proof is unavailable")
        payload = self._permit_payload(permit)
        loader_wire = payload.get("loader_attestation")
        if (
            not isinstance(loader_wire, Mapping)
            or getattr(issuer, "store_id", None) != loader_wire.get("store_id")
        ):
            raise PublicationIntegrityError("M3 trust permit issuer binding is invalid")
        verified = False
        try:
            verify_payload = getattr(self._trust_root, "verify_payload", None)
            signature = getattr(permit, "signature", None)
            if callable(verify_payload) and isinstance(signature, str):
                verified = bool(verify_payload(payload, signature))
        except Exception:  # noqa: BLE001 - trust failures are fail-closed.
            verified = False
        if not verified:
            raise PublicationIntegrityError("M3 trust proof signature is invalid")
        return payload

    def _validate_loader_attestation(
        self, payload: Mapping[str, Any], capsule: Capsule, permit: Any
    ) -> None:
        capsule_digest = capsule.control_manifest.content_digest
        wire = payload.get("loader_attestation")
        if not isinstance(wire, Mapping):
            raise PublicationIntegrityError("M3 loader attestation is required")
        profile = wire.get("profile")
        digest = wire.get("capsule_digest")
        pipeline = wire.get("pipeline")
        package_path = wire.get("package_path")
        store_id = wire.get("store_id")
        signature = wire.get("signature")
        publication_digest = wire.get("publication_digest")
        if (
            profile != _M3_LOADER_PROFILE
            or digest != capsule_digest
            or not isinstance(pipeline, list)
            or tuple(pipeline) != _M3_LOADER_PIPELINE
            or not isinstance(package_path, str)
            or not package_path
            or not Path(package_path).is_absolute()
            or not isinstance(store_id, str)
            or not isinstance(signature, str)
            or not isinstance(publication_digest, str)
        ):
            raise PublicationIntegrityError("M3 loader attestation binding is invalid")
        try:
            from contractcapsule.build.publish import (
                LoaderAttestation,
                _loader_publication_digest,
            )

            attestation = getattr(permit, "loader_attestation", None)
            valid = (
                type(attestation) is LoaderAttestation
                and _jcs_text(attestation.wire()) == _jcs_text(dict(wire))
                and attestation.verify(None)
                and publication_digest == _loader_publication_digest(capsule)
            )
        except Exception:  # noqa: BLE001 - trust failures must fail closed.
            valid = False
        if not valid:
            raise PublicationIntegrityError("M3 loader attestation signature is invalid")
        if package_path is not None:
            try:
                from contractcapsule.package import load_capsule

                loaded = load_capsule(Path(package_path))
            except Exception as error:
                raise PublicationIntegrityError(
                    "M3 loader package could not be revalidated"
                ) from error
            if canonical_digest(loaded) != capsule_digest:
                raise PublicationIntegrityError("M3 loader package digest mismatch")
            if _loader_publication_digest(loaded) != publication_digest:
                raise PublicationIntegrityError(
                    "M3 loader package publication projection mismatch"
                )

    @staticmethod
    def _wire_evidence(
        evidence_wire: Any,
    ) -> dict[str, dict[str, Any]]:
        evidence_by_id: dict[str, dict[str, Any]] = {}
        for record in evidence_wire:
            if not isinstance(record, dict) or not isinstance(record.get("evidence_id"), str):
                raise PublicationIntegrityError("M3 evidence record is malformed")
            evidence_by_id[record["evidence_id"]] = record
        return evidence_by_id

    @staticmethod
    def _wire_atom_trust(
        atom: Any, evidence_by_id: Mapping[str, dict[str, Any]]
    ) -> dict[str, Any]:
        if not isinstance(atom, dict):
            raise PublicationIntegrityError("M3 atom record is malformed")
        if atom.get("status") != "validated":
            raise PublicationIntegrityError("unvalidated atom cannot enter publication")
        extensions = atom.get("extensions")
        trust = extensions.get("x-trust") if isinstance(extensions, dict) else None
        if not isinstance(trust, Mapping):
            raise PublicationIntegrityError("validated atom is missing trust metadata")
        if trust.get("level") not in {"T0", "T1", "T2"}:
            raise PublicationIntegrityError("validated atom trust level is invalid")
        candidate_id = trust.get("candidate_id")
        approval = trust.get("approval")
        refs = atom.get("evidence_refs")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise PublicationIntegrityError("validated atom candidate identity is missing")
        if not isinstance(approval, Mapping) or not isinstance(refs, list) or not refs:
            raise PublicationIntegrityError("validated atom approval/evidence is missing")
        if approval.get("candidate_id", candidate_id) != candidate_id:
            raise PublicationIntegrityError("approval candidate identity mismatch")
        Registry._validate_atom_refs(refs, candidate_id, evidence_by_id)
        return {"atom": atom, "trust": dict(trust)}

    @staticmethod
    def _validate_atom_refs(
        refs: list[Any],
        candidate_id: str,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> None:
        for evidence_id in refs:
            record = evidence_by_id.get(evidence_id)
            if record is None:
                raise PublicationIntegrityError("validated atom evidence reference is missing")
            extensions = record.get("extensions")
            source_map = extensions.get("x-source-map") if isinstance(extensions, dict) else None
            if not isinstance(source_map, Mapping):
                raise PublicationIntegrityError("evidence source-map binding is missing")
            if source_map.get("candidate_id", candidate_id) != candidate_id:
                raise PublicationIntegrityError("evidence binding candidate mismatch")

    @staticmethod
    def _wire_trust_metadata(
        capsule: Capsule,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Extract and minimally validate M3 trust metadata from the core wire form."""

        wire = capsule_wire_dict(capsule)
        atoms_wire = wire.get("semantic_payload", {}).get("atoms", [])
        evidence_wire = wire.get("evidence_plane", {}).get("records", [])
        if not isinstance(atoms_wire, list) or not isinstance(evidence_wire, list):
            raise PublicationIntegrityError("M3 trust metadata is malformed")
        evidence_by_id = Registry._wire_evidence(evidence_wire)
        validated_atoms = [
            Registry._wire_atom_trust(atom, evidence_by_id) for atom in atoms_wire
        ]
        return validated_atoms, evidence_by_id

    def _validate_m3_header(
        self,
        capsule: Capsule,
        principal: Principal,
        payload: Mapping[str, Any],
        permit: Any,
    ) -> None:
        manifest = capsule.control_manifest
        expected = {
            "capsule_digest": manifest.content_digest,
            "capsule_id": manifest.capsule_id,
            "version": manifest.version,
            "principal_id": principal.principal_id,
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                raise PublicationIntegrityError(
                    f"M3 trust permit {key} does not match publication"
                )
        if payload.get("policy_version") != getattr(self._trust_root, "policy_version", None):
            raise PublicationIntegrityError("M3 trust permit policy version mismatch")
        if payload.get("trust_root_id") != getattr(self._trust_root, "root_id", None):
            raise PublicationIntegrityError("M3 trust permit trust root mismatch")
        if payload.get("scanner_version") != _M3_SECRET_SCANNER_VERSION:
            raise PublicationIntegrityError("M3 secret scanner profile mismatch")
        if (
            payload.get("authority") != manifest.authority
            or payload.get("scope") != _scope_dict(capsule)
        ):
            raise PublicationIntegrityError("M3 trust permit publication target mismatch")
        self._validate_loader_attestation(payload, capsule, permit)

    @staticmethod
    def _permit_atom_map(
        permit_atoms: Any, expected_count: int
    ) -> dict[str, Mapping[str, Any]]:
        if not isinstance(permit_atoms, list) or len(permit_atoms) != expected_count:
            raise PublicationIntegrityError("M3 trust permit atom set does not match capsule")
        result: dict[str, Mapping[str, Any]] = {}
        for item in permit_atoms:
            if not isinstance(item, Mapping) or not isinstance(item.get("candidate_id"), str):
                raise PublicationIntegrityError("M3 trust permit atom entry is malformed")
            candidate_id = item["candidate_id"]
            if candidate_id in result:
                raise PublicationIntegrityError("M3 trust permit has duplicate candidates")
            result[candidate_id] = item
        return result

    @staticmethod
    def _candidate_projection(candidate: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": candidate.get("candidate_id"),
            "atom_id": candidate.get("atom_id"),
            "kind": candidate.get("kind"),
            "statement": candidate.get("statement"),
            "modality": candidate.get("modality"),
            "scope": candidate.get("scope"),
            "source_snapshot_id": candidate.get("source_snapshot_id"),
            "start_line": candidate.get("start_line"),
            "end_line": candidate.get("end_line"),
            "symbol_or_heading": candidate.get("symbol_or_heading"),
            "compression_class": candidate.get("compression_class"),
            "generated": candidate.get("generated"),
            "trust_level": candidate.get("source_trust_level"),
            "status": candidate.get("status"),
        }

    @staticmethod
    def _candidate_matches_permit(
        atom_wire: Mapping[str, Any],
        trust: Mapping[str, Any],
        permit_atom: Mapping[str, Any],
        candidate: Mapping[str, Any],
        calculated: str,
    ) -> None:
        candidate_id = trust.get("candidate_id")
        if (
            candidate.get("candidate_id") != candidate_id
            or candidate.get("atom_id") != atom_wire.get("atom_id")
            or candidate.get("statement") != atom_wire.get("statement")
            or candidate.get("kind") != atom_wire.get("kind")
            or candidate.get("modality") != atom_wire.get("modality")
            or candidate.get("scope") != atom_wire.get("scope")
            or candidate.get("compression_class") != atom_wire.get("compression_class")
            or candidate.get("validated_status") != atom_wire.get("status")
            or trust.get("candidate_digest") != calculated
            or permit_atom.get("candidate_digest") != calculated
            or trust.get("level") != permit_atom.get("validated_trust_level")
            or trust.get("source_level") != permit_atom.get("source_trust_level")
            or trust.get("level") != "T1"
            or candidate.get("validated_trust_level") != permit_atom.get("validated_trust_level")
            or permit_atom.get("validated_status") != "validated"
        ):
            raise PublicationIntegrityError("M3 trust permit candidate binding mismatch")
        projection = Registry._candidate_projection(candidate)
        permit_projection = {key: permit_atom.get(key) for key in projection}
        permit_projection["source_snapshot_id"] = permit_atom.get("snapshot_id")
        if _jcs_text(permit_projection) != _jcs_text(projection):
            raise PublicationIntegrityError("M3 trust permit candidate binding mismatch")

    @staticmethod
    def _source_classification(
        candidate: Mapping[str, Any], permit_atom: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        source_level = candidate.get("source_trust_level")
        source_proof = permit_atom.get("source_proof")
        if not isinstance(candidate.get("generated"), bool):
            raise PublicationIntegrityError("M3 candidate generated flag is invalid")
        if candidate.get("generated") and source_level != "T3":
            raise PublicationIntegrityError("generated M3 candidate is not T3")
        if source_level == "T2":
            if (
                not isinstance(source_proof, Mapping)
                or source_proof.get("collector_profile")
                != "CCS-2.1-deterministic-source-v1"
                or source_proof.get("snapshot_id") != candidate.get("source_snapshot_id")
                or source_proof.get("mode") != "GIT_IMMUTABLE"
            ):
                raise PublicationIntegrityError("M3 deterministic source proof is missing")
        elif source_level == "T3":
            if source_proof is not None:
                raise PublicationIntegrityError(
                    "M3 untrusted source has an invalid deterministic proof"
                )
        else:
            raise PublicationIntegrityError("M3 source trust classification is invalid")
        return source_proof

    @staticmethod
    def _validate_source_subjects(
        payload: Mapping[str, Any], permit: Any
    ) -> dict[str, Mapping[str, Any]]:
        source_subjects = payload.get("source_subjects")
        source_bytes = getattr(permit, "source_bytes", ())
        if (
            not isinstance(source_subjects, list)
            or not source_subjects
            or not isinstance(source_bytes, (tuple, list))
            or len(source_subjects) != len(source_bytes)
        ):
            raise PublicationIntegrityError("M3 trust permit source subjects are missing")
        subject_by_binding: dict[str, Mapping[str, Any]] = {}
        try:
            from contractcapsule.audit import quarantine as quarantine_module

            scanner = quarantine_module.scan_secrets
            for subject, data in zip(source_subjects, source_bytes, strict=True):
                if not isinstance(subject, Mapping) or not isinstance(data, bytes):
                    raise TypeError("source subject is malformed")
                binding_id = subject.get("binding_id")
                digest = subject.get("content_digest")
                if (
                    not isinstance(binding_id, str)
                    or binding_id in subject_by_binding
                    or digest != "sha256:" + hashlib.sha256(data).hexdigest()
                ):
                    raise ValueError("source subject digest does not match bytes")
                scanner(data)
                subject_by_binding[binding_id] = subject
        except Exception as error:
            raise PublicationIntegrityError("M3 secret scan or source proof failed") from error
        return subject_by_binding

    @staticmethod
    def _validate_candidate_witness(
        atom_wire: Mapping[str, Any],
        trust: Mapping[str, Any],
        permit_atom: Mapping[str, Any],
    ) -> tuple[str, Mapping[str, Any], str, Mapping[str, Any] | None]:
        candidate_id = trust.get("candidate_id")
        if not isinstance(candidate_id, str):
            raise PublicationIntegrityError("M3 candidate identity is malformed")
        candidate = trust.get("candidate")
        if not isinstance(candidate, Mapping):
            raise PublicationIntegrityError("M3 candidate witness is missing")
        projection = Registry._candidate_projection(candidate)
        calculated = "sha256:" + hashlib.sha256(
            canonical_json_bytes(projection)
        ).hexdigest()
        Registry._candidate_matches_permit(
            atom_wire, trust, permit_atom, candidate, calculated
        )
        source_proof = Registry._source_classification(candidate, permit_atom)
        return candidate_id, candidate, calculated, source_proof

    @staticmethod
    def _validate_approval_source(
        approval_record: Any,
        approved_at: datetime,
        permit_atom: Mapping[str, Any],
    ) -> None:
        source_principal_id = permit_atom.get("snapshot_principal_id")
        if (
            not isinstance(source_principal_id, str)
            or approval_record.approver_id == source_principal_id
        ):
            raise PublicationIntegrityError(
                "M3 approval must be from an external source principal"
            )
        snapshot_captured_at = permit_atom.get("snapshot_captured_at")
        if not isinstance(snapshot_captured_at, str):
            raise PublicationIntegrityError("M3 source capture timestamp is missing")
        try:
            captured_at = datetime.fromisoformat(
                snapshot_captured_at.removesuffix("Z") + "+00:00"
            ).astimezone(UTC)
        except (TypeError, ValueError) as error:
            raise PublicationIntegrityError(
                "M3 source capture timestamp is invalid"
            ) from error
        if approved_at < captured_at:
            raise PublicationIntegrityError("M3 approval predates source snapshot")

    def _validate_approval(
        self,
        candidate_id: str,
        candidate_digest: str,
        trust: Mapping[str, Any],
        permit_atom: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], list[str]]:
        approval = trust.get("approval")
        if not isinstance(approval, Mapping):
            raise PublicationIntegrityError("M3 approval witness is malformed")
        permit_approval = permit_atom.get("approval")
        if (
            not isinstance(permit_approval, Mapping)
            or _jcs_text(permit_approval) != _jcs_text(approval)
        ):
            raise PublicationIntegrityError("M3 trust permit approval binding mismatch")
        try:
            from contractcapsule.audit.quarantine import HumanApproval

            approval_record = HumanApproval(**dict(approval))
            verifier_factory = getattr(self._trust_root, "verifier", None)
            if not callable(verifier_factory):
                raise TypeError("M3 trust root verifier is unavailable")
            approval_valid = bool(verifier_factory().verify(approval_record))
            now = self._clock().astimezone(UTC)
            approved_at = datetime.fromisoformat(
                approval_record.approved_at.removesuffix("Z") + "+00:00"
            ).astimezone(UTC)
            expires_at = (
                datetime.fromisoformat(
                    approval_record.expires_at.removesuffix("Z") + "+00:00"
                ).astimezone(UTC)
                if approval_record.expires_at is not None
                else None
            )
        except Exception as error:
            raise PublicationIntegrityError("M3 approval is malformed") from error
        if (
            not approval_valid
            or approval_record.decision != "approve"
            or approval_record.candidate_id != candidate_id
            or approval_record.candidate_digest != candidate_digest
            or approved_at > now
            or (expires_at is not None and expires_at <= now)
        ):
            raise PublicationIntegrityError("M3 approval is expired or untrusted")
        self._validate_approval_source(approval_record, approved_at, permit_atom)
        evidence_digests = approval.get("evidence_digests")
        if not isinstance(evidence_digests, list) or not evidence_digests:
            raise PublicationIntegrityError("M3 approval has no evidence digests")
        return approval, evidence_digests

    @staticmethod
    def _binding_wire(
        record: Mapping[str, Any], source_map: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "binding_id": source_map.get("binding_id"),
            "candidate_id": source_map.get("candidate_id"),
            "snapshot_id": source_map.get("snapshot_id"),
            "mode": record.get("mode"),
            "content_digest": record.get("content_digest"),
            "span_digest": source_map.get("span_digest"),
            "media_type": record.get("media_type"),
            "captured_at": record.get("captured_at"),
            "access_policy": record.get("access_policy"),
            "repository": record.get("repository"),
            "revision": record.get("revision"),
            "path": source_map.get("path"),
            "symbol_or_heading": source_map.get("symbol_or_heading"),
            "start_line": source_map.get("start_line"),
            "end_line": source_map.get("end_line"),
            "uri": record.get("uri"),
            "source": record.get("source"),
            "verification_method": record.get("verification_method"),
        }

    def _validate_bindings(
        self,
        atom_wire: Mapping[str, Any],
        evidence: Mapping[str, Mapping[str, Any]],
        evidence_digests: list[str],
        subject_by_binding: Mapping[str, Mapping[str, Any]],
        source_level: Any,
        source_proof: Mapping[str, Any] | None,
    ) -> list[dict[str, Any]]:
        bindings: list[dict[str, Any]] = []
        for evidence_id in atom_wire["evidence_refs"]:
            record = evidence[evidence_id]
            extensions = record.get("extensions")
            source_map = extensions.get("x-source-map") if isinstance(extensions, dict) else None
            if not isinstance(source_map, Mapping):
                raise PublicationIntegrityError("M3 evidence source-map binding is missing")
            binding = self._binding_wire(record, source_map)
            binding_digest = "sha256:" + hashlib.sha256(
                canonical_json_bytes(binding)
            ).hexdigest()
            if (
                source_map.get("binding_digest") != binding_digest
                or binding_digest not in evidence_digests
                or binding["binding_id"] not in subject_by_binding
            ):
                raise PublicationIntegrityError("M3 evidence or approval binding mismatch")
            subject = subject_by_binding[binding["binding_id"]]
            if any(
                subject.get(key) != binding[key]
                for key in ("content_digest", "mode", "media_type", "snapshot_id")
            ):
                raise PublicationIntegrityError("M3 source subject mismatch")
            if binding["mode"] == "CAS":
                try:
                    from contractcapsule.audit import quarantine as quarantine_module

                    stored = self._cas._read_verified(binding["content_digest"])
                    quarantine_module.scan_secrets(stored.data)
                except Exception as error:
                    raise PublicationIntegrityError("M3 CAS source scan failed") from error
            bindings.append(binding)
        if source_level == "T2" and (
            not isinstance(source_proof, Mapping)
            or not any(
                binding["mode"] == source_proof.get("mode")
                and binding["snapshot_id"] == source_proof.get("snapshot_id")
                and binding["content_digest"] == source_proof.get("content_digest")
                and binding["repository"] == source_proof.get("repository")
                and binding["revision"] == source_proof.get("revision")
                and binding["path"] == source_proof.get("path")
                for binding in bindings
            )
        ):
            raise PublicationIntegrityError("M3 deterministic source proof does not bind evidence")
        return bindings

    def _validate_m3_atom(
        self,
        item: Mapping[str, Any],
        permit_by_id: Mapping[str, Mapping[str, Any]],
        evidence: Mapping[str, Mapping[str, Any]],
        subject_by_binding: Mapping[str, Mapping[str, Any]],
    ) -> None:
        atom_wire = item["atom"]
        trust = item["trust"]
        try:
            from contractcapsule.audit import quarantine as quarantine_module

            quarantine_module.scan_secrets(atom_wire.get("statement", ""))
        except Exception as error:
            raise PublicationIntegrityError("M3 atom secret scan failed") from error
        candidate_id = trust["candidate_id"]
        permit_atom = permit_by_id.get(candidate_id)
        if permit_atom is None:
            raise PublicationIntegrityError("M3 trust permit candidate is not in capsule")
        if not isinstance(atom_wire, Mapping) or not isinstance(trust, Mapping):
            raise PublicationIntegrityError("M3 trust metadata is malformed")
        _candidate_id, candidate, calculated, source_proof = self._validate_candidate_witness(
            atom_wire, trust, permit_atom
        )
        _approval, evidence_digests = self._validate_approval(
            candidate_id, calculated, trust, permit_atom
        )
        bindings = self._validate_bindings(
            atom_wire,
            evidence,
            evidence_digests,
            subject_by_binding,
            candidate.get("source_trust_level"),
            source_proof,
        )
        permit_bindings = permit_atom.get("bindings")
        expected_digests = [
            "sha256:" + hashlib.sha256(canonical_json_bytes(binding)).hexdigest()
            for binding in bindings
        ]
        if (
            not isinstance(permit_bindings, list)
            or _jcs_text(permit_bindings) != _jcs_text(bindings)
            or evidence_digests != expected_digests
        ):
            raise PublicationIntegrityError("M3 trust permit evidence binding mismatch")

    def _validate_m3_publication(
        self,
        capsule: Capsule,
        principal: Principal,
        permit: Any | None,
    ) -> Mapping[str, Any] | None:
        """Enforce the final M3 evidence/approval gate immediately before commit."""

        if not self._requires_m3_gate(capsule):
            return None
        if permit is None:
            raise PublicationIntegrityError("M3 trust proof is required")
        try:
            from contractcapsule.audit import quarantine as quarantine_module

            quarantine_module.scan_secrets(
                canonical_json_bytes(capsule_wire_dict(capsule))
            )
        except Exception as error:
            raise PublicationIntegrityError("M3 final publication secret scan failed") from error
        payload = self._verify_permit_signature(permit)
        try:
            quarantine_module.scan_secrets(canonical_json_bytes(payload))
            signature = getattr(permit, "signature", None)
            if not isinstance(signature, str):
                raise TypeError("publication permit signature is malformed")
            quarantine_module.scan_secrets(signature)
        except Exception as error:
            raise PublicationIntegrityError(
                "M3 trust permit secret scan failed"
            ) from error
        self._validate_m3_header(capsule, principal, payload, permit)
        subject_by_binding = self._validate_source_subjects(payload, permit)
        atoms, evidence = self._wire_trust_metadata(capsule)
        permit_by_id = self._permit_atom_map(payload.get("atoms"), len(atoms))
        for item in atoms:
            self._validate_m3_atom(item, permit_by_id, evidence, subject_by_binding)
        return payload

    @staticmethod
    def _revalidate_candidate(capsule: Capsule) -> Capsule:
        """Re-enter the strict model boundary before trusting a caller's object."""

        if type(capsule) is not Capsule:
            raise PublicationIntegrityError("candidate model validation failed")
        try:
            wire = capsule_wire_dict(capsule)
            return Capsule.model_validate_json(
                json.dumps(wire, ensure_ascii=False, allow_nan=False)
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise PublicationIntegrityError(
                "candidate model validation failed"
            ) from error

    def _insert_evidence(
        self, connection: sqlite3.Connection, publication_id: int, capsule: Capsule
    ) -> None:
        for ordinal, record in enumerate(self._evidence_records(capsule)):
            connection.execute(
                """
                INSERT INTO evidence_references (
                    publication_id, ordinal, evidence_id, mode, content_digest,
                    media_type, access_policy, immutable_record_jcs
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    publication_id,
                    ordinal,
                    record["evidence_id"],
                    record["mode"],
                    record["content_digest"],
                    record["media_type"],
                    record["access_policy"],
                    _jcs_text(record),
                ),
            )

    def _insert_grants(
        self, connection: sqlite3.Connection, publication_id: int, capsule: Capsule
    ) -> None:
        for record in capsule.evidence_plane.records:
            if record.mode != "CAS":
                continue
            connection.execute(
                """
                INSERT INTO digest_grants (
                    publication_id, evidence_id, digest, access_policy
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    publication_id,
                    record.evidence_id,
                    record.content_digest,
                    record.access_policy,
                ),
            )

    def _insert_m3_attestation(
        self,
        connection: sqlite3.Connection,
        publication_id: int,
        principal: Principal,
        permit: Any,
        payload: Mapping[str, Any],
    ) -> None:
        root_id = getattr(self._trust_root, "root_id", None)
        policy_version = getattr(self._trust_root, "policy_version", None)
        signature = getattr(permit, "signature", None)
        if not isinstance(root_id, str) or not isinstance(policy_version, str):
            raise PublicationIntegrityError("M3 trust root metadata is unavailable")
        if not isinstance(signature, str) or not signature:
            raise PublicationIntegrityError("M3 trust permit signature is missing")
        source_subjects = payload.get("source_subjects")
        if not isinstance(source_subjects, list):
            raise PublicationIntegrityError("M3 source subjects are malformed")
        connection.execute(
            """
            INSERT INTO m3_trust_attestations (
                publication_id, policy_version, trust_root_id, principal_id,
                permit_payload_jcs, permit_signature, source_subjects_jcs
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                publication_id,
                policy_version,
                root_id,
                principal.principal_id,
                _jcs_text(payload),
                signature,
                _jcs_text(source_subjects),
            ),
        )

    @staticmethod
    def _attestation_row(
        connection: sqlite3.Connection, row: sqlite3.Row, capsule: Capsule
    ) -> sqlite3.Row | None:
        attestation = connection.execute(
            "SELECT * FROM m3_trust_attestations WHERE publication_id = ?",
            (row["publication_id"],),
        ).fetchone()
        if attestation is None and not _is_m3_capsule(capsule):
            # A pre-M3 M2 publication has no trust attestation and remains
            # readable after a service is upgraded with an M3 trust root.
            return None
        if attestation is None:
            raise PublicationIntegrityError("M3 trust attestation is missing")
        return attestation

    def _attestation_payload(
        self, attestation: sqlite3.Row, row: sqlite3.Row
    ) -> Mapping[str, Any]:
        root_type = _trust_root_class()
        if root_type is None or type(self._trust_root) is not root_type:
            raise PublicationIntegrityError("M3 trust root is unavailable")
        try:
            payload = json.loads(attestation["permit_payload_jcs"])
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise PublicationIntegrityError("M3 trust attestation payload is corrupt") from error
        if not isinstance(payload, Mapping):
            raise PublicationIntegrityError("M3 trust attestation payload is malformed")
        if (
            payload.get("capsule_digest") != row["content_digest"]
            or payload.get("capsule_id") != row["capsule_id"]
            or payload.get("version") != row["version"]
        ):
            raise PublicationIntegrityError("M3 trust attestation capsule binding mismatch")
        if attestation["policy_version"] != getattr(self._trust_root, "policy_version", None):
            raise PublicationIntegrityError("M3 trust attestation policy mismatch")
        if (
            attestation["trust_root_id"] != getattr(self._trust_root, "root_id", None)
            or attestation["principal_id"] != payload.get("principal_id")
        ):
            raise PublicationIntegrityError("M3 trust attestation denormalized binding mismatch")
        verify_payload = getattr(self._trust_root, "verify_payload", None)
        if not callable(verify_payload):
            raise PublicationIntegrityError("M3 trust root cannot verify attestations")
        try:
            valid = bool(verify_payload(payload, attestation["permit_signature"]))
        except Exception:  # noqa: BLE001 - trust verification must fail closed.
            valid = False
        if not valid:
            raise PublicationIntegrityError("M3 trust attestation signature is invalid")
        return payload

    @staticmethod
    def _attestation_subjects(
        attestation: sqlite3.Row, payload: Mapping[str, Any]
    ) -> None:
        try:
            subjects = json.loads(attestation["source_subjects_jcs"])
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise PublicationIntegrityError("M3 source subject record is corrupt") from error
        if subjects != payload.get("source_subjects"):
            raise PublicationIntegrityError("M3 source subject record disagrees")

    def _verify_m3_attestation(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        capsule: Capsule,
    ) -> None:
        if not self._requires_m3_gate(capsule):
            return
        attestation = self._attestation_row(connection, row, capsule)
        if attestation is None:
            return
        payload = self._attestation_payload(attestation, row)
        self._attestation_subjects(attestation, payload)

    def _verify_m3_replay(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        payload: Mapping[str, Any],
        permit: Any,
    ) -> None:
        """Require an exact permit replay for an already published M3 version."""

        attestation = connection.execute(
            "SELECT permit_payload_jcs, permit_signature FROM m3_trust_attestations "
            "WHERE publication_id = ?",
            (row["publication_id"],),
        ).fetchone()
        if attestation is None:
            raise PublicationIntegrityError("M3 trust attestation is missing")
        signature = getattr(permit, "signature", None)
        if (
            attestation["permit_payload_jcs"] != _jcs_text(payload)
            or attestation["permit_signature"] != signature
        ):
            raise PublicationConflict("M3 replay differs in immutable trust proof")

    def _expected_rows(
        self, capsule: Capsule
    ) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
        evidence = []
        grants = []
        for ordinal, record in enumerate(self._evidence_records(capsule)):
            evidence.append(
                (
                    ordinal,
                    record["evidence_id"],
                    record["mode"],
                    record["content_digest"],
                    record["media_type"],
                    record["access_policy"],
                    _jcs_text(record),
                )
            )
            if record["mode"] == "CAS":
                grants.append(
                    (record["evidence_id"], record["content_digest"], record["access_policy"])
                )
        return evidence, grants

    def _verify_existing(
        self, connection: sqlite3.Connection, row: sqlite3.Row, capsule: Capsule
    ) -> None:
        signature = _signature_dict(capsule)
        expected_publication = (
            capsule.control_manifest.content_digest,
            capsule.control_manifest.lifecycle,
            capsule.control_manifest.authority,
            _jcs_text(_scope_dict(capsule)),
            _jcs_text(_publication_core(capsule)),
            _jcs_text(signature) if signature is not None else None,
        )
        stored_publication = (
            row["content_digest"],
            row["lifecycle"],
            row["authority"],
            row["scope_jcs"],
            row["immutable_record_jcs"],
            row["detached_signature_jcs"],
        )
        if stored_publication != expected_publication:
            raise PublicationConflict("immutable publication fields differ")
        publication_id = row["publication_id"]
        evidence_rows = connection.execute(
            """
            SELECT ordinal, evidence_id, mode, content_digest, media_type,
                   access_policy, immutable_record_jcs
            FROM evidence_references WHERE publication_id = ? ORDER BY ordinal
            """,
            (publication_id,),
        ).fetchall()
        grant_rows = connection.execute(
            """
            SELECT evidence_id, digest, access_policy FROM digest_grants
            WHERE publication_id = ? ORDER BY evidence_id, digest
            """,
            (publication_id,),
        ).fetchall()
        expected_evidence, expected_grants = self._expected_rows(capsule)
        if [tuple(item) for item in evidence_rows] != expected_evidence:
            raise PublicationIntegrityError("stored evidence references are incomplete")
        if [tuple(item) for item in grant_rows] != sorted(expected_grants):
            raise PublicationIntegrityError("stored digest grants are incomplete")
        self._verify_m3_attestation(connection, row, capsule)

    def _row_to_published(self, row: sqlite3.Row) -> PublishedCapsule:
        try:
            wire = json.loads(row["immutable_record_jcs"])
            signature = row["detached_signature_jcs"]
            wire["detached_signature"] = json.loads(signature) if signature else None
            wire["derived_artifacts"] = {}
            wire["runtime_sidecar"] = {}
            capsule = Capsule.model_validate_json(json.dumps(wire))
        except Exception as error:
            raise PublicationIntegrityError("stored Capsule cannot be reconstructed") from error
        if (
            canonical_digest(capsule) != row["content_digest"]
            or capsule.control_manifest.content_digest != row["content_digest"]
            or capsule.control_manifest.lifecycle != row["lifecycle"]
            or capsule.control_manifest.authority != row["authority"]
            or _jcs_text(_scope_dict(capsule)) != row["scope_jcs"]
        ):
            raise PublicationIntegrityError("stored Capsule denormalized fields disagree")
        return PublishedCapsule(capsule, "PUBLISHED", row["published_at"])

    def publish(
        self,
        capsule: Capsule,
        principal: Principal,
        *,
        publication_permit: Any | None = None,
    ) -> PublishedCapsule:
        if type(principal) is not Principal:
            raise TypeError("principal must be a Principal")
        capsule = self._revalidate_candidate(capsule)
        self._authorize_publish(capsule, principal)
        manifest = capsule.control_manifest
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Re-evaluate authorization while the publication transaction owns the
            # write boundary, closing the resolver TOCTOU window between preflight
            # and the immutable insert.
            self._authorize_publish(capsule, principal)
            # The private CAS rehash is inside the Registry transaction. A failed
            # check cannot leave publication, reference, or grant rows behind.
            self._validate_candidate(capsule)
            row = connection.execute(
                "SELECT * FROM publications WHERE capsule_id = ? AND version = ?",
                (manifest.capsule_id, manifest.version),
            ).fetchone()
            # Preserve the M2 restart/idempotence behavior for an already stored,
            # unmarked legacy row. This branch never creates a new row and still
            # verifies every immutable field and evidence/grant reference. Any
            # fresh P0/P1 publication continues through the mandatory M3 gate.
            if row is not None and publication_permit is None and not _is_m3_capsule(capsule):
                if row["content_digest"] != manifest.content_digest:
                    raise VersionConflict("capsule ID and version already have another digest")
                self._verify_existing(connection, row, capsule)
                return self._row_to_published(row)
            m3_payload = self._validate_m3_publication(
                capsule, principal, publication_permit
            )
            if row is not None:
                if row["content_digest"] != manifest.content_digest:
                    raise VersionConflict("capsule ID and version already have another digest")
                self._verify_existing(connection, row, capsule)
                if m3_payload is not None:
                    self._verify_m3_replay(
                        connection, row, m3_payload, publication_permit
                    )
                return self._row_to_published(row)

            published_at = _timestamp(self._clock)
            signature = _signature_dict(capsule)
            cursor = connection.execute(
                """
                INSERT INTO publications (
                    capsule_id, version, content_digest, lifecycle, authority,
                    scope_jcs, immutable_record_jcs, detached_signature_jcs, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.capsule_id,
                    manifest.version,
                    manifest.content_digest,
                    manifest.lifecycle,
                    manifest.authority,
                    _jcs_text(_scope_dict(capsule)),
                    _jcs_text(_publication_core(capsule)),
                    _jcs_text(signature) if signature is not None else None,
                    published_at,
                ),
            )
            if cursor.lastrowid is None:  # pragma: no cover - SQLite contract guard
                raise PublicationIntegrityError("publication insert returned no identifier")
            publication_id = cursor.lastrowid
            self._insert_evidence(connection, publication_id, capsule)
            self._insert_grants(connection, publication_id, capsule)
            if m3_payload is not None:
                self._insert_m3_attestation(
                    connection,
                    publication_id,
                    principal,
                    publication_permit,
                    m3_payload,
                )
            row = connection.execute(
                "SELECT * FROM publications WHERE publication_id = ?", (publication_id,)
            ).fetchone()
            if row is None:  # pragma: no cover - SQLite contract guard
                raise PublicationIntegrityError("publication row disappeared in transaction")
            self._verify_existing(connection, row, capsule)
            return self._row_to_published(row)

    def get(
        self, capsule_id: str, version: str, principal: Principal
    ) -> PublishedCapsule:
        if type(principal) is not Principal:
            raise TypeError("principal must be a Principal")
        generic = "capsule version is unavailable"
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM publications WHERE capsule_id = ? AND version = ?",
                (capsule_id, version),
            ).fetchone()
            if row is None:
                raise RegistryNotFound(generic)
            try:
                scope = json.loads(row["scope_jcs"])
                policies = frozenset(
                    item[0]
                    for item in connection.execute(
                        """
                        SELECT access_policy FROM evidence_references
                        WHERE publication_id = ?
                        """,
                        (row["publication_id"],),
                    ).fetchall()
                )
                decision = self._decision_for_claims(
                    principal, "read", row["authority"], scope
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                decision = PolicyDecision.deny()
                policies = frozenset()
            if not decision.allowed or not policies <= decision.allowed_access_policies:
                raise RegistryNotFound(generic)
            published = self._row_to_published(row)
            self._verify_existing(connection, row, published.capsule)
            for record in published.capsule.evidence_plane.records:
                if record.mode == "CAS":
                    stored = self._cas._read_verified(record.content_digest)
                    if stored.ref.media_type != record.media_type:
                        raise PublicationIntegrityError(
                            "stored CAS evidence media type disagrees"
                        )
            return published

    def can_read_blob(self, digest: str, principal: Principal) -> bool:
        if type(principal) is not Principal:
            raise TypeError("principal must be a Principal")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.*, g.evidence_id AS grant_evidence_id,
                       g.access_policy AS grant_access_policy
                FROM digest_grants AS g
                JOIN publications AS p ON p.publication_id = g.publication_id
                WHERE g.digest = ?
                """,
                (digest,),
            ).fetchall()
            for row in rows:
                try:
                    published = self._row_to_published(row)
                    self._verify_existing(connection, row, published.capsule)
                    decision = self._decision(published.capsule, principal, "read")
                except (PublicationConflict, PublicationIntegrityError):
                    continue
                if (
                    decision.allowed
                    and row["grant_access_policy"]
                    in decision.allowed_access_policies
                ):
                    record = next(
                        (
                            item
                            for item in published.capsule.evidence_plane.records
                            if item.mode == "CAS"
                            and item.evidence_id == row["grant_evidence_id"]
                            and item.content_digest == digest
                        ),
                        None,
                    )
                    if record is None:
                        continue
                    stored = self._cas._read_verified(digest)
                    if stored.ref.media_type != record.media_type:
                        raise BlobIntegrityError(
                            "published CAS evidence media type disagrees"
                        )
                    return True
        return False

    def get_blob(self, digest: str, principal: Principal) -> bytes:
        if not self.can_read_blob(digest, principal):
            raise BlobAuthorizationError("blob read is not authorized")
        return self._cas._read_verified(digest).data

    def _table_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in (
                    "publications",
                    "evidence_references",
                    "digest_grants",
                )
            }


def publish(
    capsule: Capsule,
    principal: Principal,
    *,
    registry: Registry,
    publication_permit: Any | None = None,
) -> PublishedCapsule:
    """Required functional interface with an injected Registry."""

    if type(registry) is not Registry:
        raise TypeError("registry must be the sealed Registry implementation")
    return registry.publish(
        capsule, principal, publication_permit=publication_permit
    )


def get(
    capsule_id: str,
    version: str,
    principal: Principal,
    *,
    registry: Registry,
) -> PublishedCapsule:
    """Required functional interface with an injected Registry."""

    if type(registry) is not Registry:
        raise TypeError("registry must be the sealed Registry implementation")
    return registry.get(capsule_id, version, principal)
