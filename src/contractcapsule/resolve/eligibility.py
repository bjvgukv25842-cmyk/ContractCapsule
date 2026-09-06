"""Registry-backed local admission, strictly before ranking or provider coverage."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Annotated

from pydantic import Field, InstanceOf, TypeAdapter, field_serializer, field_validator

from contractcapsule.build.publish import _loader_publication_digest
from contractcapsule.compile.errors import CompileError
from contractcapsule.compile.protocols import EligibilityAuthorizer, FreshnessChecker
from contractcapsule.models.base import (
    Digest,
    Principal,
    SemVer,
    StrictFrozenModel,
    TimestampString,
)
from contractcapsule.models.core import Atom, Capsule, ControlManifest
from contractcapsule.models.view import Count, Eligibility, StringSet, TaskContext
from contractcapsule.resolve.policies import (
    Sensitivity,
    referenced_evidence,
    sensitivity_within,
    snapshot_digest,
)
from contractcapsule.resolve.scope import atom_scope_matches, paths_match
from contractcapsule.storage.registry import PublishedCapsule, Registry


class AdmittedCapsule(StrictFrozenModel):
    # The full verified payload is internal provider-membership input, not diagnostics.
    published: Annotated[InstanceOf[PublishedCapsule], Field(repr=False)]
    atom_ids: StringSet


class AdmissionResult(StrictFrozenModel):
    items: tuple[AdmittedCapsule, ...]
    rejected_counts: Mapping[str, Count]
    permission_digest: Digest
    freshness_digest: Digest

    @field_validator("rejected_counts")
    @classmethod
    def _safe_counts(cls, value: Mapping[str, int]) -> Mapping[str, int]:
        if any(re.fullmatch(r"[A-Z][A-Z_]*", key) is None for key in value):
            raise ValueError("rejection diagnostics require safe codes")
        return MappingProxyType(dict(sorted(value.items())))

    @field_serializer("rejected_counts")
    def _serialize_counts(self, value: Mapping[str, int]) -> dict[str, int]:
        return dict(value)


def _require(decision: Callable[[], object], code: str) -> None:
    try:
        allowed = decision()
    except Exception:  # noqa: BLE001 - arbitrary policy faults must deny without disclosure.
        raise CompileError(code) from None
    if allowed is not True:
        raise CompileError(code)


def _interfaces(values: tuple[str, ...]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for value in values:
        match = re.fullmatch(r"([^\s/]+(?:/[^\s/]+)*)/v(0|[1-9][0-9]*)", value)
        if match is None:
            raise CompileError("INTERFACE_INCOMPATIBLE")
        result.setdefault(match[1], set()).add(value)
    return result


def _compatible(capsule: Capsule, task: TaskContext) -> bool:
    provided = _interfaces(capsule.control_manifest.provides)
    required = _interfaces(task.required_interfaces)
    return all(
        not (family in provided) or bool(versions & provided[family])
        for family, versions in required.items()
    )


def _valid_at(atom: Atom, instant: datetime) -> bool:
    today = instant.date().isoformat()
    return atom.validity.from_ <= today and (
        atom.validity.until is None or today <= atom.validity.until
    )


def _atom_scope_within_capsule(capsule: Capsule, atom: Atom, task: TaskContext) -> bool:
    admitted_paths = tuple(
        path
        for path in task.paths
        if paths_match(capsule.control_manifest.scope.paths, (path,))
    )
    # Narrow only scope evaluation; authorization and replay bind the original task.
    scope_task = task.model_copy(update={"paths": admitted_paths})
    return bool(admitted_paths) and atom_scope_matches(atom.scope, scope_task)


def _publication_key(publication: PublishedCapsule) -> tuple[str, str]:
    if (
        type(publication) is not PublishedCapsule
        or type(publication.capsule) is not Capsule
    ):
        raise CompileError("REGISTRY_INTEGRITY")
    manifest = publication.capsule.control_manifest
    if type(manifest) is not ControlManifest:
        raise CompileError("REGISTRY_INTEGRITY")
    identity = (manifest.capsule_id, manifest.version)
    if not all(type(value) is str and value for value in identity):
        raise CompileError("REGISTRY_INTEGRITY")
    return identity


def _ttl_valid(capsule: Capsule, atom: Atom, instant: datetime) -> bool:
    if atom.compression_class != "P4_TRANSIENT":
        return True
    policy = next(
        item
        for item in capsule.compression_policy.classes
        if item.name == "P4_TRANSIENT"
    )
    if policy.ttl is None:
        return True
    ttl = timedelta(days=int(policy.ttl[1:-1]))
    evidence = referenced_evidence(capsule, atom)
    return bool(evidence) and all(
        datetime.fromisoformat(item.captured_at)
        <= instant
        <= datetime.fromisoformat(item.captured_at) + ttl
        for item in evidence
    )


@dataclass(frozen=True)
class EligibilityResolver:
    registry: Registry = field(repr=False)
    authorizer: EligibilityAuthorizer = field(repr=False)
    freshness: FreshnessChecker = field(repr=False)
    as_of: TimestampString
    max_sensitivity: Sensitivity = "restricted"

    def __post_init__(self) -> None:
        if type(self.registry) is not Registry:
            raise CompileError("INVALID_CONFIGURATION")
        try:
            TypeAdapter(TimestampString).validate_python(self.as_of, strict=True)
            TypeAdapter(Sensitivity).validate_python(self.max_sensitivity, strict=True)
        except (TypeError, ValueError):
            raise CompileError("INVALID_CONFIGURATION") from None

    def _snapshot(self, task: TaskContext, principal: Principal) -> tuple[str, str]:
        try:
            permission_version = TypeAdapter(SemVer).validate_python(
                self.authorizer.version, strict=True
            )
            freshness_version = TypeAdapter(SemVer).validate_python(
                self.freshness.version, strict=True
            )
            permission = TypeAdapter(Digest).validate_python(
                self.authorizer.context_digest(task, principal), strict=True
            )
            freshness = TypeAdapter(Digest).validate_python(
                self.freshness.context_digest(), strict=True
            )
            return (
                snapshot_digest(
                    {
                        "authorizer": permission,
                        "version": permission_version,
                        "as_of": self.as_of,
                        "max_sensitivity": self.max_sensitivity,
                        "task": task.model_dump(mode="json"),
                        "principal_id": principal.principal_id,
                    }
                ),
                snapshot_digest(
                    {
                        "freshness": freshness,
                        "version": freshness_version,
                        "as_of": self.as_of,
                    }
                ),
            )
        except Exception:  # noqa: BLE001 - snapshot providers are replaceable trust boundaries.
            raise CompileError("INVALID_POLICY_SNAPSHOT") from None

    def _verified(self, capsule: Capsule, principal: Principal) -> PublishedCapsule:
        try:
            if type(capsule) is not Capsule or type(principal) is not Principal:
                raise CompileError("REGISTRY_INTEGRITY")
            manifest = capsule.control_manifest
            published = self.registry.get(
                manifest.capsule_id, manifest.version, principal
            )
            if _loader_publication_digest(capsule) != _loader_publication_digest(
                published.capsule
            ):
                raise CompileError("REGISTRY_INTEGRITY")
            return published
        except Exception:  # noqa: BLE001 - Registry/integrity failures must not disclose content.
            raise CompileError("REGISTRY_INTEGRITY") from None

    def _capsule_gates(
        self, published: PublishedCapsule, task: TaskContext, principal: Principal
    ) -> None:
        capsule = published.capsule
        manifest = capsule.control_manifest
        _require(
            lambda: (
                published.registry_status == "PUBLISHED"
                and manifest.lifecycle == "PUBLISHED"
            ),
            "LIFECYCLE_DENIED",
        )
        _require(lambda: manifest.tenant == task.tenant, "TENANT_DENIED")
        _require(
            lambda: self.authorizer.authorize(capsule, None, task, principal),
            "AUTHORIZATION_DENIED",
        )
        _require(
            lambda: sensitivity_within(manifest.sensitivity, self.max_sensitivity),
            "SENSITIVITY_DENIED",
        )
        _require(
            lambda: task.repository in manifest.scope.repositories, "REPOSITORY_DENIED"
        )
        _require(lambda: paths_match(manifest.scope.paths, task.paths), "PATH_DENIED")
        _require(
            lambda: task.environment in manifest.scope.environments,
            "ENVIRONMENT_DENIED",
        )
        _require(
            lambda: self.freshness.check(capsule, None, self.as_of), "FRESHNESS_DENIED"
        )
        _require(lambda: _compatible(capsule, task), "INTERFACE_INCOMPATIBLE")

    def _atom_gates(
        self, capsule: Capsule, atom: Atom, task: TaskContext, principal: Principal
    ) -> None:
        instant = datetime.fromisoformat(self.as_of)
        _require(lambda: atom.status == "validated", "ATOM_STATUS_DENIED")
        _require(
            lambda: self.authorizer.authorize(capsule, atom, task, principal),
            "AUTHORIZATION_DENIED",
        )
        _require(
            lambda: sensitivity_within(atom.sensitivity, self.max_sensitivity),
            "SENSITIVITY_DENIED",
        )
        _require(
            lambda: _atom_scope_within_capsule(capsule, atom, task), "ATOM_SCOPE_DENIED"
        )
        _require(lambda: _valid_at(atom, instant), "VALIDITY_DENIED")
        _require(
            lambda: atom.refresh_policy in {"on-source-change", "immutable"},
            "REFRESH_POLICY_DENIED",
        )
        _require(
            lambda: self.freshness.check(capsule, atom, self.as_of), "FRESHNESS_DENIED"
        )
        _require(lambda: _ttl_valid(capsule, atom, instant), "TTL_EXPIRED")

    def _admit(
        self,
        capsule: Capsule,
        task: TaskContext,
        principal: Principal,
        counts: Counter[str],
    ) -> AdmittedCapsule:
        published = self._verified(capsule, principal)
        self._capsule_gates(published, task, principal)
        selected: list[str] = []
        for atom in published.capsule.semantic_payload.atoms:
            try:
                self._atom_gates(published.capsule, atom, task, principal)
                selected.append(atom.atom_id)
            except CompileError as error:
                counts[error.code] += 1
        return AdmittedCapsule(published=published, atom_ids=tuple(selected))

    def eligible(
        self, capsule: Capsule, task: TaskContext, principal: Principal
    ) -> Eligibility:
        try:
            before = self._snapshot(task, principal)
            admitted = self._admit(capsule, task, principal, Counter())
            if before != self._snapshot(task, principal):
                raise CompileError("POLICY_SNAPSHOT_CHANGED")
            return Eligibility(allowed=True, atom_ids=admitted.atom_ids)
        except CompileError as error:
            return Eligibility(allowed=False, blockers=(error.code,))

    @staticmethod
    def _unique(
        capsules: tuple[PublishedCapsule, ...], counts: Counter[str]
    ) -> tuple[PublishedCapsule, ...]:
        groups: dict[tuple[str, str], list[PublishedCapsule]] = {}
        for publication in capsules:
            try:
                key = _publication_key(publication)
                groups.setdefault(key, []).append(publication)
            except (AttributeError, TypeError, ValueError, CompileError):
                counts["REGISTRY_INTEGRITY"] += 1
        selected: list[PublishedCapsule] = []
        for key in sorted(groups):
            group = groups[key]
            try:
                identities = {
                    (_loader_publication_digest(item.capsule), item.registry_status)
                    for item in group
                }
                if len(identities) != 1:
                    raise CompileError("CONFLICTING_PUBLICATION")
                selected.append(group[0])
            except (AttributeError, TypeError, ValueError, CompileError):
                counts["CONFLICTING_PUBLICATION"] += len(group)
        return tuple(selected)

    def resolve(
        self,
        capsules: tuple[PublishedCapsule, ...],
        task: TaskContext,
        principal: Principal,
    ) -> AdmissionResult:
        before = self._snapshot(task, principal)
        counts: Counter[str] = Counter()
        items: list[AdmittedCapsule] = []
        for publication in self._unique(capsules, counts):
            try:
                if publication.registry_status != "PUBLISHED":
                    raise CompileError("LIFECYCLE_DENIED")
                items.append(self._admit(publication.capsule, task, principal, counts))
            except CompileError as error:
                counts[error.code] += 1
        if before != self._snapshot(task, principal):
            raise CompileError("POLICY_SNAPSHOT_CHANGED")
        return AdmissionResult(
            items=tuple(items),
            rejected_counts=counts,
            permission_digest=before[0],
            freshness_digest=before[1],
        )
