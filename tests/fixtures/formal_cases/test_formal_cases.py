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
        assert executed.receipt.blockers == (expected_blocker,)


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


def test_stripped_view_metadata_fails_closed() -> None:
    executed = _execute(_load_case(CASES_DIR / "valid_replacement.json"))
    stripped_view = replace(
        executed.view,
        content="",
        selected_atom_ids=frozenset(),
        exact_atom_ids=frozenset(),
        evidence_handles=frozenset(),
        ranked_capsules=(),
    )
    principal = Principal(executed.data["principal"])
    validation = validate_view(stripped_view, (executed.candidate,), principal)
    receipt = activate(
        ActivationCandidate(
            old=executed.old,
            new=executed.candidate,
            view=stripped_view,
            validation=validation,
            replacement=executed.decision,
        ),
        SafeBoundary(before_next_action=True),
    )

    assert not validation.valid
    assert not receipt.activated
    assert receipt.active_capsule == executed.old.reference
    assert BlockerCode.VIEW_INCONSISTENT in receipt.blockers


def test_activation_rejects_a_view_compiled_for_no_candidate() -> None:
    executed = _execute(_load_case(CASES_DIR / "valid_replacement.json"))
    principal = Principal(executed.data["principal"])
    task = _task(executed.data["task"])
    unrelated_view = compile_view(
        (), task, principal, Budget(executed.data["budget"]), "test-adapter"
    )
    unrelated_validation = validate_view(unrelated_view, (), principal)
    receipt = activate(
        ActivationCandidate(
            old=executed.old,
            new=executed.candidate,
            view=unrelated_view,
            validation=unrelated_validation,
            replacement=executed.decision,
        ),
        SafeBoundary(before_next_action=True),
    )

    assert not receipt.activated
    assert receipt.active_capsule == executed.old.reference
    assert BlockerCode.CANDIDATE_MISMATCH in receipt.blockers


def test_activation_rejects_validation_for_a_different_view() -> None:
    executed = _execute(_load_case(CASES_DIR / "valid_replacement.json"))
    modified_view = replace(executed.view, content="tampered")
    receipt = activate(
        ActivationCandidate(
            old=executed.old,
            new=executed.candidate,
            view=modified_view,
            validation=executed.validation,
            replacement=executed.decision,
        ),
        SafeBoundary(before_next_action=True),
    )

    assert not receipt.activated
    assert receipt.active_capsule == executed.old.reference
    assert BlockerCode.VALIDATION_MISMATCH in receipt.blockers


@pytest.mark.parametrize(
    "case_name",
    ["missing_mandatory_dependency.json", "unresolved_conflict.json"],
)
def test_validation_recomputes_graph_failures_from_capsules(
    case_name: str,
) -> None:
    executed = _execute(_load_case(CASES_DIR / case_name))
    cleared_view = replace(
        executed.view,
        blockers=(),
        missing_dependencies=frozenset(),
        conflicts=frozenset(),
        dependency_closed=True,
    )
    principal = Principal(executed.data["principal"])
    validation = validate_view(cleared_view, (executed.candidate,), principal)

    assert not validation.valid
    assert validation.reason is BlockerCode.VIEW_INCONSISTENT


def test_activation_binds_the_decision_to_the_compiled_task() -> None:
    executed = _execute(_load_case(CASES_DIR / "valid_replacement.json"))
    principal = Principal(executed.data["principal"])
    benign_task = _task(executed.data["task"])
    irreversible_task = replace(
        benign_task,
        irreversible_external_action=True,
        preflight_completed=False,
        approval_granted=False,
        compensation_available=False,
    )
    irreversible_view = compile_view(
        (executed.candidate,),
        irreversible_task,
        principal,
        Budget(executed.data["budget"]),
        executed.data["adapter"],
    )
    irreversible_validation = validate_view(
        irreversible_view, (executed.candidate,), principal
    )
    benign_decision = can_replace(
        executed.old, executed.candidate, benign_task
    )
    receipt = activate(
        ActivationCandidate(
            old=executed.old,
            new=executed.candidate,
            view=irreversible_view,
            validation=irreversible_validation,
            replacement=benign_decision,
        ),
        SafeBoundary(before_next_action=True),
    )

    assert not receipt.activated
    assert receipt.active_capsule == executed.old.reference
    assert BlockerCode.TASK_MISMATCH in receipt.blockers


