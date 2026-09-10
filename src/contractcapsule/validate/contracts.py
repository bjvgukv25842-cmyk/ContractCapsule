"""Signed execution-clause binding verification."""

import hashlib
from collections.abc import Mapping
from typing import Any

from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.storage.registry import Registry, RegistryError
from contractcapsule.validate.artifacts import publication_projection
from contractcapsule.validate.models import (
    Artifact,
    BoundExecution,
    CheckBinding,
    ExecutionProfile,
    Invocation,
    ReplacementRequest,
)
from contractcapsule.validate.protocols import ArtifactResolver


class ExecutionContractError(ValueError):
    """Safe, non-payload execution-contract rejection."""


def parse_execution_contract(
    request: ReplacementRequest, registry: Registry, resolver: ArtifactResolver
) -> BoundExecution:
    try:
        request = ReplacementRequest.model_validate(
            {
                **request.__dict__,
                "task": dict(request.task.__dict__),
                "budget": dict(request.budget.__dict__),
            }
        )
        _verify_publications(request, registry)
        raw = request.new.capsule.replacement_contract.extensions.get("x-m5-execution")
        profile = ExecutionProfile.model_validate(_raw_containers(raw))
        _compatibility(request, profile)
        _check_coverage(request, profile)
        artifacts = resolver.resolve(request.new)
        _verify_artifacts(request, profile, artifacts)
        return BoundExecution(request=request, profile=profile, artifacts=artifacts)
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        AttributeError,
        RegistryError,
    ) as error:
        raise ExecutionContractError("execution contract rejected") from error


def _raw_containers(value: Any) -> Any:
    """Adapt frozen JSON containers, without JSON serializer key/value coercion."""
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("non-string key")
        return {key: _raw_containers(item) for key, item in value.items()}
    if type(value) in {list, tuple}:
        return tuple(_raw_containers(item) for item in value)
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise ValueError("non-JSON value")


def _verify_publications(request: ReplacementRequest, registry: Registry) -> None:
    if type(request) is not ReplacementRequest:
        raise ValueError("invalid request")
    for publication in (request.old, request.new):
        manifest = publication.capsule.control_manifest
        actual = registry.get(manifest.capsule_id, manifest.version, request.principal)
        if actual.registry_status != "PUBLISHED" or publication_projection(
            actual
        ) != publication_projection(publication):
            raise ValueError("publication mismatch")


def _compatibility(request: ReplacementRequest, profile: ExecutionProfile) -> None:
    old = request.old.capsule.control_manifest
    new = request.new.capsule.control_manifest
    contract = request.new.capsule.replacement_contract
    ref = profile.replaces_ref
    if (ref.capsule_id, ref.version, ref.digest) != (
        old.capsule_id,
        old.version,
        old.content_digest,
    ):
        raise ValueError("old ref mismatch")
    old_name = f"{old.capsule_id}@{old.version}"
    if contract.replaces != old_name or contract.rollback.pointer != old_name:
        raise ValueError("replacement/rollback mismatch")
    if not set(old.provides) <= set(profile.accepts_interfaces):
        raise ValueError("incompatible old interfaces")
    if not set(request.task.required_interfaces) <= set(new.provides):
        raise ValueError("new root lacks task interfaces")
    if request.task.repository != request.source_repository:
        raise ValueError("source repository mismatch")
    if request.task.tenant != old.tenant or old.tenant != new.tenant:
        raise ValueError("tenant mismatch")
    high = request.task.risk in {"high", "critical"} or contract.activation.risk in {
        "high",
        "critical",
    }
    if profile.repetitions != (3 if high else 1):
        raise ValueError("wrong repeat count")


def _clauses(request: ReplacementRequest) -> dict[str, tuple[str, str, str]]:
    contract = request.new.capsule.replacement_contract
    result = {}
    for collection, role, phase in (
        ("preconditions", "precondition", "pre"),
        ("target_effects", "target", "post"),
        ("protected_invariants", "invariant", "post"),
        ("forbidden_spillover", "spillover", "post"),
        ("verification/static", "static", "post"),
        ("verification/behavioral", "behavioral", "post"),
        ("verification/differential", "differential", "pair"),
    ):
        values = (
            getattr(contract.verification, collection.split("/")[1])
            if collection.startswith("verification/")
            else getattr(contract, collection)
        )
        if role in {"target", "invariant", "spillover"} and not values:
            raise ValueError("empty behavioral collection")
        for index, text in enumerate(values):
            result[f"{collection}/{index}"] = (
                role,
                phase,
                "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
            )
    return result


