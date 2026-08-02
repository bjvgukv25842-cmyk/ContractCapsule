"""Explicit CCS-2.1-canonical-v1 identity projection and JCS encoding."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

import rfc8785

from contractcapsule.models.base import reject_surrogates
from contractcapsule.models.core import (
    Capsule,
    CASEvidence,
    ExternalImmutableEvidence,
    GitImmutableEvidence,
)

CANONICAL_PROFILE = "CCS-2.1-canonical-v1"
SIGNATURE_DOMAIN = b"CCS-2.1-signature-v1\0"


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str):
            reject_surrogates(value)
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > (2**53 - 1):
            raise ValueError("integer is outside the exact IEEE 754 range")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number is not permitted")
        return value
    if isinstance(value, Mapping):
        return _json_object(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    raise ValueError(f"value is not JCS-compatible: {type(value).__name__}")


def _json_object(value: Mapping[Any, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("JCS object keys must be strings")
        reject_surrogates(key)
        result[key] = _json_value(item)
    return result


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a value with RFC 8785/JCS, rejecting ambiguous JSON values."""

    try:
        return rfc8785.dumps(_json_value(value))
    except (rfc8785.CanonicalizationError, UnicodeEncodeError) as error:
        raise ValueError(f"value is not JCS-compatible: {error}") from error


def _extensions(value: Mapping[str, Any]) -> dict[str, Any]:
    return _json_value(value)


def _manifest(capsule: Capsule) -> dict[str, Any]:
    manifest = capsule.control_manifest
    return {
        "spec_version": manifest.spec_version,
        "canonical_profile": manifest.canonical_profile,
        "capsule_id": manifest.capsule_id,
        "version": manifest.version,
        # manifest.content_digest is intentionally excluded to avoid recursion.
        "owner": manifest.owner,
        "tenant": manifest.tenant,
        "scope": {
            "repositories": list(manifest.scope.repositories),
            "paths": list(manifest.scope.paths),
            "environments": list(manifest.scope.environments),
        },
        "authority": manifest.authority,
        "sensitivity": manifest.sensitivity,
        "provides": list(manifest.provides),
        "requires": list(manifest.requires),
        "conflicts": list(manifest.conflicts),
        "lifecycle": manifest.lifecycle,
        "created_from": list(manifest.created_from),
        "integrity": {
            "lock": manifest.integrity.lock,
            "signature": manifest.integrity.signature,
        },
        "extensions": _extensions(manifest.extensions),
    }


def _semantic_payload(capsule: Capsule) -> dict[str, Any]:
    return {
        "atoms": [
            {
                "atom_id": atom.atom_id,
                "kind": atom.kind,
                "statement": atom.statement,
                "modality": atom.modality,
                "scope": list(atom.scope),
                "exceptions": list(atom.exceptions),
                "validity": {"from": atom.validity.from_, "until": atom.validity.until},
                "authority": atom.authority,
                "status": atom.status,
                "confidence": atom.confidence,
                "evidence_refs": list(atom.evidence_refs),
                "requires_atoms": list(atom.requires_atoms),
                "conflicts_with": list(atom.conflicts_with),
                "sensitivity": atom.sensitivity,
                "compression_class": atom.compression_class,
                "refresh_policy": atom.refresh_policy,
                "extensions": _extensions(atom.extensions),
            }
            for atom in capsule.semantic_payload.atoms
        ],
        "extensions": _extensions(capsule.semantic_payload.extensions),
    }


def _evidence_plane(capsule: Capsule) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for record in capsule.evidence_plane.records:
        item: dict[str, Any] = {
            "mode": record.mode,
            "evidence_id": record.evidence_id,
            "atom_ids": list(record.atom_ids),
            "content_digest": record.content_digest,
            "media_type": record.media_type,
            "captured_at": record.captured_at,
            "retention": record.retention,
            "access_policy": record.access_policy,
            "validation": record.validation,
            "extensions": _extensions(record.extensions),
        }
        if isinstance(record, GitImmutableEvidence):
            item.update(
                {
                    "repository": record.repository,
                    "revision": record.revision,
                    "path": record.path,
                    "locator": {
                        "symbol_or_heading": record.locator.symbol_or_heading,
                        "start_line": record.locator.start_line,
                        "end_line": record.locator.end_line,
                        "span_digest": record.locator.span_digest,
                    },
                }
            )
        elif isinstance(record, ExternalImmutableEvidence):
            item.update(
                {
                    "uri": record.uri,
                    "source": record.source,
                    "verification_method": record.verification_method,
                }
            )
        elif not isinstance(record, CASEvidence):  # pragma: no cover - union exhaustiveness
            raise TypeError(f"unsupported evidence type: {type(record).__name__}")
        records.append(item)
    return {
        "records": records,
        "extensions": _extensions(capsule.evidence_plane.extensions),
    }


def _dependency_graph(capsule: Capsule) -> dict[str, Any]:
    return {
        "edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "edge_type": edge.edge_type,
                "version_constraint": edge.version_constraint,
                "mandatory": edge.mandatory,
                "extensions": _extensions(edge.extensions),
            }
            for edge in capsule.dependency_graph.edges
        ],
        "extensions": _extensions(capsule.dependency_graph.extensions),
    }


