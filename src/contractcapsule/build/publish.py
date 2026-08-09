"""Source-grounded capsule construction and M2-backed publication for M3."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from contractcapsule.audit.quarantine import (
    EvidenceBinding,
    QuarantineError,
    QuarantineStore,
    ValidatedAtom,
    scan_secrets,
)
from contractcapsule.models import Capsule, Principal
from contractcapsule.models.canonical import canonical_digest, capsule_wire_dict
from contractcapsule.package import load_capsule
from contractcapsule.storage.registry import PublishedCapsule, Registry

_ZERO_DIGEST = "sha256:" + "0" * 64
_BUILDER_TEST_BYTES = b'{"check":"m3-source-grounding"}\n'
_BUILDER_TEST_DIGEST = "sha256:" + hashlib.sha256(_BUILDER_TEST_BYTES).hexdigest()
_LOADER_RECEIPT = object()


class BuildError(QuarantineError):
    """A complete source-grounded Capsule could not be built safely."""


@dataclass(frozen=True, slots=True)
class BuildRequest:
    """Explicit inputs for one M3 capsule build.

    ``quarantine`` is mandatory because it is the trust root that can attest that every
    supplied ``ValidatedAtom`` crossed the evidence-and-human-approval gate.
    """

    atoms: tuple[ValidatedAtom, ...]
    quarantine: QuarantineStore | None = None
    template: Capsule | Mapping[str, Any] | None = None
    capsule_id: str = "org.contractcapsule.generated"
    version: str = "0.1.0"
    owner: str = "source-owner"
    tenant: str = "local-research"
    authority: str = "human-validated-source"
    sensitivity: str = "internal"
    lifecycle: str = "VALIDATED"
    environments: tuple[str, ...] = ("research",)
    package_path: Path | None = None
    detached_signature: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DraftCapsule:
    """A complete Capsule accepted by the public M2 package loader."""

    capsule: Capsule
    atom_ids: tuple[str, ...]
    package_path: Path | None
    validation_pipeline: tuple[str, ...] = (
        "strict-json",
        "json-schema",
        "python-semantics",
        "digest-and-reference-integrity",
        "load_capsule",
    )
    _loader_receipt: object | None = field(default=None, repr=False, compare=False)


def _approval_extension(atom: ValidatedAtom) -> dict[str, Any]:
    approval = atom.approval
    return {
        "x-trust": {
            "level": atom.trust_level,
            "source_level": atom.source_trust_level,
            "candidate_id": atom.candidate_id,
            "approval": {
                "approval_id": approval.approval_id,
                "approver_id": approval.approver_id,
                "approved_at": approval.approved_at,
                "decision": approval.decision,
                "candidate_digest": approval.candidate_digest,
                "evidence_digests": list(approval.evidence_digests),
                "expires_at": approval.expires_at,
                "issuer": approval.issuer,
                "signature": approval.signature,
            },
        }
    }


def _atom_record(atom: ValidatedAtom, authority: str) -> dict[str, Any]:
    scan_secrets(atom.statement)
    evidence_ids = [binding.binding_id for binding in atom.evidence_bindings]
    valid_from = min(binding.captured_at[:10] for binding in atom.evidence_bindings)
    return {
        "atom_id": atom.atom_id,
        "kind": atom.kind,
        "statement": atom.statement,
        "modality": atom.modality,
        "scope": list(atom.scope),
        "exceptions": [],
        "validity": {"from": valid_from, "until": None},
        "authority": authority,
        "status": "validated",
        "confidence": 1.0,
        "evidence_refs": evidence_ids,
        "requires_atoms": [],
        "conflicts_with": [],
        "sensitivity": "internal",
        "compression_class": atom.compression_class,
        "refresh_policy": "on-source-change",
        "extensions": _approval_extension(atom),
    }


def _binding_extension(binding: EvidenceBinding) -> dict[str, Any]:
    return {
        "x-source-map": {
            "binding_id": binding.binding_id,
            "snapshot_id": binding.snapshot_id,
            "mode": binding.mode,
            "content_digest": binding.content_digest,
            "path": binding.path,
            "symbol_or_heading": binding.symbol_or_heading,
            "start_line": binding.start_line,
            "end_line": binding.end_line,
            "span_digest": binding.span_digest,
        }
    }


def _evidence_record(binding: EvidenceBinding, atom_id: str) -> dict[str, Any]:
    scan_secrets(binding.source_bytes)
    record: dict[str, Any] = {
        "mode": binding.mode,
        "evidence_id": binding.binding_id,
        "atom_ids": [atom_id],
        "content_digest": binding.content_digest,
        "media_type": binding.media_type,
        "captured_at": binding.captured_at,
        "retention": "follow-source-policy",
        "access_policy": binding.access_policy,
        "validation": "verified",
        "extensions": _binding_extension(binding),
    }
    if binding.mode == "GIT_IMMUTABLE":
        record.update(
            {
                "repository": binding.repository,
                "revision": binding.revision,
                "path": binding.path,
                "locator": {
                    "symbol_or_heading": binding.symbol_or_heading,
                    "start_line": binding.start_line,
                    "end_line": binding.end_line,
                    "span_digest": binding.span_digest,
                },
            }
        )
    elif binding.mode == "EXTERNAL_IMMUTABLE":
        record.update(
            {
                "uri": binding.uri,
                "source": binding.source,
                "verification_method": binding.verification_method,
            }
        )
    return record


def _source_markers(
    atoms: tuple[ValidatedAtom, ...],
) -> tuple[list[str], list[str], list[str]]:
    created_from: list[str] = []
    paths: list[str] = []
    repositories: list[str] = []
    for atom in atoms:
        for binding in atom.evidence_bindings:
            if binding.mode == "GIT_IMMUTABLE":
                marker = f"git:{binding.repository}@{binding.revision}:{binding.path}"
                path = binding.path or "external/content"
                repository = binding.repository or "git-source"
            elif binding.mode == "EXTERNAL_IMMUTABLE":
                marker = f"external:{binding.uri}@{binding.content_digest}"
                path = "external/content"
                repository = "external-source"
            else:
                marker = f"cas:{binding.content_digest}"
                path = "source/content"
                repository = "local-cas"
            if marker not in created_from:
                created_from.append(marker)
            if path not in paths:
                paths.append(path)
            if repository not in repositories:
                repositories.append(repository)
    return created_from, paths, repositories


def _default_core(request: BuildRequest) -> dict[str, Any]:
    created_from, paths, repositories = _source_markers(request.atoms)
    signature = (
        copy.deepcopy(dict(request.detached_signature))
        if request.detached_signature
        else None
    )
    signature_policy = {
        "algorithm": signature["algorithm"] if signature else "m3-test-only",
        "key_id": signature["key_id"] if signature else "not-signed",
        "input_profile": "CCS-2.1-signature-v1",
    }
    return {
        "control_manifest": {
            "spec_version": "CCS-2.1",
            "canonical_profile": "CCS-2.1-canonical-v1",
            "capsule_id": request.capsule_id,
            "version": request.version,
            "content_digest": _ZERO_DIGEST,
            "owner": request.owner,
            "tenant": request.tenant,
            "scope": {
                "repositories": repositories,
                "paths": paths,
                "environments": list(request.environments),
            },
            "authority": request.authority,
            "sensitivity": request.sensitivity,
            "provides": [],
            "requires": [],
            "conflicts": [],
            "lifecycle": request.lifecycle,
            "created_from": created_from,
            "integrity": {
                "lock": "integrity/capsule.lock",
                "signature": "integrity/signature.json" if signature else None,
            },
            "extensions": {"x-builder-profile": "CCS-2.1-m3-v1"},
        },
        "semantic_payload": {"atoms": [], "extensions": {}},
        "evidence_plane": {"records": [], "extensions": {}},
        "dependency_graph": {"edges": [], "extensions": {}},
        "replacement_contract": {
            "contract_id": f"{request.capsule_id}.source-grounding",
            "replaces": None,
            "preconditions": [
                "all P0/P1 atoms have exact evidence and trusted human approval"
            ],
            "target_effects": ["source-grounded payload is available"],
            "protected_invariants": ["unapproved candidates remain quarantined"],
            "allowed_scope": paths,
            "forbidden_spillover": [],
            "verification": {
                "static": ["uv run pytest tests/security/test_trust_promotion.py"],
                "behavioral": [
                    "uv run pytest tests/integration/test_build_pipeline.py"
                ],
                "differential": [],
            },
            "activation": {
                "risk": "high",
                "approval_required": True,
                "safe_boundary": "before-next-agent-action",
            },
            "rollback": {"pointer": "none:first-version", "compensating_action": None},
            "extensions": {},
        },
        "compression_policy": {
            "policy_version": "1.0.0",
            "classes": [
                {
                    "name": "P0_EXACT",
                    "rendering": "exact",
                    "lossy_compression": "forbidden",
                    "expansion_triggers": ["always"],
                    "ttl": None,
                },
                {
                    "name": "P1_STRUCTURED",
                    "rendering": "canonical_atom",
                    "lossy_compression": "validated_only",
                    "expansion_triggers": ["ambiguity"],
                    "ttl": None,
                },
                {
                    "name": "P2_EVIDENCE",
                    "rendering": "exact_excerpt_with_handle",
                    "lossy_compression": "excerpt_only",
                    "expansion_triggers": ["model_request"],
                    "ttl": None,
                },
                {
                    "name": "P3_SUMMARY",
                    "rendering": "source_grounded_summary",
                    "lossy_compression": "allowed",
                    "expansion_triggers": ["missing_detail"],
                    "ttl": None,
                },
                {
                    "name": "P4_TRANSIENT",
                    "rendering": "aggregate_or_drop",
                    "lossy_compression": "allowed",
                    "expansion_triggers": [],
                    "ttl": "P7D",
                },
            ],
            "extensions": {},
        },
        "tests_integrity": {
            "tests": [
                {
                    "test_id": "m3-source-grounding",
                    "kind": "static",
                    "path": "tests/static/m3-source-grounding.json",
                    "digest": _BUILDER_TEST_DIGEST,
                }
            ],
            "lock": {
                "capsule_dependencies": [],
                "source_commits": created_from,
                "compiler_version": "0.1.0",
                "adapter_versions": ["m3-builder:0.1.0"],
                "compression_policy_version": "1.0.0",
                "test_set_version": "0.1.0",
                "model_series": ["deterministic-parser"],
                "parameters": ["human-approval=required"],
                "runtime_config_digest": _BUILDER_TEST_DIGEST,
                "extensions": {},
            },
            "artifact_checksums": [
                {
                    "path": "tests/static/m3-source-grounding.json",
                    "digest": _BUILDER_TEST_DIGEST,
                }
            ],
            "signature_policy": signature_policy,
            "extensions": {},
        },
        "detached_signature": signature,
        "derived_artifacts": {},
        "runtime_sidecar": {},
    }


def _raw_template(request: BuildRequest) -> dict[str, Any]:
    if request.template is None:
        raw = _default_core(request)
    elif isinstance(request.template, Capsule):
        raw = capsule_wire_dict(request.template)
    elif isinstance(request.template, Mapping):
        try:
            raw = json.loads(
                json.dumps(request.template, ensure_ascii=False, allow_nan=False)
            )
        except (TypeError, ValueError) as error:
            raise BuildError("template is not a strict JSON object") from error
    else:
        raise TypeError("template must be Capsule, mapping, or None")
    if not isinstance(raw, dict):
        raise BuildError("template root must be an object")
    return raw


def _assemble(request: BuildRequest) -> tuple[Capsule, dict[str, bytes]]:
    if not request.atoms:
        raise BuildError("at least one validated atom is required")
    if request.quarantine is None:
        raise BuildError("an explicit quarantine trust boundary is required")
    seen_atoms: set[str] = set()
    records: list[dict[str, Any]] = []
    blobs: dict[str, bytes] = {}
    for atom in request.atoms:
        if not isinstance(atom, ValidatedAtom):
            raise BuildError("raw candidates cannot enter a capsule payload")
        request.quarantine.verify_validated(atom)
        if atom.atom_id in seen_atoms:
            raise BuildError("duplicate validated atom ID")
        seen_atoms.add(atom.atom_id)
        for binding in atom.evidence_bindings:
            records.append(_evidence_record(binding, atom.atom_id))
            if binding.mode == "CAS":
                existing = blobs.get(binding.content_digest)
                if existing is not None and existing != binding.source_bytes:
                    raise BuildError(
                        "one CAS digest maps to inconsistent evidence bytes"
                    )
                blobs[binding.content_digest] = binding.source_bytes
    raw = _raw_template(request)
    semantic_extensions = (
        raw.get("semantic_payload", {}).get("extensions", {})
        if isinstance(raw.get("semantic_payload"), Mapping)
        else {}
    )
    evidence_extensions = (
        raw.get("evidence_plane", {}).get("extensions", {})
        if isinstance(raw.get("evidence_plane"), Mapping)
        else {}
    )
    raw["semantic_payload"] = {
        "atoms": [_atom_record(atom, request.authority) for atom in request.atoms],
        "extensions": semantic_extensions,
    }
    raw["evidence_plane"] = {
        "records": records,
        "extensions": evidence_extensions,
    }
    raw["dependency_graph"] = {"edges": [], "extensions": {}}
    manifest = raw.get("control_manifest")
    if not isinstance(manifest, dict):
        raise BuildError("template manifest is missing")
    created_from, paths, repositories = _source_markers(request.atoms)
    manifest.update(
        {
            "capsule_id": request.capsule_id,
            "version": request.version,
            "owner": request.owner,
            "tenant": request.tenant,
            "authority": request.authority,
            "sensitivity": request.sensitivity,
            "lifecycle": request.lifecycle,
            "created_from": created_from,
            "content_digest": _ZERO_DIGEST,
        }
    )
    manifest["scope"] = {
        "repositories": repositories,
        "paths": paths,
        "environments": list(request.environments),
    }
    if request.detached_signature is not None:
        signature = copy.deepcopy(dict(request.detached_signature))
        raw["detached_signature"] = signature
        manifest["integrity"]["signature"] = "integrity/signature.json"
        raw["tests_integrity"]["signature_policy"] = {
            "algorithm": signature["algorithm"],
            "key_id": signature["key_id"],
            "input_profile": "CCS-2.1-signature-v1",
        }
    elif request.template is None:
        raw["detached_signature"] = None
        manifest["integrity"]["signature"] = None
    tests_integrity = raw.get("tests_integrity")
    if not isinstance(tests_integrity, dict):
        raise BuildError("template tests and integrity module is missing")
    lock = tests_integrity.get("lock")
    if not isinstance(lock, dict):
        raise BuildError("template integrity lock is missing")
    lock["source_commits"] = created_from
    tests_integrity["tests"] = [
        {
            "test_id": "m3-source-grounding",
            "kind": "static",
            "path": "tests/static/m3-source-grounding.json",
            "digest": _BUILDER_TEST_DIGEST,
        }
    ]
    tests_integrity["artifact_checksums"] = [
        {
            "path": "tests/static/m3-source-grounding.json",
            "digest": _BUILDER_TEST_DIGEST,
        }
    ]
    raw["derived_artifacts"] = {}
    raw["runtime_sidecar"] = {}
    try:
        candidate = Capsule.model_validate_json(
            json.dumps(raw, ensure_ascii=False, allow_nan=False)
        )
    except (TypeError, ValueError) as error:
        raise BuildError(
            "assembled capsule failed canonical model validation"
        ) from error
    raw["control_manifest"]["content_digest"] = canonical_digest(candidate)
    try:
        complete = Capsule.model_validate_json(
            json.dumps(raw, ensure_ascii=False, allow_nan=False)
        )
    except (TypeError, ValueError) as error:
        raise BuildError(
            "digested capsule failed canonical model validation"
        ) from error
    return complete, blobs


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_package(root: Path, capsule: Capsule, blobs: Mapping[str, bytes]) -> None:
    raw = capsule_wire_dict(capsule)
    paths = {
        "payload": root / "payload",
        "evidence": root / "evidence",
        "graph": root / "graph",
        "contracts": root / "contracts",
        "policies": root / "policies",
        "integrity": root / "integrity",
        "tests": root / "tests/static",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    root.joinpath("manifest.json").write_bytes(_json_bytes(raw["control_manifest"]))
    paths["payload"].joinpath("atoms.jsonl").write_bytes(
        b"".join(_json_bytes(atom) for atom in raw["semantic_payload"]["atoms"])
    )
    paths["evidence"].joinpath("source-map.jsonl").write_bytes(
        b"".join(_json_bytes(record) for record in raw["evidence_plane"]["records"])
    )
    paths["graph"].joinpath("dependencies.json").write_bytes(
        _json_bytes(raw["dependency_graph"])
    )
    paths["contracts"].joinpath("replacement.yaml").write_text(
        yaml.safe_dump(raw["replacement_contract"], allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )
    paths["policies"].joinpath("compression.yaml").write_text(
        yaml.safe_dump(raw["compression_policy"], allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )
    integrity = raw["tests_integrity"]
    lock = {
        "tests": integrity["tests"],
        "lock": integrity["lock"],
        "signature_policy": integrity["signature_policy"],
        "extensions": integrity["extensions"],
    }
    paths["integrity"].joinpath("capsule.lock").write_bytes(_json_bytes(lock))
    paths["tests"].joinpath("m3-source-grounding.json").write_bytes(_BUILDER_TEST_BYTES)
    paths["integrity"].joinpath("checksums.sha256").write_text(
        f"{_BUILDER_TEST_DIGEST}  tests/static/m3-source-grounding.json\n",
        encoding="utf-8",
    )
    signature = raw.get("detached_signature")
    if signature is not None:
        paths["integrity"].joinpath("signature.json").write_bytes(
            _json_bytes(signature)
        )
    payload_extensions = raw["semantic_payload"].get("extensions", {})
    if payload_extensions:
        paths["payload"].joinpath("metadata.json").write_bytes(
            _json_bytes({"extensions": payload_extensions})
        )
    evidence_extensions = raw["evidence_plane"].get("extensions", {})
    if evidence_extensions:
        paths["evidence"].joinpath("metadata.json").write_bytes(
            _json_bytes({"extensions": evidence_extensions})
        )
    for digest, data in blobs.items():
        scan_secrets(data)
        hex_digest = digest.removeprefix("sha256:")
        destination = root / "evidence/blobs/sha256" / hex_digest[:2] / hex_digest[2:]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def _validate_through_loader(
    capsule: Capsule, blobs: Mapping[str, bytes], package_path: Path | None
) -> tuple[Capsule, Path | None]:
    if package_path is None:
        with tempfile.TemporaryDirectory(
            prefix="contractcapsule-m3-"
        ) as temporary_name:
            root = Path(temporary_name).resolve()
            _write_package(root, capsule, blobs)
            return load_capsule(root), None
    destination = Path(package_path).resolve(strict=False)
    if destination.exists():
        raise BuildError("package destination must not already exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = Path(
        tempfile.mkdtemp(prefix=".contractcapsule-m3-", dir=destination.parent)
    ).resolve()
    try:
        _write_package(temporary_path, capsule, blobs)
        loaded = load_capsule(temporary_path)
        os.rename(temporary_path, destination)
        return loaded, destination
    except Exception:
        shutil.rmtree(temporary_path, ignore_errors=True)
        raise


def build_capsule(build_request: BuildRequest) -> DraftCapsule:
    """Build and validate one capsule through the public M2 package loader."""

    if not isinstance(build_request, BuildRequest):
        raise TypeError("build_request must be a BuildRequest")
    capsule, blobs = _assemble(build_request)
    loaded, package_path = _validate_through_loader(
        capsule, blobs, build_request.package_path
    )
    return DraftCapsule(
        loaded,
        tuple(atom.atom_id for atom in build_request.atoms),
        package_path,
        _loader_receipt=_LOADER_RECEIPT,
    )


def publish_draft(
    draft: DraftCapsule, principal: Principal, registry: Registry
) -> PublishedCapsule:
    """Publish only a loader-validated PUBLISHED draft through the public M2 Registry."""

    if (
        not isinstance(draft, DraftCapsule)
        or draft._loader_receipt is not _LOADER_RECEIPT
        or "load_capsule" not in draft.validation_pipeline
    ):
        raise BuildError("publication requires a public-loader validated draft")
    return registry.publish(draft.capsule, principal)