def _check_coverage(request: ReplacementRequest, profile: ExecutionProfile) -> None:
    clauses = _clauses(request)
    if len({check.check_id for check in profile.checks}) != len(profile.checks):
        raise ValueError("duplicate check ID")
    paths = [check.clause_path for check in profile.checks]
    if len(set(paths)) != len(paths) or set(paths) != set(clauses):
        raise ValueError("incomplete/duplicate clause mapping")
    probes = [
        probe.probe_id for check in profile.checks for probe in check.subject_probes
    ]
    if len(probes) != len(set(probes)):
        raise ValueError("ambiguous probe ID")
    for check in profile.checks:
        if (check.role, check.phase, check.clause_sha256) != clauses[check.clause_path]:
            raise ValueError("clause binding mismatch")
        _expectations(check)
    if not any(
        check.role == "target" and check.old_expected is False
        for check in profile.checks
    ):
        raise ValueError("no behavior-changing target")


def _expectations(check: CheckBinding) -> None:
    pair = (check.old_expected, check.new_expected)
    if check.role in {"precondition", "static", "behavioral", "invariant"} and pair != (
        True,
        True,
    ):
        raise ValueError("guard expectations")
    if check.role == "target" and check.new_expected is not True:
        raise ValueError("target expectation")
    if check.role == "spillover" and pair != (False, False):
        raise ValueError("spillover expectations")
    if check.role == "differential" and check.pair_expected is not True:
        raise ValueError("paired expectation")
    states = (
        {"initial", "old_final", "new_final"}
        if check.phase == "pair"
        else {"initial", "current"}
    )
    if any(probe.input_state not in states for probe in check.subject_probes):
        raise ValueError("probe snapshot mismatch")


def _invocation(
    invocation: Invocation, kind: str, artifacts: dict[str, Artifact]
) -> set[str]:
    if not set(invocation.artifact_ids) <= artifacts.keys():
        raise ValueError("missing declared artifact")
    entry = artifacts[invocation.test_id]
    if (
        entry.kind != kind
        or not entry.path.startswith(f"tests/{kind}/")
        or not entry.path.endswith(".py")
    ):
        raise ValueError("wrong program kind/path")
    return set(invocation.artifact_ids)


def _verify_artifacts(
    request: ReplacementRequest, profile: ExecutionProfile, values: tuple[Artifact, ...]
) -> None:
    artifacts = {item.test_id: item for item in values}
    tests = request.new.capsule.tests_integrity.tests
    if len(artifacts) != len(values) or set(artifacts) != {
        test.test_id for test in tests
    }:
        raise ValueError("ambiguous/incomplete test set")
    checksums = {
        item.path: item.digest
        for item in request.new.capsule.tests_integrity.artifact_checksums
    }
    for test in tests:
        artifact = artifacts[test.test_id]
        if (artifact.path, artifact.kind, artifact.digest) != (
            test.path,
            test.kind,
            test.digest,
        ):
            raise ValueError("artifact lock mismatch")
        if (
            checksums.get(test.path) != test.digest
            or "sha256:" + hashlib.sha256(artifact.data).hexdigest() != test.digest
        ):
            raise ValueError("artifact bytes mismatch")
    subjects = _invocation(profile.executor, "behavioral", artifacts)
    checkers: set[str] = set()
    for check in profile.checks:
        kind = "static" if check.role in {"precondition", "static"} else "behavioral"
        checkers.update(_invocation(check, kind, artifacts))
        for probe in check.subject_probes:
            subjects.update(_invocation(probe, "behavioral", artifacts))
    _disjoint(subjects, checkers, artifacts)


def _disjoint(
    subjects: set[str], checkers: set[str], artifacts: dict[str, Artifact]
) -> None:
    subject_paths = {artifacts[key].path.casefold() for key in subjects}
    checker_paths = {artifacts[key].path.casefold() for key in checkers}
    subject_bytes = {artifacts[key].digest for key in subjects}
    checker_bytes = {artifacts[key].digest for key in checkers}
    if (
        subjects & checkers
        or subject_paths & checker_paths
        or subject_bytes & checker_bytes
    ):
        raise ValueError("subject/checker artifact overlap")


def execution_subject(bound: BoundExecution) -> str:
    request = bound.request
    payload = {
        "domain": "ccs-m5-execution-approval/1.0.0",
        "operation_id": request.operation_id,
        "principal": request.principal.principal_id,
        "old": publication_projection(request.old),
        "new": publication_projection(request.new),
        "task": request.task.model_dump(mode="json"),
        "source_repository": request.source_repository,
        "source_commit": request.source_commit,
        "budget": request.budget.model_dump(mode="json"),
        "model_id": request.model_id,
        "tokenizer_profile": request.tokenizer_profile,
        "renderer_version": request.renderer_version,
        "profile": bound.profile.model_dump(mode="json", exclude_none=True),
        "artifacts": [
            {
                "test_id": item.test_id,
                "path": item.path,
                "kind": item.kind,
                "digest": item.digest,
                "bytes_digest": "sha256:" + hashlib.sha256(item.data).hexdigest(),
            }
            for item in bound.artifacts
        ],
    }
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
