"""M5 binding and authority boundaries using real loader and Registry."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from contractcapsule.models import Principal
from contractcapsule.models.view import TaskContext, ViewBudget
from contractcapsule.validate.approvals import (
    ApprovalAuthority,
    ApprovalError,
    _signature,
)
from contractcapsule.validate.artifacts import LocalArtifactResolver
from contractcapsule.validate.contracts import (
    ExecutionContractError,
    parse_execution_contract,
)
from contractcapsule.validate.models import ReplacementRequest
from tests.m5_helpers import M5Fixture


def request_for(fixture: M5Fixture) -> ReplacementRequest:
    return ReplacementRequest(
        operation_id="synthetic-operation",
        principal=Principal("reader"),
        old=fixture.old,
        new=fixture.new,
        task=TaskContext(
            task_id="synthetic",
            tenant="example",
            repository="example/api",
            paths=("src/main.py",),
            environment="dev",
            text="change target",
            required_interfaces=("policy/v2",),
        ),
        source_repository="example/api",
        source_commit="sha1:" + "a" * 40,
        budget=ViewBudget(model_input_tokens=10000),
        model_id="reference/1",
        tokenizer_profile="o200k_base",
        renderer_version="ccs-neutral/1.0.0",
    )


def parse(fixture: M5Fixture):
    resolver = LocalArtifactResolver(
        {fixture.new.capsule.control_manifest.content_digest: fixture.package}
    )
    return parse_execution_contract(
        request_for(fixture), fixture.base.registry, resolver
    )


def test_real_package_and_repeatable_approval(tmp_path: Path) -> None:
    bound = parse(M5Fixture.create(tmp_path))
    assert len(bound.profile.checks) == 7
    now = datetime(2026, 9, 10, tzinfo=UTC)
    authority = ApprovalAuthority(
        "synthetic-issuer", b"synthetic-key-32-bytes-for-test!!"
    )
    approval = authority.issue_execution(
        bound, issued_at=now, expires_at=now + timedelta(minutes=5), synthetic=True
    )
    verifier = authority.verifier()
    assert verifier.verify_execution(approval, bound, now=now) == approval
    assert verifier.verify_execution(approval, bound, now=now) == approval
    with pytest.raises(ApprovalError):
        verifier.verify_execution(approval, bound, now=now + timedelta(hours=1))
    with pytest.raises(ApprovalError):
        verifier.verify_execution(None, bound, now=now)
    assert "synthetic-key" not in repr(authority)


def test_approval_expiry_is_parsed_at_fractional_boundary(tmp_path: Path) -> None:
    bound = parse(M5Fixture.create(tmp_path))
    issued = datetime(2026, 9, 10, tzinfo=UTC)
    authority = ApprovalAuthority("synthetic-issuer", b"synthetic-key-32-bytes-for-test!!")
    approval = authority.issue_execution(
        bound, issued_at=issued, expires_at=issued + timedelta(minutes=5), synthetic=True
    )
    no_fraction = approval.model_copy(
        update={"expires_at": "2026-09-10T00:05:00Z", "signature": "sha256:" + "0" * 64}
    )
    no_fraction = no_fraction.model_copy(
        update={"signature": _signature(authority._key, no_fraction)}
    )
    issued_no_fraction = approval.model_copy(
        update={
            "issued_at": "2026-09-10T00:00:00Z",
            "expires_at": "2026-09-10T00:05:00Z",
            "signature": "sha256:" + "0" * 64,
        }
    )
    issued_no_fraction = issued_no_fraction.model_copy(
        update={"signature": _signature(authority._key, issued_no_fraction)}
    )
    assert authority.verifier().verify_execution(
        issued_no_fraction,
        bound,
        now=datetime(2026, 9, 10, 0, 0, 0, 1, tzinfo=UTC),
    ) == issued_no_fraction
    with pytest.raises(ApprovalError):
        authority.verifier().verify_execution(
            no_fraction,
            bound,
            now=datetime(2026, 9, 10, 0, 5, 0, 1, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "target"),
        ("phase", "post"),
        ("clause_path", "preconditions/1"),
        ("clause_sha256", "sha256:" + "0" * 64),
        ("test_id", "missing"),
        ("artifact_ids", ["executor"]),
        ("old_expected", 1),
        ("pair_expected", True),
        ("unknown", True),
    ],
)
def test_bad_binding(tmp_path: Path, field: str, value: object) -> None:
    def amend(raw):
        raw["replacement_contract"]["extensions"]["x-m5-execution"]["checks"][0][
            field
        ] = value

    fixture = M5Fixture.create(tmp_path, amend)
    with pytest.raises(ExecutionContractError):
        parse(fixture)


def test_actual_artifact_mutation(tmp_path: Path) -> None:
    fixture = M5Fixture.create(tmp_path)
    (fixture.package / "tests/behavioral/executor.py").write_bytes(b"tampered")
    with pytest.raises(ExecutionContractError):
        parse(fixture)


def test_checker_bytes_cannot_alias_executor(tmp_path: Path) -> None:
    fixture = M5Fixture.create(
        tmp_path, programs={"executor": b"same bytes", "target": b"same bytes"}
    )
    with pytest.raises(ExecutionContractError):
        parse(fixture)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_check",
        "duplicate_id",
        "duplicate_path",
        "bad_interfaces",
        "bad_old_ref",
        "bad_replaces",
        "bad_rollback",
        "bad_repeat",
        "bad_profile",
        "high_limit",
        "bool_limit",
        "unmapped_target",
        "wrong_kind",
        "subject_checker_overlap",
        "missing_helper",
        "probe_bad_state",
        "duplicate_probe",
        "pair_old_expected",
        "pair_false",
    ],
)
def test_profile_mutations_fail_closed(tmp_path: Path, mutation: str) -> None:
    fixture = M5Fixture.create(tmp_path, lambda raw: mutate_profile(raw, mutation))
    with pytest.raises(ExecutionContractError):
        parse(fixture)


def mutate_profile(raw: dict[str, Any], mutation: str) -> None:
    contract = raw["replacement_contract"]
    profile = contract["extensions"]["x-m5-execution"]
    first, pair = profile["checks"][0], profile["checks"][-1]
    actions = {
        "missing_check": lambda: profile["checks"].pop(),
        "duplicate_id": lambda: first.update(check_id="static"),
        "duplicate_path": lambda: first.update(clause_path="verification/static/0"),
        "bad_interfaces": lambda: profile.update(accepts_interfaces=[]),
        "bad_old_ref": lambda: profile["replaces_ref"].update(
            digest="sha256:" + "0" * 64
        ),
        "bad_replaces": lambda: contract.update(replaces="other@1.0.0"),
        "bad_rollback": lambda: contract["rollback"].update(pointer="other@1.0.0"),
        "bad_repeat": lambda: profile.update(repetitions=1),
        "bad_profile": lambda: profile.update(profile="unknown"),
        "high_limit": lambda: profile["runner"].update(process_limit=129),
        "bool_limit": lambda: profile["runner"].update(cpu_limit=True),
        "unmapped_target": lambda: contract["target_effects"].append("unmapped"),
        "empty_target": lambda: contract.update(target_effects=[]),
        "wrong_kind": lambda: first.update(
            test_id="executor", artifact_ids=["executor"]
        ),
        "subject_checker_overlap": lambda: profile["executor"].update(
            artifact_ids=["executor", "target"]
        ),
        "missing_helper": lambda: profile["executor"].update(
            artifact_ids=["executor", "missing"]
        ),
        "pair_old_expected": lambda: pair.update(old_expected=True),
        "pair_false": lambda: pair.update(pair_expected=False),
    }
    if mutation in actions:
        actions[mutation]()
    else:
        probe = {
            "probe_id": "probe",
            "test_id": "probe",
            "artifact_ids": ["probe"],
            "argv": [],
            "input_state": "old_final" if mutation == "probe_bad_state" else "initial",
        }
        first["subject_probes"] = (
            [probe, probe] if mutation == "duplicate_probe" else [probe]
        )


def test_snapshot_is_immutable_and_missing_package_is_rejected(tmp_path: Path) -> None:
    fixture = M5Fixture.create(tmp_path)
    bound = parse(fixture)
    before = bound.artifacts
    (fixture.package / "tests/behavioral/executor.py").unlink()
    assert bound.artifacts == before
    with pytest.raises(ExecutionContractError):
        parse(fixture)


def test_no_dependency_can_substitute_new_root_interface(tmp_path: Path) -> None:
    fixture = M5Fixture.create(tmp_path)
    request = request_for(fixture)
    task = request.task.model_copy(update={"required_interfaces": ("policy/v1",)})
    request = request.model_copy(update={"task": task})
    with pytest.raises(ExecutionContractError):
        parse_execution_contract(
            request, fixture.base.registry, LocalArtifactResolver({})
        )


def test_forged_publication_and_denied_principal_are_not_credentials(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    fixture = M5Fixture.create(tmp_path)
    request = request_for(fixture)
    for modified in (
        request.model_copy(
            update={"new": replace(fixture.new, registry_status="ACTIVE")}
        ),
        request.model_copy(update={"principal": Principal("stranger")}),
    ):
        with pytest.raises(ExecutionContractError):
            parse_execution_contract(
                modified, fixture.base.registry, LocalArtifactResolver({})
            )


def test_approval_binds_each_runtime_input_and_domain(tmp_path: Path) -> None:
    from contractcapsule.validate.approvals import Approval, activation_subject

    bound = parse(M5Fixture.create(tmp_path))
    now = datetime(2026, 9, 10, tzinfo=UTC)
    authority = ApprovalAuthority("synthetic", b"synthetic-secret-long-enough")
    approval = authority.issue_execution(
        bound, issued_at=now, expires_at=now + timedelta(minutes=5), synthetic=True
    )
    verifier = authority.verifier()
    changes = {
        "operation_id": "other-operation",
        "principal": Principal("other"),
        "source_commit": "sha1:" + "b" * 40,
        "model_id": "other-model",
        "budget": ViewBudget(model_input_tokens=9999),
        "tokenizer_profile": "other",
        "renderer_version": "other",
        "task": bound.request.task.model_copy(update={"text": "different"}),
    }
    for field, value in changes.items():
        changed = bound.model_copy(
            update={"request": bound.request.model_copy(update={field: value})}
        )
        with pytest.raises(ApprovalError):
            verifier.verify_execution(approval, changed, now=now)
    activation = authority.issue(
        domain="activation",
        operation_id=bound.request.operation_id,
        subject=approval.subject,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
        synthetic=True,
    )
    with pytest.raises(ApprovalError):
        verifier.verify_execution(activation, bound, now=now)
    bad: object
    for bad in (
        None,
        {},
        approval.model_copy(update={"signature": "bad"}),
        Approval.model_construct(issuer=None),
    ):
        with pytest.raises(ApprovalError):
            verifier.verify_execution(bad, bound, now=now)
    with pytest.raises(ApprovalError):
        verifier.verify_execution(approval, bound, now=now - timedelta(seconds=1))
    subject = activation_subject(
        operation_id=bound.request.operation_id,
        prepared_digest=approval.subject,
        scope_digest=approval.subject,
        request_digest=approval.subject,
        expected_generation=1,
    )
    assert subject != approval.subject


def test_raw_extension_rejects_non_json_without_serializer_coercion(
    tmp_path: Path,
) -> None:
    from types import MappingProxyType

    from contractcapsule.validate.contracts import _raw_containers

    for value in (
        {1: "coerced key"},
        {"checks": {"not an array"}},
        {"a": Path("path")},
    ):
        with pytest.raises(ValueError):
            _raw_containers(MappingProxyType(value))


def test_extension_identity_and_legacy_publication_unchanged(tmp_path: Path) -> None:
    from contractcapsule.models.canonical import canonical_digest, capsule_wire_dict
    from tests.m2_helpers import capsule_with_digest

    fixture = M5Fixture.create(tmp_path)
    raw = capsule_wire_dict(fixture.new.capsule)
    raw["replacement_contract"]["extensions"]["x-m5-execution"]["runner"][
        "timeout_seconds"
    ] = 200
    assert (
        canonical_digest(capsule_with_digest(raw))
        != fixture.new.capsule.control_manifest.content_digest
    )
    assert fixture.old.capsule.replacement_contract.extensions == {}
    assert (
        fixture.base.registry.get("com.example.policy", "1.0.0", Principal("reader"))
        == fixture.old
    )


def test_empty_target_already_rejected_by_frozen_core(tmp_path: Path) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        M5Fixture.create(tmp_path, lambda raw: mutate_profile(raw, "empty_target"))


@pytest.mark.parametrize(
    "mutation", ["duplicate_test_id", "missing_checksum", "wrong_checksum"]
)
def test_reciprocal_artifact_locks_rejected_before_publication(
    tmp_path: Path, mutation: str
) -> None:
    from pydantic import ValidationError

    def amend(raw: dict[str, Any]) -> None:
        integrity = raw["tests_integrity"]
        if mutation == "duplicate_test_id":
            integrity["tests"][1]["test_id"] = integrity["tests"][0]["test_id"]
        elif mutation == "missing_checksum":
            integrity["artifact_checksums"].pop()
        else:
            integrity["artifact_checksums"][-1]["digest"] = "sha256:" + "0" * 64

    if mutation == "duplicate_test_id":
        fixture = M5Fixture.create(tmp_path, amend)
        with pytest.raises(ExecutionContractError):
            parse(fixture)
    else:
        with pytest.raises(ValidationError):
            M5Fixture.create(tmp_path, amend)


def test_malformed_nominal_request_does_not_bypass_strict_fields(
    tmp_path: Path,
) -> None:
    fixture = M5Fixture.create(tmp_path)
    request = request_for(fixture).model_copy(update={"source_commit": 123})
    resolver = LocalArtifactResolver(
        {fixture.new.capsule.control_manifest.content_digest: fixture.package}
    )
    with pytest.raises(ExecutionContractError):
        parse_execution_contract(request, fixture.base.registry, resolver)


def test_lower_cpu_limit_preserves_exact_numeric_value(tmp_path: Path) -> None:
    def amend(raw: dict[str, Any]) -> None:
        raw["replacement_contract"]["extensions"]["x-m5-execution"]["runner"][
            "cpu_limit"
        ] = 0.5

    assert parse(M5Fixture.create(tmp_path, amend)).profile.runner.cpu_limit == 0.5


def test_declared_probe_is_locked_and_snapshot_phase_checked(tmp_path: Path) -> None:
    def amend(raw: dict[str, Any]) -> None:
        profile = raw["replacement_contract"]["extensions"]["x-m5-execution"]
        profile["checks"][0]["subject_probes"] = [
            {
                "probe_id": "initial-probe",
                "test_id": "probe",
                "artifact_ids": ["probe"],
                "argv": ["--initial"],
                "input_state": "initial",
            }
        ]

    bound = parse(M5Fixture.create(tmp_path, amend))
    assert bound.profile.checks[0].subject_probes[0].input_state == "initial"


def test_approval_rejects_changed_image_program_repeat_or_signature(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    bound = parse(M5Fixture.create(tmp_path))
    now = datetime(2026, 9, 10, tzinfo=UTC)
    authority = ApprovalAuthority("synthetic", b"synthetic-secret-long-enough")
    approval = authority.issue_execution(
        bound, issued_at=now, expires_at=now + timedelta(minutes=1), synthetic=True
    )
    changed_profile = bound.profile.model_copy(update={"repetitions": 1})
    runner = bound.profile.runner.model_copy(
        update={"image_digest": "sha256:" + "b" * 64}
    )
    signature = bound.request.new.capsule.detached_signature
    assert signature is not None
    capsule = bound.request.new.capsule.model_copy(
        update={
            "detached_signature": signature.model_copy(update={"value": "tampered"})
        }
    )
    new = replace(bound.request.new, capsule=capsule)
    for changed in (
        bound.model_copy(update={"profile": changed_profile}),
        bound.model_copy(
            update={"profile": bound.profile.model_copy(update={"runner": runner})}
        ),
        bound.model_copy(
            update={
                "artifacts": (
                    bound.artifacts[0].model_copy(update={"data": b"bad"}),
                    *bound.artifacts[1:],
                )
            }
        ),
        bound.model_copy(
            update={"request": bound.request.model_copy(update={"new": new})}
        ),
    ):
        with pytest.raises(ApprovalError):
            authority.verifier().verify_execution(approval, changed, now=now)


def test_artifact_path_alias_is_not_mountable(tmp_path: Path) -> None:
    fixture = M5Fixture.create(tmp_path)
    path = fixture.package / "tests/behavioral/executor.py"
    path.unlink()
    path.symlink_to(fixture.package / "tests/behavioral/target.py")
    with pytest.raises(ExecutionContractError):
        parse(fixture)
