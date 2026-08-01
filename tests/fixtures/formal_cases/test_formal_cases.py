from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from contractcapsule.formal import (
    ActivationCandidate,
    Atom,
    BlockerCode,
    Budget,
    Capsule,
    CompressionPolicy,
    DependencyGraph,
    Evidence,
    IntegrityBundle,
    Manifest,
    Principal,
    ReplacementContract,
    SafeBoundary,
    TaskContext,
    activate,
    can_replace,
    compile_view,
    rollback,
    validate_view,
)

CASES_DIR = Path(__file__).parent / "cases"
EXPECTED_CASE_FILES = {
    "failed_protected_invariant.json",
    "incompatible_interface.json",
    "irreversible_external_side_effect.json",
    "missing_mandatory_dependency.json",
    "p0_overflow.json",
    "safe_rollback.json",
    "stale_evidence.json",
    "unauthorized_capsule.json",
    "unresolved_conflict.json",
    "valid_replacement.json",
}


@dataclass(frozen=True)
class ExecutedCase:
    data: dict[str, Any]
    old: Capsule
    candidate: Capsule
    view: Any
    validation: Any
    decision: Any
    receipt: Any


def _load_case(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fixture_file:
        value = json.load(fixture_file)
    assert isinstance(value, dict)
    return value


def _manifest(data: dict[str, Any]) -> Manifest:
    capsule_id, version = data["reference"].split("@", maxsplit=1)
    return Manifest(
        capsule_id=capsule_id,
        version=version,
        authorized_principals=frozenset(data["authorized_principals"]),
        repositories=frozenset({"example/api"}),
        path_prefixes=("src/",),
        environments=frozenset({"prod"}),
        provides=frozenset(data["provides"]),
        lifecycle="PUBLISHED",
    )


def _capsule(data: dict[str, Any]) -> Capsule:
    graph = data["graph"]
    contract = data["replacement_contract"]
    return Capsule(
        manifest=_manifest(data["manifest"]),
        atoms=frozenset(
            Atom(
                atom_id=atom["id"],
                statement=atom["statement"],
                compression_class=atom["compression_class"],
                token_cost=atom["token_cost"],
                relevance=atom["relevance"],
                evidence_refs=frozenset(atom["evidence_refs"]),
            )
            for atom in data["atoms"]
        ),
        evidence=frozenset(
            Evidence(
                evidence_id=evidence["id"],
                digest=evidence["digest"],
                exact_text=evidence["exact_text"],
                fresh=evidence["fresh"],
            )
            for evidence in data["evidence"]
        ),
        dependency_graph=DependencyGraph(
            requires=frozenset(tuple(edge) for edge in graph["requires"]),
            conflicts=frozenset(tuple(edge) for edge in graph["conflicts"]),
        ),
        replacement_contract=ReplacementContract(
            replaces=contract["replaces"],
            accepts_interfaces=frozenset(contract["accepts_interfaces"]),
            target_effects_passed=contract["target_effects_passed"],
            protected_invariants_passed=contract[
                "protected_invariants_passed"
            ],
            forbidden_spillover_detected=contract[
                "forbidden_spillover_detected"
            ],
        ),
        compression_policy=CompressionPolicy(
            p0_exact=data["compression_policy"]["p0_exact"]
        ),
        integrity=IntegrityBundle(valid=data["integrity"]["valid"]),
    )


def _task(data: dict[str, Any]) -> TaskContext:
    return TaskContext(
        task_id=data["task_id"],
        repository="example/api",
        path="src/auth/policy.py",
        environment="prod",
        required_interfaces=frozenset(data["required_interfaces"]),
        irreversible_external_action=data["irreversible_external_action"],
        preflight_completed=data["preflight_completed"],
        approval_granted=data["approval_granted"],
        compensation_available=data["compensation_available"],
    )


def _execute(data: dict[str, Any]) -> ExecutedCase:
    old = _capsule(data["old"])
    candidate = _capsule(data["candidate"])
    principal = Principal(data["principal"])
    task = _task(data["task"])
    view = compile_view(
        (candidate,), task, principal, Budget(data["budget"]), data["adapter"]
    )
    validation = validate_view(view, (candidate,), principal)
    decision = can_replace(old, candidate, task)
    activation_candidate = ActivationCandidate(
        old=old,
        new=candidate,
        view=view,
        validation=validation,
        replacement=decision,
    )
    receipt = activate(
        activation_candidate,
        SafeBoundary(before_next_action=data["safe_boundary"]),
    )
    return ExecutedCase(
        data=data,
        old=old,
        candidate=candidate,
        view=view,
        validation=validation,
        decision=decision,
        receipt=receipt,
    )


CASE_PATHS = sorted(CASES_DIR.glob("*.json"))


def test_fixture_inventory_is_exactly_the_ten_frozen_formal_cases() -> None:
    assert {path.name for path in CASE_PATHS} == EXPECTED_CASE_FILES
    assert len(CASE_PATHS) == 10

    for path in CASE_PATHS:
        case = _load_case(path)
        assert case["name"]
        assert case["description"]
        assert set(case["expected"]) == {
            "activation",
            "active_capsule",
            "blocker",
            "rollback",
        }
        assert case["expected"]["blocker"] in {
            blocker.value for blocker in BlockerCode
        }


@pytest.mark.parametrize("case_path", CASE_PATHS, ids=lambda path: path.stem)
def test_formal_case_has_the_declared_fail_closed_outcome(case_path: Path) -> None:
    executed = _execute(_load_case(case_path))
    expected = executed.data["expected"]
    expected_blocker = BlockerCode(expected["blocker"])

    assert executed.receipt.activated is expected["activation"]
    assert executed.receipt.active_capsule == expected["active_capsule"]
    assert executed.receipt.reason is expected_blocker

    if expected["activation"]:
        assert executed.receipt.blockers == ()
        assert expected_blocker is BlockerCode.NONE
        assert executed.receipt.previous_capsule == executed.old.reference
        assert executed.receipt.active_capsule == executed.candidate.reference
    else:
        assert executed.receipt.active_capsule == executed.old.reference
        assert expected_blocker in executed.receipt.blockers


def test_valid_replacement_closes_dependencies_and_preserves_exact_evidence() -> None:
    executed = _execute(_load_case(CASES_DIR / "valid_replacement.json"))
    exact_evidence = {
        evidence.evidence_id: evidence.exact_text
        for evidence in executed.candidate.evidence
    }

    assert executed.receipt.activated
    assert executed.view.selected_atom_ids == frozenset(
        {"auth.ttl-15m", "security.audit-enabled"}
    )
    assert executed.view.dependency_closed
    assert executed.view.p0_preserved
    assert executed.view.exact_atom_ids == frozenset({"auth.ttl-15m"})
    assert executed.view.evidence_handles == frozenset(exact_evidence)
    assert {
        evidence.evidence_id: evidence.exact_text
        for evidence in executed.candidate.evidence
    } == exact_evidence
    assert executed.receipt.previous_capsule == "auth-policy@1"
    assert executed.receipt.active_capsule == "auth-policy@2"


def test_ineligible_capsule_is_never_ranked() -> None:
    executed = _execute(_load_case(CASES_DIR / "unauthorized_capsule.json"))

    assert executed.candidate.reference in executed.view.eligibility_checked
    assert executed.candidate.reference not in executed.view.ranked_capsules
    assert executed.view.audit_phases == ("eligibility",)
    assert executed.receipt.reason is BlockerCode.UNAUTHORIZED_CAPSULE


def test_unresolved_conflict_is_visible_in_the_compiled_view() -> None:
    executed = _execute(_load_case(CASES_DIR / "unresolved_conflict.json"))

    assert executed.view.conflicts == frozenset(
        {("auth.jwt-only", "auth.session-only")}
    )
    assert BlockerCode.UNRESOLVED_CONFLICT in executed.validation.blockers
    assert not executed.receipt.activated


def test_safe_rollback_restores_the_prior_active_capsule() -> None:
    executed = _execute(_load_case(CASES_DIR / "safe_rollback.json"))

    assert executed.data["expected"]["rollback"] is True
    rollback_receipt = rollback(executed.receipt)
    assert rollback_receipt.rolled_back
    assert rollback_receipt.active_capsule == executed.old.reference
    assert rollback_receipt.replaced_capsule == executed.candidate.reference
    assert rollback_receipt.reason is BlockerCode.NONE


def test_activation_outside_a_safe_boundary_preserves_the_old_capsule() -> None:
    executed = _execute(_load_case(CASES_DIR / "valid_replacement.json"))
    unsafe_receipt = activate(
        ActivationCandidate(
            old=executed.old,
            new=executed.candidate,
            view=executed.view,
            validation=executed.validation,
            replacement=executed.decision,
        ),
        SafeBoundary(before_next_action=False),
    )

    assert not unsafe_receipt.activated
    assert unsafe_receipt.active_capsule == executed.old.reference
    assert unsafe_receipt.reason is BlockerCode.UNSAFE_ACTIVATION_BOUNDARY


def test_missing_formal_evidence_is_a_well_formedness_failure() -> None:
    executed = _execute(_load_case(CASES_DIR / "valid_replacement.json"))
    malformed = replace(executed.candidate, evidence=frozenset())
    task = _task(executed.data["task"])
    principal = Principal(executed.data["principal"])
    view = compile_view(
        (malformed,),
        task,
        principal,
        Budget(executed.data["budget"]),
        executed.data["adapter"],
    )
    validation = validate_view(view, (malformed,), principal)
    decision = can_replace(executed.old, malformed, task)
    receipt = activate(
        ActivationCandidate(
            old=executed.old,
            new=malformed,
            view=view,
            validation=validation,
            replacement=decision,
        ),
        SafeBoundary(before_next_action=True),
    )

    assert not receipt.activated
    assert receipt.active_capsule == executed.old.reference
    assert receipt.reason is BlockerCode.MISSING_EVIDENCE


def test_capsule_core_is_immutable() -> None:
    executed = _execute(_load_case(CASES_DIR / "valid_replacement.json"))

    with pytest.raises(FrozenInstanceError):
        executed.candidate.manifest = executed.old.manifest  # type: ignore[misc]
