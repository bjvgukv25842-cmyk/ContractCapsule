"""Immutable B-zone runtime contracts; construction never authorizes activation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    InstanceOf,
    field_serializer,
    field_validator,
    model_validator,
)

from contractcapsule.models.base import (
    Digest,
    NonEmptyString,
    Principal,
    SemVer,
    StrictFrozenModel,
    TimestampString,
    freeze_json,
    is_safe_relative_path,
    thaw_json,
)
from contractcapsule.models.canonical import canonical_json_bytes, capsule_wire_dict
from contractcapsule.models.core import Atom
from contractcapsule.storage.registry import PublishedCapsule


def _unique_strings(value: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(set(value)))


StringSet = Annotated[tuple[NonEmptyString, ...], AfterValidator(_unique_strings)]
Count = Annotated[int, Field(ge=0, le=2**53 - 1)]
SignedCount = Annotated[int, Field(ge=-(2**53 - 1), le=2**53 - 1)]


def _json_map(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen = freeze_json(value)
    if not isinstance(frozen, Mapping):
        raise ValueError("runtime configuration must be a JSON object")  # noqa: TRY004
    return frozen


def _exact_publication(value: object) -> PublishedCapsule:
    if type(value) is not PublishedCapsule:
        raise ValueError("capsules require exact PublishedCapsule objects")
    return value


def _exact_principal(value: object) -> Principal:
    if type(value) is not Principal:
        raise ValueError("principal requires an exact Principal object")
    return value


class CapsuleRef(StrictFrozenModel):
    capsule_id: NonEmptyString
    version: SemVer
    digest: Digest

    @property
    def key(self) -> str:
        return f"{self.capsule_id}@{self.version}#{self.digest}"


class TaskContext(StrictFrozenModel):
    task_id: NonEmptyString
    tenant: NonEmptyString
    repository: NonEmptyString
    paths: Annotated[StringSet, Field(min_length=1)]
    environment: NonEmptyString
    text: str
    risk: Literal["low", "medium", "high", "critical"] = "low"
    required_interfaces: StringSet = ()
    required_atom_ids: StringSet = ()

    @field_validator("paths")
    @classmethod
    def _literal_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for path in value:
            if not is_safe_relative_path(path) or any(char in path for char in "*?[]"):
                raise ValueError(
                    "task paths must be literal safe repository-relative files"
                )
        return value


class ViewBudget(StrictFrozenModel):
    model_input_tokens: Count
    system_tokens: Count = 0
    conversation_tokens: Count = 0
    tools_tokens: Count = 0
    safety_headroom_tokens: Count = 0

    @property
    def available(self) -> int:
        return (
            self.model_input_tokens
            - self.system_tokens
            - self.conversation_tokens
            - self.tools_tokens
            - self.safety_headroom_tokens
        )

    @model_validator(mode="after")
    def _nonnegative_available(self) -> ViewBudget:
        if self.available < 0:
            raise ValueError("reserved tokens exceed the model input budget")
        return self


class CompileRequest(StrictFrozenModel):
    """Nominal inputs only; Registry must revalidate every publication before use.

    Use compile_request_projection for replay identity, not automatic dataclass
    serialization. Services are supplied explicitly outside this request.
    """

    capsules: tuple[
        Annotated[InstanceOf[PublishedCapsule], BeforeValidator(_exact_publication)],
        ...,
    ]
    task: TaskContext
    principal: Annotated[InstanceOf[Principal], BeforeValidator(_exact_principal)]
    budget: ViewBudget
    as_of: TimestampString
    model_id: NonEmptyString
    tokenizer_profile: NonEmptyString
    renderer_version: NonEmptyString = "ccs-neutral/1.0.0"
    runtime_config: Mapping[str, Any] = Field(
        default_factory=lambda: MappingProxyType({})
    )
    expected_manifest_digest: Digest | None = None

    @field_validator("runtime_config")
    @classmethod
    def _freeze_config(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _json_map(value)

    @field_serializer("runtime_config")
    def _serialize_config(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return dict(thaw_json(value))


class Eligibility(StrictFrozenModel):
    """Local admission, not collective view validity or activation permission."""

    allowed: bool
    atom_ids: StringSet = ()
    blockers: StringSet = ()

    @model_validator(mode="after")
    def _consistent_admission(self) -> Eligibility:
        if (not self.allowed and self.atom_ids) or (self.allowed and self.blockers):
            raise ValueError("admission result is contradictory")
        return self


class RankedAtom(StrictFrozenModel):
    atom: Atom
    score: float
    matched: bool

    @field_validator("score", mode="before")
    @classmethod
    def _strict_score(cls, value: object) -> float:
        if type(value) is not float:
            raise ValueError("score must be a float without coercion")
        return value


class Conflict(StrictFrozenModel):
    source: NonEmptyString
    target: NonEmptyString
    reason: NonEmptyString

    @model_validator(mode="after")
    def _ordered_endpoints(self) -> Conflict:
        source, target = sorted((self.source, self.target))
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "target", target)
        return self


class EvidenceHandle(StrictFrozenModel):
    capsule: CapsuleRef
    evidence_id: NonEmptyString
    atom_ids: StringSet
    mode: Literal["CAS", "GIT_IMMUTABLE", "EXTERNAL_IMMUTABLE"]
    content_digest: Digest
    span_digest: Digest | None
    resolver_version: NonEmptyString

    @property
    def handle_id(self) -> str:
        return (
            "sha256:"
            + hashlib.sha256(
                canonical_json_bytes(self.model_dump(mode="json"))
            ).hexdigest()
        )


class EvidenceMaterial(StrictFrozenModel):
    handle: EvidenceHandle
    excerpt: str
    full_text: str


class DecisionRecord(StrictFrozenModel):
    """Public records may describe admitted atoms only; denial counts are aggregate."""

    capsule: CapsuleRef
    atom_id: NonEmptyString
    outcome: Literal["selected", "excluded"]
    reason: NonEmptyString


class ServiceStamp(StrictFrozenModel):
    name: NonEmptyString
    version: NonEmptyString
    config_digest: Digest


class ProviderWitness(StrictFrozenModel):
    consumer: CapsuleRef | None
    requirement: NonEmptyString
    provider: CapsuleRef
    atom_ids: StringSet


class ClosureLink(StrictFrozenModel):
    source: NonEmptyString
    target: NonEmptyString


class TokenAccounting(StrictFrozenModel):
    total: Count
    available: Count
    sections: Mapping[NonEmptyString, Count]
    boundary_adjustment: SignedCount

    @field_validator("sections")
    @classmethod
    def _freeze_sections(cls, value: Mapping[str, int]) -> Mapping[str, int]:
        return MappingProxyType(dict(value))

    @field_serializer("sections")
    def _serialize_sections(self, value: Mapping[str, int]) -> dict[str, int]:
        return dict(value)

    @model_validator(mode="after")
    def _consistent_total(self) -> TokenAccounting:
        if self.total != sum(self.sections.values()) + self.boundary_adjustment:
            raise ValueError(
                "total tokens do not match sections and boundary adjustment"
            )
        return self


class ValidationReport(StrictFrozenModel):
    valid: bool
    blockers: StringSet = ()

    @model_validator(mode="after")
    def _consistent_validation(self) -> ValidationReport:
        if self.valid != (not self.blockers):
            raise ValueError("validity must match the absence of blockers")
        return self


def _ordered[T: StrictFrozenModel](value: tuple[T, ...]) -> tuple[T, ...]:
    return tuple(
        sorted(
            value, key=lambda item: canonical_json_bytes(item.model_dump(mode="json"))
        )
    )


class ViewManifest(StrictFrozenModel):
    profile: Literal["CCS-2.1-m4-collective-interfaces-v1"] = (
        "CCS-2.1-m4-collective-interfaces-v1"
    )
    compiler_version: SemVer = "0.1.0"
    task_id: NonEmptyString
    tenant: NonEmptyString
    repository: NonEmptyString
    as_of: TimestampString
    task_digest: Digest
    permission_digest: Digest
    request_digest: Digest
    model_id: NonEmptyString
    tokenizer_profile: NonEmptyString
    renderer_version: NonEmptyString
    capsules: tuple[CapsuleRef, ...] = ()
    decisions: tuple[DecisionRecord, ...] = ()
    providers: tuple[ProviderWitness, ...] = ()
    closure: tuple[ClosureLink, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    expanded_evidence: StringSet = ()
    rejected_counts: Mapping[NonEmptyString, Count] = Field(
        default_factory=lambda: MappingProxyType({})
    )
    services: tuple[ServiceStamp, ...] = ()
    tokens: TokenAccounting
    validation: ValidationReport

    @field_validator("capsules")
    @classmethod
    def _capsule_order(cls, value: tuple[CapsuleRef, ...]) -> tuple[CapsuleRef, ...]:
        if len({item.capsule_id for item in value}) != len(value):
            raise ValueError("duplicate or contradictory capsule identity")
        return tuple(sorted(value, key=lambda item: item.key))

    @field_validator("decisions")
    @classmethod
    def _decision_order(
        cls, value: tuple[DecisionRecord, ...]
    ) -> tuple[DecisionRecord, ...]:
        if len({(item.capsule.key, item.atom_id) for item in value}) != len(value):
            raise ValueError("duplicate decision key")
        return tuple(sorted(value, key=lambda item: (item.capsule.key, item.atom_id)))

    @field_validator("providers", "closure", "conflicts", "services")
    @classmethod
    def _set_order[T: StrictFrozenModel](cls, value: tuple[T, ...]) -> tuple[T, ...]:
        return _ordered(value)

    @field_validator("rejected_counts")
    @classmethod
    def _freeze_counts(cls, value: Mapping[str, int]) -> Mapping[str, int]:
        return MappingProxyType(dict(value))

    @field_serializer("rejected_counts")
    def _serialize_counts(self, value: Mapping[str, int]) -> dict[str, int]:
        return dict(value)


class CompiledView(StrictFrozenModel):
    """Consistent runtime output, not a signed activation or behavioral receipt."""

    content: str
    manifest: ViewManifest
    validation: ValidationReport
    evidence_handles: tuple[EvidenceHandle, ...] = ()

    @model_validator(mode="after")
    def _consistent_view(self) -> CompiledView:
        if self.validation != self.manifest.validation:
            raise ValueError("view and manifest validation reports differ")
        if not self.validation.valid and self.content:
            raise ValueError("invalid views must have empty content")
        if (
            self.validation.valid
            and self.manifest.tokens.total > self.manifest.tokens.available
        ):
            raise ValueError("valid view exceeds available tokens")
        return self


def canonical_view_manifest_bytes(manifest: ViewManifest) -> bytes:
    """Explicit B-zone serialization, independent of the frozen A-zone projection."""
    return canonical_json_bytes(
        {
            "profile": manifest.profile,
            "compiler_version": manifest.compiler_version,
            "task_id": manifest.task_id,
            "tenant": manifest.tenant,
            "repository": manifest.repository,
            "as_of": manifest.as_of,
            "task_digest": manifest.task_digest,
            "permission_digest": manifest.permission_digest,
            "request_digest": manifest.request_digest,
            "model_id": manifest.model_id,
            "tokenizer_profile": manifest.tokenizer_profile,
            "renderer_version": manifest.renderer_version,
            "capsules": [item.model_dump(mode="json") for item in manifest.capsules],
            "decisions": [item.model_dump(mode="json") for item in manifest.decisions],
            "providers": [item.model_dump(mode="json") for item in manifest.providers],
            "closure": [item.model_dump(mode="json") for item in manifest.closure],
            "conflicts": [item.model_dump(mode="json") for item in manifest.conflicts],
            "expanded_evidence": list(manifest.expanded_evidence),
            "rejected_counts": dict(manifest.rejected_counts),
            "services": [item.model_dump(mode="json") for item in manifest.services],
            "tokens": manifest.tokens.model_dump(mode="json"),
            "validation": manifest.validation.model_dump(mode="json"),
        }
    )


def view_manifest_digest(manifest: ViewManifest) -> str:
    return (
        "sha256:" + hashlib.sha256(canonical_view_manifest_bytes(manifest)).hexdigest()
    )


def compile_request_projection(request: CompileRequest) -> dict[str, Any]:
    """Replay input excluding rebuildable B/C data and publication transport time.

    Exact core/signature/status projection is data, never proof of publication.
    The expected output digest is excluded to avoid a replay identity fixed point.
    """
    publications: list[dict[str, Any]] = []
    for publication in request.capsules:
        wire = capsule_wire_dict(publication.capsule)
        wire.pop("derived_artifacts")
        wire.pop("runtime_sidecar")
        publications.append(
            {"capsule": wire, "registry_status": publication.registry_status}
        )
    publications.sort(
        key=lambda item: (
            item["capsule"]["control_manifest"]["capsule_id"],
            item["capsule"]["control_manifest"]["version"],
            item["capsule"]["control_manifest"]["content_digest"],
        )
    )
    return {
        "capsules": publications,
        "task": request.task.model_dump(mode="json"),
        "principal": {"principal_id": request.principal.principal_id},
        "budget": request.budget.model_dump(mode="json"),
        "as_of": request.as_of,
        "model_id": request.model_id,
        "tokenizer_profile": request.tokenizer_profile,
        "renderer_version": request.renderer_version,
        "runtime_config": thaw_json(request.runtime_config),
    }