def _replacement_contract(capsule: Capsule) -> dict[str, Any]:
    contract = capsule.replacement_contract
    return {
        "contract_id": contract.contract_id,
        "replaces": contract.replaces,
        "preconditions": list(contract.preconditions),
        "target_effects": list(contract.target_effects),
        "protected_invariants": list(contract.protected_invariants),
        "allowed_scope": list(contract.allowed_scope),
        "forbidden_spillover": list(contract.forbidden_spillover),
        "verification": {
            "static": list(contract.verification.static),
            "behavioral": list(contract.verification.behavioral),
            "differential": list(contract.verification.differential),
        },
        "activation": {
            "risk": contract.activation.risk,
            "approval_required": contract.activation.approval_required,
            "safe_boundary": contract.activation.safe_boundary,
        },
        "rollback": {
            "pointer": contract.rollback.pointer,
            "compensating_action": contract.rollback.compensating_action,
        },
        "extensions": _extensions(contract.extensions),
    }


def _compression_policy(capsule: Capsule) -> dict[str, Any]:
    policy = capsule.compression_policy
    return {
        "policy_version": policy.policy_version,
        "classes": [
            {
                "name": item.name,
                "rendering": item.rendering,
                "lossy_compression": item.lossy_compression,
                "expansion_triggers": list(item.expansion_triggers),
                "ttl": item.ttl,
            }
            for item in policy.classes
        ],
        "extensions": _extensions(policy.extensions),
    }


def _tests_integrity(capsule: Capsule) -> dict[str, Any]:
    integrity = capsule.tests_integrity
    lock = integrity.lock
    return {
        "tests": [
            {
                "test_id": test.test_id,
                "kind": test.kind,
                "path": test.path,
                "digest": test.digest,
            }
            for test in integrity.tests
        ],
        "lock": {
            "capsule_dependencies": [
                {
                    "capsule_id": item.capsule_id,
                    "version": item.version,
                    "digest": item.digest,
                }
                for item in lock.capsule_dependencies
            ],
            "source_commits": list(lock.source_commits),
            "compiler_version": lock.compiler_version,
            "adapter_versions": list(lock.adapter_versions),
            "compression_policy_version": lock.compression_policy_version,
            "test_set_version": lock.test_set_version,
            "model_series": list(lock.model_series),
            "parameters": list(lock.parameters),
            "runtime_config_digest": lock.runtime_config_digest,
            "extensions": _extensions(lock.extensions),
        },
        "artifact_checksums": [
            {"path": item.path, "digest": item.digest}
            for item in integrity.artifact_checksums
        ],
        "signature_policy": {
            "algorithm": integrity.signature_policy.algorithm,
            "key_id": integrity.signature_policy.key_id,
            "input_profile": integrity.signature_policy.input_profile,
        },
        "extensions": _extensions(integrity.extensions),
    }


def identity_projection(capsule: Capsule) -> dict[str, Any]:
    """Return the explicit, versioned identity projection for all seven modules."""

    return {
        "profile": CANONICAL_PROFILE,
        "core": {
            "control_manifest": _manifest(capsule),
            "semantic_payload": _semantic_payload(capsule),
            "evidence_plane": _evidence_plane(capsule),
            "dependency_graph": _dependency_graph(capsule),
            "replacement_contract": _replacement_contract(capsule),
            "compression_policy": _compression_policy(capsule),
            "tests_integrity": _tests_integrity(capsule),
        },
    }


def canonical_digest(capsule: Capsule) -> str:
    """Compute the stable production content identity for a Capsule."""

    digest = hashlib.sha256(canonical_json_bytes(identity_projection(capsule))).hexdigest()
    return f"sha256:{digest}"


def signature_input(content_digest: str) -> bytes:
    """Return the frozen future signing message; M2 performs no signature operation."""

    if not re.fullmatch(r"sha256:[0-9a-f]{64}", content_digest):
        raise ValueError("signature input requires a canonical SHA-256 digest")
    return SIGNATURE_DOMAIN + content_digest.encode("ascii")


def capsule_wire_dict(capsule: Capsule) -> dict[str, Any]:
    """Build a full storage/package representation without implicit model dumping."""

    core = identity_projection(capsule)["core"]
    result = dict(core)
    result["control_manifest"] = dict(result["control_manifest"])
    result["control_manifest"]["content_digest"] = capsule.control_manifest.content_digest
    if capsule.detached_signature is not None:
        result["detached_signature"] = {
            "algorithm": capsule.detached_signature.algorithm,
            "key_id": capsule.detached_signature.key_id,
            "value": capsule.detached_signature.value,
            "envelope": _json_value(capsule.detached_signature.envelope),
        }
    result["derived_artifacts"] = _json_value(capsule.derived_artifacts)
    result["runtime_sidecar"] = _json_value(capsule.runtime_sidecar)
    return result
