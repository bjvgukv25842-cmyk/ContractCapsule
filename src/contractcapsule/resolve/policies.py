"""Explicit trusted local policy and freshness snapshots, defaulting to denial."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import TypeAdapter, field_validator, model_validator

from contractcapsule.models.base import (
    Digest,
    NonEmptyString,
    Principal,
    SemVer,
    StrictFrozenModel,
    TimestampString,
)
from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.models.core import Atom, Capsule, EvidenceRecord
from contractcapsule.models.view import CapsuleRef, TaskContext

Sensitivity = Literal["public", "internal", "confidential", "restricted"]


def snapshot_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sensitivity_within(value: str, ceiling: str) -> bool:
    levels = ("public", "internal", "confidential", "restricted")
    return (
        value in levels
        and ceiling in levels
        and levels.index(value) <= levels.index(ceiling)
    )


def capsule_ref(capsule: Capsule) -> CapsuleRef:
    manifest = capsule.control_manifest
    return CapsuleRef(
        capsule_id=manifest.capsule_id,
        version=manifest.version,
        digest=manifest.content_digest,
    )


def referenced_evidence(
    capsule: Capsule, atom: Atom | None
) -> tuple[EvidenceRecord, ...]:
    if atom is None:
        return capsule.evidence_plane.records
    by_id = {record.evidence_id: record for record in capsule.evidence_plane.records}
    if not atom.evidence_refs or not set(atom.evidence_refs) <= by_id.keys():
        return ()
    return tuple(by_id[ref] for ref in atom.evidence_refs)


class AccessGrant(StrictFrozenModel):
    principal_id: NonEmptyString
    tenant: NonEmptyString
    authorities: tuple[NonEmptyString, ...]
    capsule_ids: tuple[NonEmptyString, ...]
    access_policies: tuple[NonEmptyString, ...]
    max_sensitivity: Sensitivity

    @field_validator("authorities", "capsule_ids", "access_policies")
    @classmethod
    def _canonical_sets(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


def _grant_matches(
    grant: AccessGrant,
    capsule: Capsule,
    atom: Atom | None,
    task: TaskContext,
    principal: Principal,
) -> bool:
    manifest = capsule.control_manifest
    authorities = (
        (manifest.authority,) if atom is None else (manifest.authority, atom.authority)
    )
    sensitivities = (
        (manifest.sensitivity,)
        if atom is None
        else (manifest.sensitivity, atom.sensitivity)
    )
    evidence = referenced_evidence(capsule, atom)
    return (
        grant.principal_id == principal.principal_id
        and grant.tenant == task.tenant == manifest.tenant
        and (manifest.capsule_id in grant.capsule_ids or "*" in grant.capsule_ids)
        and all(
            value in grant.authorities or "*" in grant.authorities
            for value in authorities
        )
        and all(
            sensitivity_within(value, grant.max_sensitivity) for value in sensitivities
        )
        and bool(evidence)
        and all(record.access_policy in grant.access_policies for record in evidence)
    )


@dataclass(frozen=True)
class StaticEligibilityAuthorizer:
    grants: tuple[AccessGrant, ...] = ()
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        TypeAdapter(SemVer).validate_python(self.version, strict=True)
        if type(self.grants) is not tuple:
            raise ValueError("grants require an immutable tuple")
        grants = tuple(
            AccessGrant.model_validate_json(grant.model_dump_json())
            for grant in self.grants
        )
        by_wire = {
            canonical_json_bytes(grant.model_dump(mode="json")): grant
            for grant in grants
        }
        object.__setattr__(
            self, "grants", tuple(by_wire[key] for key in sorted(by_wire))
        )

    def authorize(
        self,
        capsule: Capsule,
        atom: Atom | None,
        task: TaskContext,
        principal: Principal,
    ) -> bool:
        return any(
            _grant_matches(grant, capsule, atom, task, principal)
            for grant in self.grants
        )

    def context_digest(self, task: TaskContext, principal: Principal) -> str:
        return snapshot_digest(
            {
                "version": self.version,
                "grants": [grant.model_dump(mode="json") for grant in self.grants],
                "task": task.model_dump(mode="json"),
                "principal_id": principal.principal_id,
            }
        )


class FreshnessRecord(StrictFrozenModel):
    capsule: CapsuleRef
    evidence_id: NonEmptyString
    content_digest: Digest
    checked_at: TimestampString
    valid_until: TimestampString

    @model_validator(mode="after")
    def _ordered_times(self) -> FreshnessRecord:
        if datetime.fromisoformat(self.checked_at) > datetime.fromisoformat(
            self.valid_until
        ):
            raise ValueError("freshness record time interval is reversed")
        return self


def _fresh_record(
    record: FreshnessRecord, evidence: EvidenceRecord, as_of: datetime
) -> bool:
    return (
        evidence.validation == "verified"
        and record.content_digest == evidence.content_digest
        and datetime.fromisoformat(evidence.captured_at) <= as_of
        and datetime.fromisoformat(record.checked_at)
        <= as_of
        <= datetime.fromisoformat(record.valid_until)
    )


@dataclass(frozen=True)
class RecordedFreshnessChecker:
    """Trusted attestation only; source byte integrity still needs its own resolver."""

    records: tuple[FreshnessRecord, ...] = ()
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        TypeAdapter(SemVer).validate_python(self.version, strict=True)
        if type(self.records) is not tuple:
            raise ValueError("freshness records require an immutable tuple")
        records = tuple(
            FreshnessRecord.model_validate_json(record.model_dump_json())
            for record in self.records
        )
        keys = {(record.capsule.key, record.evidence_id) for record in records}
        if len(keys) != len(records):
            raise ValueError("duplicate or contradictory freshness records")
        object.__setattr__(
            self,
            "records",
            tuple(
                sorted(
                    records, key=lambda record: (record.capsule.key, record.evidence_id)
                )
            ),
        )

    def check(self, capsule: Capsule, atom: Atom | None, as_of: str) -> bool:
        instant = datetime.fromisoformat(
            TypeAdapter(TimestampString).validate_python(as_of, strict=True)
        )
        evidence = referenced_evidence(capsule, atom)
        by_id = {
            record.evidence_id: record
            for record in self.records
            if record.capsule == capsule_ref(capsule)
        }
        return bool(evidence) and all(
            item.evidence_id in by_id
            and _fresh_record(by_id[item.evidence_id], item, instant)
            for item in evidence
        )

    def context_digest(self) -> str:
        return snapshot_digest(
            {
                "version": self.version,
                "records": [record.model_dump(mode="json") for record in self.records],
            }
        )
