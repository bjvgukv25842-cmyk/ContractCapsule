"""Canonical CCS-2.1 models for the seven immutable core modules."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import (
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from contractcapsule.models.base import (
    SAFE_RELATIVE_PATH_PATTERN,
    DateString,
    Digest,
    ExtensibleModel,
    MediaType,
    NonEmptyString,
    SemVer,
    StrictFrozenModel,
    TimestampString,
    freeze_json,
    is_canonical_https_uri,
    is_safe_relative_path,
    thaw_json,
)

PYTHON_RE_NON_WHITESPACE_SCHEMA_ATOM = (
    r"[^\u0009-\u000D\u001C-\u0020\u0085\u00A0\u1680"
    r"\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]"
)
SCHEMA_ABSOLUTE_END_ASSERTION = r"$(?![\u000A\u000D\u2028\u2029])"
DOI_URI_SCHEMA_PATTERN = (
    r"^doi:10\.[0-9]{4,9}/"
    f"{PYTHON_RE_NON_WHITESPACE_SCHEMA_ATOM}+"
    f"{SCHEMA_ABSOLUTE_END_ASSERTION}"
)
URN_URI_SCHEMA_PATTERN = (
    r"^urn:[a-z0-9][a-z0-9-]{0,31}:"
    f"{PYTHON_RE_NON_WHITESPACE_SCHEMA_ATOM}+"
    f"{SCHEMA_ABSOLUTE_END_ASSERTION}"
)
HTTPS_URI_SCHEMA_PATTERN = (
    r"^[\u0000-\u0020]*"
    r"[Hh][\t\r\n]*[Tt][\t\r\n]*[Tt][\t\r\n]*"
    r"[Pp][\t\r\n]*[Ss][\t\r\n]*:"
    r"[\t\r\n]*/[\t\r\n]*/"
)
EXTERNAL_URI_LEXICAL_SCHEMA: dict[str, Any] = {
    "anyOf": [
        {"pattern": HTTPS_URI_SCHEMA_PATTERN},
        {"pattern": DOI_URI_SCHEMA_PATTERN},
        {"pattern": URN_URI_SCHEMA_PATTERN},
    ]
}


class Scope(StrictFrozenModel):
    repositories: Annotated[tuple[NonEmptyString, ...], Field(min_length=1)]
    paths: Annotated[tuple[NonEmptyString, ...], Field(min_length=1)]
    environments: Annotated[tuple[NonEmptyString, ...], Field(min_length=1)]

    @field_validator("paths")
    @classmethod
    def _literal_scope_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not is_safe_relative_path(value) for value in values):
            raise ValueError("scope paths must be literal repository-relative patterns")
        return values


class IntegrityReferences(StrictFrozenModel):
    lock: NonEmptyString
    signature: NonEmptyString | None

    @field_validator("lock")
    @classmethod
    def _lock_path(cls, value: str) -> str:
        if value != "integrity/capsule.lock":
            raise ValueError("lock must use the canonical package path")
        return value

    @field_validator("signature")
    @classmethod
    def _signature_path(cls, value: str | None) -> str | None:
        if value is not None and value != "integrity/signature.json":
            raise ValueError("signature must use the canonical package path")
        return value


class ControlManifest(ExtensibleModel):
    spec_version: Literal["CCS-2.1"]
    canonical_profile: Literal["CCS-2.1-canonical-v1"]
    capsule_id: Annotated[
        str,
        Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)+(?:-[a-z0-9]+)*$"),
    ]
    version: SemVer
    content_digest: Digest
    owner: NonEmptyString
    tenant: NonEmptyString
    scope: Scope
    authority: NonEmptyString
    sensitivity: Literal["public", "internal", "confidential", "restricted"]
    provides: tuple[NonEmptyString, ...]
    requires: tuple[NonEmptyString, ...]
    conflicts: tuple[NonEmptyString, ...]
    lifecycle: Literal[
        "DRAFT", "VALIDATED", "PUBLISHED", "ACTIVE", "DEPRECATED", "REVOKED"
    ]
    created_from: tuple[NonEmptyString, ...]
    integrity: IntegrityReferences

    @model_validator(mode="after")
    def _scope_is_explicit(self) -> ControlManifest:
        if not self.scope.repositories or not self.scope.paths or not self.scope.environments:
            raise ValueError("manifest scope dimensions must all be non-empty")
        return self


class Validity(StrictFrozenModel):
    from_: DateString = Field(alias="from", serialization_alias="from")
    until: DateString | None


class Atom(ExtensibleModel):
    atom_id: NonEmptyString
    kind: Literal[
        "policy",
        "invariant",
        "fact",
        "decision",
        "procedure",
        "interface",
        "tool_contract",
        "example",
        "episodic_observation",
    ]
    statement: NonEmptyString
    modality: Literal["MUST", "SHOULD", "MAY", "INFORMATIVE"]
    scope: Annotated[tuple[NonEmptyString, ...], Field(min_length=1)]
    exceptions: tuple[NonEmptyString, ...]
    validity: Validity
    authority: NonEmptyString
    status: Literal["candidate", "validated", "deprecated", "revoked"]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    evidence_refs: tuple[NonEmptyString, ...]
    requires_atoms: tuple[NonEmptyString, ...]
    conflicts_with: tuple[NonEmptyString, ...]
    sensitivity: Literal["public", "internal", "confidential", "restricted"]
    compression_class: Literal[
        "P0_EXACT", "P1_STRUCTURED", "P2_EVIDENCE", "P3_SUMMARY", "P4_TRANSIENT"
    ]
    refresh_policy: NonEmptyString

    @model_validator(mode="after")
    def _formal_atoms_are_traceable(self) -> Atom:
        if self.status == "validated" and not self.evidence_refs:
            raise ValueError("validated atoms require evidence")
        if not self.scope:
            raise ValueError("atom scope must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return self


class SemanticPayload(ExtensibleModel):
    atoms: Annotated[tuple[Atom, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _unique_atoms(self) -> SemanticPayload:
        identifiers = [atom.atom_id for atom in self.atoms]
        if not identifiers or len(identifiers) != len(set(identifiers)):
            raise ValueError("atom identifiers must be non-empty and unique")
        return self


class EvidenceBase(ExtensibleModel):
    evidence_id: NonEmptyString
    atom_ids: Annotated[tuple[NonEmptyString, ...], Field(min_length=1)]
    content_digest: Digest
    media_type: MediaType
    captured_at: TimestampString
    retention: NonEmptyString
    access_policy: NonEmptyString
    validation: Literal["verified", "stale", "unavailable", "revoked"]

    @model_validator(mode="after")
    def _mapped_atoms_present(self) -> EvidenceBase:
        if not self.atom_ids:
            raise ValueError("evidence must map at least one atom")
        return self


class CASEvidence(EvidenceBase):
    mode: Literal["CAS"]


class GitLocator(StrictFrozenModel):
    symbol_or_heading: NonEmptyString
    start_line: Annotated[int, Field(ge=1, le=2**53 - 1)]
    end_line: Annotated[int, Field(ge=1, le=2**53 - 1)]
    span_digest: Digest

    @model_validator(mode="after")
    def _ordered_lines(self) -> GitLocator:
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class GitImmutableEvidence(EvidenceBase):
    mode: Literal["GIT_IMMUTABLE"]
    repository: NonEmptyString
    revision: Annotated[
        str,
        Field(pattern=r"^(?:sha1:[0-9a-f]{40}|sha256:[0-9a-f]{64})$"),
    ]
    path: NonEmptyString = Field(
        json_schema_extra={"pattern": SAFE_RELATIVE_PATH_PATTERN}
    )
    locator: GitLocator

    @field_validator("repository")
    @classmethod
    def _canonical_repository(cls, value: str) -> str:
        if not is_canonical_https_uri(value):
            raise ValueError("repository identity must be canonical HTTPS")
        return value

    @field_validator("path")
    @classmethod
    def _literal_repository_path(cls, value: str) -> str:
        if not is_safe_relative_path(value):
            raise ValueError("Git evidence path must be a literal repository-relative path")
        return value


class ExternalImmutableEvidence(EvidenceBase):
    mode: Literal["EXTERNAL_IMMUTABLE"]
    uri: NonEmptyString = Field(json_schema_extra=EXTERNAL_URI_LEXICAL_SCHEMA)
    source: NonEmptyString
    verification_method: NonEmptyString

    @field_validator("uri")
    @classmethod
    def _canonical_external_locator(cls, value: str) -> str:
        persistent = bool(re.fullmatch(r"(?:doi:10\.[0-9]{4,9}/\S+|urn:[a-z0-9][a-z0-9-]{0,31}:\S+)", value))
        if not (persistent or is_canonical_https_uri(value)):
            raise ValueError("external locator must be canonical HTTPS, DOI, or URN")
        return value


EvidenceRecord = Annotated[
    CASEvidence | GitImmutableEvidence | ExternalImmutableEvidence,
    Field(discriminator="mode"),
]


class EvidencePlane(ExtensibleModel):
    records: Annotated[tuple[EvidenceRecord, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _unique_evidence(self) -> EvidencePlane:
        identifiers = [record.evidence_id for record in self.records]
        if not identifiers or len(identifiers) != len(set(identifiers)):
            raise ValueError("evidence identifiers must be non-empty and unique")
        return self


class DependencyEdge(ExtensibleModel):
    source: NonEmptyString
    target: NonEmptyString
    edge_type: Literal["requires", "provides", "conflicts", "replaces", "optional"]
    version_constraint: NonEmptyString | None
    mandatory: bool


class DependencyGraph(ExtensibleModel):
    edges: tuple[DependencyEdge, ...]

    @model_validator(mode="after")
    def _unique_edges(self) -> DependencyGraph:
        keys = [(edge.source, edge.target, edge.edge_type) for edge in self.edges]
        if len(keys) != len(set(keys)):
            raise ValueError("dependency edges must be unique")
        return self


class VerificationCommands(StrictFrozenModel):
    static: tuple[NonEmptyString, ...]
    behavioral: tuple[NonEmptyString, ...]
    differential: tuple[NonEmptyString, ...]


class ActivationPolicy(StrictFrozenModel):
    risk: Literal["low", "medium", "high", "critical"]
    approval_required: bool
    safe_boundary: Literal["before-next-agent-action"]


class RollbackPolicy(StrictFrozenModel):
    pointer: NonEmptyString
    compensating_action: NonEmptyString | None


class ReplacementContract(ExtensibleModel):
    contract_id: NonEmptyString
    replaces: NonEmptyString | None
    preconditions: tuple[NonEmptyString, ...]
    target_effects: Annotated[tuple[NonEmptyString, ...], Field(min_length=1)]
    protected_invariants: Annotated[
        tuple[NonEmptyString, ...], Field(min_length=1)
    ]
    allowed_scope: tuple[NonEmptyString, ...]
    forbidden_spillover: tuple[NonEmptyString, ...]
    verification: VerificationCommands
    activation: ActivationPolicy
    rollback: RollbackPolicy

    @field_validator("allowed_scope", "forbidden_spillover")
    @classmethod
    def _literal_contract_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not is_safe_relative_path(value) for value in values):
            raise ValueError("contract scopes must be literal repository-relative patterns")
        return values

    @model_validator(mode="after")
    def _behavioral_contract_is_nonempty(self) -> ReplacementContract:
        if not self.target_effects or not self.protected_invariants:
            raise ValueError("replacement contract requires effects and protected invariants")
        return self


class CompressionClassPolicy(StrictFrozenModel):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"name": {"const": "P0_EXACT"}},
                        "required": ["name"],
                    },
                    "then": {
                        "properties": {
                            "rendering": {"const": "exact"},
                            "lossy_compression": {"const": "forbidden"},
                        }
                    },
                }
            ]
        }
    )

    name: Literal[
        "P0_EXACT", "P1_STRUCTURED", "P2_EVIDENCE", "P3_SUMMARY", "P4_TRANSIENT"
    ]
    rendering: NonEmptyString
    lossy_compression: Literal[
        "forbidden", "validated_only", "excerpt_only", "allowed"
    ]
    expansion_triggers: tuple[NonEmptyString, ...]
    ttl: Annotated[str, Field(pattern=r"^P[0-9]+D$")] | None

    @model_validator(mode="after")
    def _p0_is_exact(self) -> CompressionClassPolicy:
        if self.name == "P0_EXACT" and (
            self.rendering != "exact" or self.lossy_compression != "forbidden"
        ):
            raise ValueError("P0 must render exactly and forbid lossy compression")
        return self


class CompressionPolicy(ExtensibleModel):
    policy_version: SemVer
    classes: Annotated[
        tuple[CompressionClassPolicy, ...],
        Field(
            min_length=5,
            max_length=5,
            json_schema_extra={
                "allOf": [
                    {
                        "contains": {
                            "properties": {"name": {"const": name}},
                            "required": ["name"],
                        },
                        "minContains": 1,
                        "maxContains": 1,
                    }
                    for name in (
                        "P0_EXACT",
                        "P1_STRUCTURED",
                        "P2_EVIDENCE",
                        "P3_SUMMARY",
                        "P4_TRANSIENT",
                    )
                ]
            },
        ),
    ]

    @model_validator(mode="after")
    def _all_classes_exactly_once(self) -> CompressionPolicy:
        expected = {
            "P0_EXACT",
            "P1_STRUCTURED",
            "P2_EVIDENCE",
            "P3_SUMMARY",
            "P4_TRANSIENT",
        }
        names = [item.name for item in self.classes]
        if len(names) != len(set(names)) or set(names) != expected:
            raise ValueError("compression policy must define P0-P4 exactly once")
        return self


class TestDefinition(StrictFrozenModel):
    test_id: NonEmptyString
    kind: Literal["static", "evidence", "compression", "behavioral"]
    path: NonEmptyString
    digest: Digest

    @field_validator("path")
    @classmethod
    def _test_path(cls, value: str) -> str:
        allowed = any(
            is_safe_relative_path(value, prefix=prefix)
            for prefix in ("tests/static/", "tests/behavioral/", "tests/compression/")
        )
        if not allowed:
            raise ValueError("test artifact must be under an allowed tests directory")
        return value


class CapsuleDependency(StrictFrozenModel):
    capsule_id: NonEmptyString
    version: SemVer
    digest: Digest


class IntegrityLock(ExtensibleModel):
    capsule_dependencies: tuple[CapsuleDependency, ...]
    source_commits: tuple[NonEmptyString, ...]
    compiler_version: SemVer
    adapter_versions: tuple[NonEmptyString, ...]
    compression_policy_version: SemVer
    test_set_version: SemVer
    model_series: tuple[NonEmptyString, ...]
    parameters: tuple[NonEmptyString, ...]
    runtime_config_digest: Digest


class ArtifactChecksum(StrictFrozenModel):
    path: NonEmptyString
    digest: Digest

    @field_validator("path")
    @classmethod
    def _artifact_path(cls, value: str) -> str:
        if not is_safe_relative_path(value, prefix="tests/"):
            raise ValueError("integrity checksum path must be a safe tests path")
        return value


class SignaturePolicy(StrictFrozenModel):
    algorithm: NonEmptyString
    key_id: NonEmptyString
    input_profile: Literal["CCS-2.1-signature-v1"]


class TestsIntegrity(ExtensibleModel):
    tests: Annotated[tuple[TestDefinition, ...], Field(min_length=1)]
    lock: IntegrityLock
    artifact_checksums: tuple[ArtifactChecksum, ...]
    signature_policy: SignaturePolicy

    @model_validator(mode="after")
    def _tests_are_locked(self) -> TestsIntegrity:
        tests = [(item.path, item.digest) for item in self.tests]
        checksums = [(item.path, item.digest) for item in self.artifact_checksums]
        if not tests or len(tests) != len(set(tests)):
            raise ValueError("test definitions must be non-empty and unique")
        if checksums != tests:
            raise ValueError("artifact checksums must exactly match ordered test definitions")
        return self


class DetachedSignature(StrictFrozenModel):
    algorithm: NonEmptyString
    key_id: NonEmptyString
    value: NonEmptyString
    envelope: Mapping[str, Any]

    @field_validator("envelope", mode="after")
    @classmethod
    def _freeze_envelope(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        frozen = freeze_json(value)
        if not isinstance(frozen, Mapping):  # pragma: no cover
            raise TypeError("signature envelope must be an object")
        return frozen

    @field_serializer("envelope")
    def _serialize_envelope(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return thaw_json(value)


class Capsule(StrictFrozenModel):
    """Seven A-zone modules plus explicitly non-identity envelope and sidecars."""

    control_manifest: ControlManifest
    semantic_payload: SemanticPayload
    evidence_plane: EvidencePlane
    dependency_graph: DependencyGraph
    replacement_contract: ReplacementContract
    compression_policy: CompressionPolicy
    tests_integrity: TestsIntegrity
    detached_signature: DetachedSignature | None = None
    derived_artifacts: Mapping[str, Any] = Field(default_factory=dict)
    runtime_sidecar: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("derived_artifacts", "runtime_sidecar", mode="after")
    @classmethod
    def _freeze_non_core(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        frozen = freeze_json(value)
        if not isinstance(frozen, Mapping):  # pragma: no cover
            raise TypeError("non-core data must be an object")
        return frozen

    @field_serializer("derived_artifacts", "runtime_sidecar")
    def _serialize_non_core(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return thaw_json(value)

    @model_validator(mode="after")
    def _references_are_closed(self) -> Capsule:
        atom_ids = {atom.atom_id for atom in self.semantic_payload.atoms}
        evidence_ids = {record.evidence_id for record in self.evidence_plane.records}
        referenced_evidence = {
            evidence_id
            for atom in self.semantic_payload.atoms
            for evidence_id in atom.evidence_refs
        }
        if not referenced_evidence <= evidence_ids:
            raise ValueError("atom evidence references must resolve in the Evidence Plane")
        if any(not set(record.atom_ids) <= atom_ids for record in self.evidence_plane.records):
            raise ValueError("Evidence Plane atom references must resolve in the payload")
        atom_bindings = {
            (atom.atom_id, evidence_id)
            for atom in self.semantic_payload.atoms
            for evidence_id in atom.evidence_refs
        }
        evidence_bindings = {
            (atom_id, record.evidence_id)
            for record in self.evidence_plane.records
            for atom_id in record.atom_ids
        }
        if atom_bindings != evidence_bindings:
            raise ValueError("atom and Evidence Plane bindings must be reciprocal")
        signature_declared = self.control_manifest.integrity.signature is not None
        signature_present = self.detached_signature is not None
        if signature_declared != signature_present:
            raise ValueError("manifest signature declaration and envelope must agree")
        if self.control_manifest.lifecycle == "PUBLISHED" and not signature_present:
            raise ValueError("PUBLISHED Capsule requires a detached signature envelope")
        if self.detached_signature is not None and (
            self.detached_signature.algorithm
            != self.tests_integrity.signature_policy.algorithm
            or self.detached_signature.key_id
            != self.tests_integrity.signature_policy.key_id
        ):
            raise ValueError("detached signature metadata must match the signature policy")
        return self
