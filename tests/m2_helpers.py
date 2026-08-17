from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from contractcapsule.audit.quarantine import (
        ApprovalAuthority,
        QuarantineStore,
        ValidatedAtom,
    )
    from contractcapsule.build.publish import DraftCapsule
    from contractcapsule.models import Principal
    from contractcapsule.storage.cas import FilesystemCAS
    from contractcapsule.storage.registry import PublishedCapsule, Registry

ZERO_DIGEST = "sha256:" + ("0" * 64)
CAS_BYTES = b"authoritative evidence\n"
CAS_DIGEST = "sha256:" + hashlib.sha256(CAS_BYTES).hexdigest()
TEST_BYTES = b'{"expected":"pass"}\n'
TEST_DIGEST = "sha256:" + hashlib.sha256(TEST_BYTES).hexdigest()


def sample_capsule_data(
    *, evidence_modes: tuple[str, ...] = ("CAS",)
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    evidence_refs: list[str] = []
    if "CAS" in evidence_modes:
        records.append(
            {
                "mode": "CAS",
                "evidence_id": "ev-cas-1",
                "atom_ids": ["auth.token-ttl"],
                "content_digest": CAS_DIGEST,
                "media_type": "text/plain",
                "captured_at": "2026-08-01T00:00:00Z",
                "retention": "follow-source-policy",
                "access_policy": "team-auth",
                "validation": "verified",
                "extensions": {"x-source-tier": "authoritative"},
            }
        )
        evidence_refs.append("ev-cas-1")
    if "GIT_IMMUTABLE" in evidence_modes:
        records.append(
            {
                "mode": "GIT_IMMUTABLE",
                "evidence_id": "ev-git-1",
                "atom_ids": ["auth.token-ttl"],
                "content_digest": "sha256:" + ("1" * 64),
                "media_type": "text/markdown",
                "captured_at": "2026-08-01T00:00:00Z",
                "retention": "follow-source-policy",
                "access_policy": "team-auth",
                "validation": "verified",
                "repository": "https://github.com/example/api",
                "revision": "sha1:" + ("a" * 40),
                "path": "docs/security/auth.md",
                "locator": {
                    "symbol_or_heading": "Access token lifetime",
                    "start_line": 41,
                    "end_line": 44,
                    "span_digest": "sha256:" + ("2" * 64),
                },
                "extensions": {},
            }
        )
        evidence_refs.append("ev-git-1")
    if "EXTERNAL_IMMUTABLE" in evidence_modes:
        records.append(
            {
                "mode": "EXTERNAL_IMMUTABLE",
                "evidence_id": "ev-external-1",
                "atom_ids": ["auth.token-ttl"],
                "content_digest": "sha256:" + ("3" * 64),
                "media_type": "text/html",
                "captured_at": "2026-08-01T00:00:00Z",
                "retention": "metadata-only",
                "access_policy": "team-auth",
                "validation": "verified",
                "uri": "https://example.com/security/auth",
                "source": "Example security policy",
                "verification_method": "publisher-checksum",
                "extensions": {},
            }
        )
        evidence_refs.append("ev-external-1")

    return {
        "control_manifest": {
            "spec_version": "CCS-2.1",
            "canonical_profile": "CCS-2.1-canonical-v1",
            "capsule_id": "com.example.auth-policy",
            "version": "2.3.0",
            "content_digest": ZERO_DIGEST,
            "owner": "team-auth",
            "tenant": "example",
            "scope": {
                "repositories": ["example/api"],
                "paths": ["src/auth/**"],
                "environments": ["dev", "staging", "prod"],
            },
            "authority": "approved-project-policy",
            "sensitivity": "internal",
            "provides": ["auth.jwt-policy/v2"],
            "requires": ["security.baseline@>=3,<4"],
            "conflicts": ["auth.legacy-session@<2"],
            "lifecycle": "PUBLISHED",
            "created_from": ["git:example/api@sha1:" + ("a" * 40)],
            "integrity": {
                "lock": "integrity/capsule.lock",
                "signature": "integrity/signature.json",
            },
            "extensions": {"x-policy-tier": "critical"},
        },
        "semantic_payload": {
            "atoms": [
                {
                    "atom_id": "auth.token-ttl",
                    "kind": "invariant",
                    "statement": "Production access tokens expire within 15 minutes.",
                    "modality": "MUST",
                    "scope": ["environment:prod", "path:src/auth/**"],
                    "exceptions": [],
                    "validity": {"from": "2026-07-01", "until": None},
                    "authority": "approved-project-policy",
                    "status": "validated",
                    "confidence": 1.0,
                    "evidence_refs": evidence_refs,
                    "requires_atoms": [],
                    "conflicts_with": ["auth.jwt.legacy-ttl"],
                    "sensitivity": "internal",
                    "compression_class": "P0_EXACT",
                    "refresh_policy": "on-source-change",
                    "extensions": {},
                }
            ],
            "extensions": {"x-payload-state": "validated"},
        },
        "evidence_plane": {
            "records": records,
            "extensions": {"x-evidence-retention": "locked"},
        },
        "dependency_graph": {
            "edges": [
                {
                    "source": "auth.token-ttl",
                    "target": "security.clock-skew-limit",
                    "edge_type": "requires",
                    "version_constraint": ">=1,<2",
                    "mandatory": True,
                    "extensions": {},
                }
            ],
            "extensions": {},
        },
        "replacement_contract": {
            "contract_id": "auth.jwt-policy.v2",
            "replaces": "com.example.auth-policy@1.9.0",
            "preconditions": ["repository tests are green"],
            "target_effects": ["access token TTL changes from 30m to 15m"],
            "protected_invariants": ["refresh flow remains compatible"],
            "allowed_scope": ["src/auth/**"],
            "forbidden_spillover": ["billing/**"],
            "verification": {
                "static": ["make lint"],
                "behavioral": ["make test-auth"],
                "differential": ["tests/contracts/auth-noninterference.yaml"],
            },
            "activation": {
                "risk": "high",
                "approval_required": True,
                "safe_boundary": "before-next-agent-action",
            },
            "rollback": {
                "pointer": "com.example.auth-policy@1.9.0",
                "compensating_action": "revoke-new-tokens",
            },
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
                    "expansion_triggers": ["ambiguity", "conflict", "high_risk"],
                    "ttl": None,
                },
                {
                    "name": "P2_EVIDENCE",
                    "rendering": "exact_excerpt_with_handle",
                    "lossy_compression": "excerpt_only",
                    "expansion_triggers": ["model_request", "validator_request"],
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
                    "test_id": "schema-core",
                    "kind": "static",
                    "path": "tests/static/schema-test.json",
                    "digest": TEST_DIGEST,
                }
            ],
            "lock": {
                "capsule_dependencies": [
                    {
                        "capsule_id": "security.baseline",
                        "version": "3.2.0",
                        "digest": "sha256:" + ("4" * 64),
                    }
                ],
                "source_commits": ["git:example/api@sha1:" + ("a" * 40)],
                "compiler_version": "0.1.0",
                "adapter_versions": ["codex:unavailable"],
                "compression_policy_version": "1.0.0",
                "test_set_version": "1.0.0",
                "model_series": ["coding-agent-unspecified"],
                "parameters": ["temperature=unspecified"],
                "runtime_config_digest": "sha256:" + ("5" * 64),
                "extensions": {},
            },
            "artifact_checksums": [
                {"path": "tests/static/schema-test.json", "digest": TEST_DIGEST}
            ],
            "signature_policy": {
                "algorithm": "ed25519",
                "key_id": "test-key",
                "input_profile": "CCS-2.1-signature-v1",
            },
            "extensions": {},
        },
        "detached_signature": {
            "algorithm": "ed25519",
            "key_id": "test-key",
            "value": "base64:AA==",
            "envelope": {"x-transport": "test-only"},
        },
        "derived_artifacts": {
            "embeddings": {"model": "test", "values": [0.1]},
            "cache": {"hit": False},
            "compiled_view": {"id": "view-1"},
            "index": {"version": 1},
        },
        "runtime_sidecar": {
            "logs": ["not identity"],
            "observations": ["not identity"],
            "timestamp": "2026-08-02T00:00:00Z",
        },
    }