def test_activation_binds_reports_to_the_candidate_core() -> None:
    executed = _execute(_load_case(CASES_DIR / "valid_replacement.json"))
    invalid_candidate = replace(
        executed.candidate, integrity=IntegrityBundle(valid=False)
    )
    receipt = activate(
        ActivationCandidate(
            old=executed.old,
            new=invalid_candidate,
            view=executed.view,
            validation=executed.validation,
            replacement=executed.decision,
        ),
        SafeBoundary(before_next_action=True),
    )

    assert not receipt.activated
    assert receipt.active_capsule == executed.old.reference
    assert BlockerCode.CANDIDATE_MISMATCH in receipt.blockers


def test_duplicate_atom_ids_fail_closed_before_budgeting() -> None:
    executed = _execute(_load_case(CASES_DIR / "valid_replacement.json"))
    first = next(atom for atom in executed.candidate.atoms if atom.is_p0)
    duplicate = replace(
        first,
        statement="A different P0 statement using the same identifier.",
        token_cost=6,
    )
    original = replace(first, token_cost=6)
    candidate = replace(
        executed.candidate,
        atoms=frozenset(
            {original, duplicate}
            | {atom for atom in executed.candidate.atoms if not atom.is_p0}
        ),
    )
    principal = Principal(executed.data["principal"])
    task = _task(executed.data["task"])
    view = compile_view((candidate,), task, principal, Budget(10), "test")
    validation = validate_view(view, (candidate,), principal)
    decision = can_replace(executed.old, candidate, task)
    receipt = activate(
        ActivationCandidate(
            old=executed.old,
            new=candidate,
            view=view,
            validation=validation,
            replacement=decision,
        ),
        SafeBoundary(before_next_action=True),
    )

    assert not receipt.activated
    assert receipt.active_capsule == executed.old.reference
    assert BlockerCode.MALFORMED_CAPSULE in receipt.blockers


def test_duplicate_evidence_ids_fail_closed() -> None:
    executed = _execute(_load_case(CASES_DIR / "valid_replacement.json"))
    first = next(iter(executed.candidate.evidence))
    duplicate = replace(first, exact_text="Different source span, same ID.")
    candidate = replace(
        executed.candidate,
        evidence=executed.candidate.evidence | frozenset({duplicate}),
    )
    principal = Principal(executed.data["principal"])
    task = _task(executed.data["task"])
    view = compile_view(
        (candidate,), task, principal, Budget(executed.data["budget"]), "test"
    )

    assert BlockerCode.MALFORMED_CAPSULE in view.blockers


def test_duplicate_atom_ids_across_compiled_capsules_fail_closed() -> None:
    executed = _execute(_load_case(CASES_DIR / "valid_replacement.json"))
    first = next(iter(executed.candidate.atoms))
    conflicting = replace(first, statement="Conflicting statement for same ID.")
    second = replace(
        executed.candidate,
        manifest=replace(
            executed.candidate.manifest,
            capsule_id="another-policy",
            version="1",
        ),
        atoms=(executed.candidate.atoms - frozenset({first}))
        | frozenset({conflicting}),
    )
    principal = Principal(executed.data["principal"])
    task = _task(executed.data["task"])
    view = compile_view(
        (executed.candidate, second),
        task,
        principal,
        Budget(executed.data["budget"] * 2),
        "test",
    )

    assert BlockerCode.MALFORMED_CAPSULE in view.blockers


def test_unknown_compression_class_is_malformed_and_fail_closed() -> None:
    executed = _execute(_load_case(CASES_DIR / "valid_replacement.json"))
    first = next(iter(executed.candidate.atoms))
    unknown = replace(
        first,
        compression_class="P0_CRITICAL",
        token_cost=10_000,
        relevance=0,
    )
    candidate = replace(
        executed.candidate,
        atoms=(executed.candidate.atoms - frozenset({first}))
        | frozenset({unknown}),
    )
    principal = Principal(executed.data["principal"])
    task = _task(executed.data["task"])
    view = compile_view((candidate,), task, principal, Budget(1), "test")
    validation = validate_view(view, (candidate,), principal)
    decision = can_replace(executed.old, candidate, task)
    receipt = activate(
        ActivationCandidate(
            old=executed.old,
            new=candidate,
            view=view,
            validation=validation,
            replacement=decision,
        ),
        SafeBoundary(before_next_action=True),
    )

    assert not receipt.activated
    assert receipt.active_capsule == executed.old.reference
    assert BlockerCode.MALFORMED_CAPSULE in receipt.blockers