def clone(data: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(data)


def capsule_with_digest(data: dict[str, Any] | None = None):
    from contractcapsule.models import Capsule
    from contractcapsule.models.canonical import canonical_digest

    raw = clone(data or sample_capsule_data())
    capsule = Capsule.model_validate_json(json.dumps(raw, ensure_ascii=False))
    raw["control_manifest"]["content_digest"] = canonical_digest(capsule)
    return Capsule.model_validate_json(json.dumps(raw, ensure_ascii=False))


def write_package(
    root: Path,
    data: dict[str, Any] | None = None,
    *,
    include_cas_blob: bool = True,
) -> tuple[Path, dict[str, Any]]:
    from pydantic import ValidationError

    from contractcapsule.models import Capsule
    from contractcapsule.models.canonical import canonical_digest

    raw = clone(data or sample_capsule_data())
    try:
        capsule = Capsule.model_validate_json(json.dumps(raw, ensure_ascii=False))
        raw["control_manifest"]["content_digest"] = canonical_digest(capsule)
    except ValidationError:
        # Invalid-package tests need raw bytes that fail inside the loader.
        pass

    package = root / "capsule"
    files: dict[str, Any] = {
        "manifest.json": raw["control_manifest"],
        "payload/atoms.jsonl": raw["semantic_payload"]["atoms"],
        "payload/metadata.json": {"extensions": raw["semantic_payload"]["extensions"]},
        "evidence/source-map.jsonl": raw["evidence_plane"]["records"],
        "evidence/metadata.json": {"extensions": raw["evidence_plane"]["extensions"]},
        "graph/dependencies.json": raw["dependency_graph"],
        "contracts/replacement.yaml": raw["replacement_contract"],
        "policies/compression.yaml": raw["compression_policy"],
        "integrity/capsule.lock": {
            "tests": raw["tests_integrity"]["tests"],
            "lock": raw["tests_integrity"]["lock"],
            "signature_policy": raw["tests_integrity"]["signature_policy"],
            "extensions": raw["tests_integrity"]["extensions"],
        },
        "integrity/signature.json": raw["detached_signature"],
    }
    for relative, value in files.items():
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith(".jsonl"):
            target.write_text(
                "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in value),
                encoding="utf-8",
            )
        else:
            target.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    checksum_path = package / "integrity/checksums.sha256"
    checksum_path.write_text(
        f"{TEST_DIGEST}  tests/static/schema-test.json\n", encoding="utf-8"
    )
    test_path = package / "tests/static/schema-test.json"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_bytes(TEST_BYTES)

    if include_cas_blob and any(
        item["mode"] == "CAS" for item in raw["evidence_plane"]["records"]
    ):
        hex_digest = CAS_DIGEST.removeprefix("sha256:")
        blob_path = package / "evidence/blobs/sha256" / hex_digest[:2] / hex_digest[2:]
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_bytes(CAS_BYTES)
    return package, raw


@dataclass(slots=True)
class TrustedM3TestHarness:
    """Build P0/P1 Registry fixtures through the real M3 trust pipeline."""

    root: Path
    cas: FilesystemCAS
    authority: ApprovalAuthority
    store: QuarantineStore
    principal: Principal
    _source_index: int = 0
    _package_index: int = 0

    @classmethod
    def create(
        cls,
        root: Path,
        cas: FilesystemCAS,
        *,
        principal_id: str = "publisher",
    ) -> TrustedM3TestHarness:
        from contractcapsule.audit.quarantine import ApprovalAuthority, QuarantineStore
        from contractcapsule.models import Principal

        authority = ApprovalAuthority({"reviewer": b"m2-migration-test-secret"})
        return cls(
            root=Path(root).resolve(),
            cas=cas,
            authority=authority,
            store=QuarantineStore(trust_root=authority.trust_root()),
            principal=Principal(principal_id),
        )

    def promote_source(
        self,
        source_bytes: bytes = CAS_BYTES,
        *,
        compression_class: str = "P1_STRUCTURED",
    ) -> ValidatedAtom:
        from contractcapsule.build.atomize import (
            bind_evidence,
            extract_candidate_atoms,
        )
        from contractcapsule.build.ingest import SourceInput, snapshot_source

        self._source_index += 1
        source_path = (
            self.root / "m3-trusted-sources" / f"source-{self._source_index}.txt"
        )
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(source_bytes)
        snapshot = snapshot_source(
            SourceInput(
                path=source_path,
                mode="CAS",
                access_policy="team-auth",
                cas=self.cas,
                quarantine=self.store,
                generated=True,
            ),
            self.principal,
        )
        candidate = extract_candidate_atoms(snapshot)[0]
        if compression_class not in {"P0_EXACT", "P1_STRUCTURED"}:
            raise ValueError("M2 Registry migration helper supports only P0/P1")
        # The frozen extractor intentionally emits P1. This test-only harness changes
        # the pre-approval candidate so both mandatory Registry branches exercise the
        # same real Evidence -> approval -> promotion -> loader flow.
        object.__setattr__(candidate, "compression_class", compression_class)
        binding = bind_evidence(candidate, snapshot)
        approval = self.authority.issue(candidate, (binding,), "reviewer")
        return self.store.promote(candidate.candidate_id, approval)

    def build_draft(
        self,
        *,
        validated_atom: ValidatedAtom | None = None,
        source_bytes: bytes = CAS_BYTES,
        capsule_id: str = "com.example.auth-policy",
        version: str = "2.3.0",
        authority: str = "approved-project-policy",
        detached_signature: Mapping[str, Any] | None = None,
        compression_class: str = "P1_STRUCTURED",
    ) -> DraftCapsule:
        from contractcapsule.build.publish import BuildRequest, build_capsule

        atom = validated_atom or self.promote_source(
            source_bytes, compression_class=compression_class
        )
        self._package_index += 1
        package_path = (
            self.root / "m3-trusted-packages" / f"package-{self._package_index}"
        )
        signature = detached_signature or {
            "algorithm": "m3-test-only",
            "key_id": "m3-test-key",
            "value": "test-signature-not-production",
            "envelope": {"x-purpose": "M2 test-contract migration"},
        }
        return build_capsule(
            BuildRequest(
                atoms=(atom,),
                quarantine=self.store,
                capsule_id=capsule_id,
                version=version,
                owner="team-auth",
                tenant="example",
                authority=authority,
                sensitivity="internal",
                lifecycle="PUBLISHED",
                environments=("dev", "staging", "prod"),
                package_path=package_path,
                detached_signature=signature,
            )
        )

    def publish(
        self,
        draft: DraftCapsule,
        registry: Registry,
        principal: Principal | None = None,
    ) -> PublishedCapsule:
        from contractcapsule.build.publish import publish_draft

        return publish_draft(draft, principal or self.principal, registry)
