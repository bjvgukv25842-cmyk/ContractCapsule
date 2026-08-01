"""Executable reference semantics for CCS-2.1 context replacement.

This module is deliberately in-memory and small.  It defines the M1 model used
to falsify the frozen safety rules; later modules own schemas, persistence,
production compilation, and agent integration.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class BlockerCode(StrEnum):
    """Stable fail-closed outcomes emitted by the reference semantics."""

    NONE = "NONE"
    MALFORMED_CAPSULE = "MALFORMED_CAPSULE"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    INTEGRITY_FAILED = "INTEGRITY_FAILED"
    UNAUTHORIZED_CAPSULE = "UNAUTHORIZED_CAPSULE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    MISSING_MANDATORY_DEPENDENCY = "MISSING_MANDATORY_DEPENDENCY"
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
    P0_NOT_EXACT = "P0_NOT_EXACT"
    P0_BUDGET_OVERFLOW = "P0_BUDGET_OVERFLOW"
    MANDATORY_CLOSURE_BUDGET_OVERFLOW = "MANDATORY_CLOSURE_BUDGET_OVERFLOW"
    INCOMPATIBLE_INTERFACE = "INCOMPATIBLE_INTERFACE"
    INCOMPATIBLE_REPLACEMENT_TARGET = "INCOMPATIBLE_REPLACEMENT_TARGET"
    TARGET_EFFECT_FAILED = "TARGET_EFFECT_FAILED"
    PROTECTED_INVARIANT_FAILED = "PROTECTED_INVARIANT_FAILED"
    FORBIDDEN_SPILLOVER = "FORBIDDEN_SPILLOVER"
    IRREVERSIBLE_SIDE_EFFECT_UNCONTROLLED = (
        "IRREVERSIBLE_SIDE_EFFECT_UNCONTROLLED"
    )
    UNSAFE_ACTIVATION_BOUNDARY = "UNSAFE_ACTIVATION_BOUNDARY"
    ACTIVATION_NOT_APPLIED = "ACTIVATION_NOT_APPLIED"


@dataclass(frozen=True)
class Principal:
    principal_id: str


@dataclass(frozen=True)
class Budget:
    tokens: int


@dataclass(frozen=True)
class TaskContext:
    task_id: str
    repository: str
    path: str
    environment: str
    required_interfaces: frozenset[str]
    irreversible_external_action: bool = False
    preflight_completed: bool = False
    approval_granted: bool = False
    compensation_available: bool = False


@dataclass(frozen=True)
class SafeBoundary:
    before_next_action: bool


@dataclass(frozen=True)
class Manifest:
    capsule_id: str
    version: str
    authorized_principals: frozenset[str]
    repositories: frozenset[str]
    path_prefixes: tuple[str, ...]
    environments: frozenset[str]
    provides: frozenset[str]
    lifecycle: str

    @property
    def reference(self) -> str:
        return f"{self.capsule_id}@{self.version}"


@dataclass(frozen=True)
class Atom:
    atom_id: str
    statement: str
    compression_class: str
    token_cost: int
    relevance: int
    evidence_refs: frozenset[str]

    @property
    def is_p0(self) -> bool:
        return self.compression_class == "P0_EXACT"


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    digest: str
    exact_text: str
    fresh: bool


@dataclass(frozen=True)
class DependencyGraph:
    requires: frozenset[tuple[str, str]]
    conflicts: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class ReplacementContract:
    replaces: str | None
    accepts_interfaces: frozenset[str]
    target_effects_passed: bool
    protected_invariants_passed: bool
    forbidden_spillover_detected: bool


@dataclass(frozen=True)
class CompressionPolicy:
    p0_exact: bool


@dataclass(frozen=True)
class IntegrityBundle:
    valid: bool


@dataclass(frozen=True)
class Capsule:
    """The seven immutable CCS-2.1 core modules."""

    manifest: Manifest
    atoms: frozenset[Atom]
    evidence: frozenset[Evidence]
    dependency_graph: DependencyGraph
    replacement_contract: ReplacementContract
    compression_policy: CompressionPolicy
    integrity: IntegrityBundle

    @property
    def reference(self) -> str:
        return self.manifest.reference


@dataclass(frozen=True)
class CompiledView:
    capsule_refs: tuple[str, ...]
    task_id: str
    principal_id: str
    adapter: str
    content: str
    selected_atom_ids: frozenset[str]
    exact_atom_ids: frozenset[str]
    evidence_handles: frozenset[str]
    eligibility_checked: tuple[str, ...]
    ranked_capsules: tuple[str, ...]
    audit_phases: tuple[str, ...]
    missing_dependencies: frozenset[str]
    conflicts: frozenset[tuple[str, str]]
    dependency_closed: bool
    p0_preserved: bool
    blockers: tuple[BlockerCode, ...]


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    blockers: tuple[BlockerCode, ...]

    @property
    def reason(self) -> BlockerCode:
        return self.blockers[0] if self.blockers else BlockerCode.NONE


@dataclass(frozen=True)
class ReplacementDecision:
    old_capsule: str
    new_capsule: str
    allowed: bool
    target_effect_realized: bool
    protected_invariants_preserved: bool
    forbidden_spillover_detected: bool
    interface_compatible: bool
    blockers: tuple[BlockerCode, ...]

    @property
    def reason(self) -> BlockerCode:
        return self.blockers[0] if self.blockers else BlockerCode.NONE


@dataclass(frozen=True)
class ActivationCandidate:
    old: Capsule
    new: Capsule
    view: CompiledView
    validation: ValidationReport
    replacement: ReplacementDecision


@dataclass(frozen=True)
class ActivationReceipt:
    activated: bool
    previous_capsule: str
    active_capsule: str
    blockers: tuple[BlockerCode, ...]

    @property
    def reason(self) -> BlockerCode:
        return self.blockers[0] if self.blockers else BlockerCode.NONE


@dataclass(frozen=True)
class RollbackReceipt:
    rolled_back: bool
    replaced_capsule: str
    active_capsule: str
    blockers: tuple[BlockerCode, ...]

    @property
    def reason(self) -> BlockerCode:
        return self.blockers[0] if self.blockers else BlockerCode.NONE


def _unique_blockers(*groups: Iterable[BlockerCode]) -> tuple[BlockerCode, ...]:
    result: list[BlockerCode] = []
    seen: set[BlockerCode] = set()
    for group in groups:
        for blocker in group:
            if blocker is BlockerCode.NONE or blocker in seen:
                continue
            seen.add(blocker)
            result.append(blocker)
    return tuple(result)


def _well_formedness(capsule: Capsule) -> tuple[BlockerCode, ...]:
    blockers: list[BlockerCode] = []
    manifest = capsule.manifest
    if (
        not manifest.capsule_id
        or not manifest.version
        or manifest.lifecycle not in {"PUBLISHED", "ACTIVE"}
        or not manifest.repositories
        or not manifest.path_prefixes
        or not manifest.environments
    ):
        blockers.append(BlockerCode.MALFORMED_CAPSULE)
    if not capsule.integrity.valid:
        blockers.append(BlockerCode.INTEGRITY_FAILED)

    evidence_by_id = {
        evidence.evidence_id: evidence for evidence in capsule.evidence
    }
    for evidence in capsule.evidence:
        if not evidence.evidence_id or not evidence.digest or not evidence.exact_text:
            blockers.append(BlockerCode.MISSING_EVIDENCE)
    for atom in capsule.atoms:
        if (
            not atom.atom_id
            or not atom.statement
            or atom.token_cost < 0
            or not atom.evidence_refs
        ):
            blockers.append(BlockerCode.MALFORMED_CAPSULE)
        if not atom.evidence_refs.issubset(evidence_by_id):
            blockers.append(BlockerCode.MISSING_EVIDENCE)
        if atom.is_p0 and not capsule.compression_policy.p0_exact:
            blockers.append(BlockerCode.P0_NOT_EXACT)
    return _unique_blockers(blockers)


def _eligibility_blockers(
    capsule: Capsule, task: TaskContext, principal: Principal
) -> tuple[BlockerCode, ...]:
    blockers: list[BlockerCode] = []
    manifest = capsule.manifest
    if principal.principal_id not in manifest.authorized_principals:
        blockers.append(BlockerCode.UNAUTHORIZED_CAPSULE)
    if (
        task.repository not in manifest.repositories
        or task.environment not in manifest.environments
        or not any(task.path.startswith(prefix) for prefix in manifest.path_prefixes)
    ):
        blockers.append(BlockerCode.OUT_OF_SCOPE)
    if any(not evidence.fresh for evidence in capsule.evidence):
        blockers.append(BlockerCode.STALE_EVIDENCE)
    return _unique_blockers(blockers)


def _atom_index(capsules: Iterable[Capsule]) -> dict[str, Atom]:
    return {
        atom.atom_id: atom
        for capsule in capsules
        for atom in capsule.atoms
    }


def _dependency_closure(
    selected: set[str],
    atom_by_id: dict[str, Atom],
    requires: frozenset[tuple[str, str]],
) -> tuple[set[str], set[str]]:
    closed = set(selected)
    missing: set[str] = set()
    changed = True
    while changed:
        changed = False
        for source, dependency in sorted(requires):
            if source not in closed:
                continue
            if dependency not in atom_by_id:
                missing.add(dependency)
                continue
            if dependency not in closed:
                closed.add(dependency)
                changed = True
    return closed, missing


def compile_view(
    capsules: Iterable[Capsule],
    task: TaskContext,
    principal: Principal,
    budget: Budget,
    adapter: str,
) -> CompiledView:
    """Compile an auditable view after fail-closed eligibility checks."""

    supplied = tuple(capsules)
    eligibility_checked = tuple(capsule.reference for capsule in supplied)
    blockers: list[BlockerCode] = []
    eligible: list[Capsule] = []

    for capsule in supplied:
        structural_blockers = _well_formedness(capsule)
        blockers.extend(structural_blockers)
        eligibility_blockers = _eligibility_blockers(capsule, task, principal)
        blockers.extend(eligibility_blockers)
        if not structural_blockers and not eligibility_blockers:
            eligible.append(capsule)

    audit_phases: tuple[str, ...] = ("eligibility",)
    ranked: tuple[Capsule, ...] = ()
    if eligible:
        audit_phases += ("ranking",)
        ranked = tuple(
            sorted(
                eligible,
                key=lambda capsule: (
                    -sum(atom.relevance for atom in capsule.atoms),
                    capsule.reference,
                ),
            )
        )

    atom_by_id = _atom_index(ranked)
    selected = {
        atom.atom_id
        for capsule in ranked
        for atom in capsule.atoms
        if atom.is_p0 or atom.relevance > 0
    }
    requires = frozenset(
        edge for capsule in ranked for edge in capsule.dependency_graph.requires
    )
    selected, missing_dependencies = _dependency_closure(
        selected, atom_by_id, requires
    )
    if missing_dependencies:
        blockers.append(BlockerCode.MISSING_MANDATORY_DEPENDENCY)

    declared_conflicts = frozenset(
        edge for capsule in ranked for edge in capsule.dependency_graph.conflicts
    )
    conflicts = frozenset(
        (left, right)
        for left, right in declared_conflicts
        if left in selected and right in selected
    )
    if conflicts:
        blockers.append(BlockerCode.UNRESOLVED_CONFLICT)

    selected_atoms = tuple(
        sorted(
            (atom_by_id[atom_id] for atom_id in selected if atom_id in atom_by_id),
            key=lambda atom: (not atom.is_p0, -atom.relevance, atom.atom_id),
        )
    )
    exact_atom_ids = frozenset(
        atom.atom_id for atom in selected_atoms if atom.is_p0
    )
    p0_atom_ids = frozenset(
        atom.atom_id for atom in atom_by_id.values() if atom.is_p0
    )
    p0_cost = sum(atom.token_cost for atom in atom_by_id.values() if atom.is_p0)
    policies_are_exact = all(
        capsule.compression_policy.p0_exact for capsule in ranked
    )
    if not policies_are_exact and p0_atom_ids:
        blockers.append(BlockerCode.P0_NOT_EXACT)
    if p0_cost > budget.tokens:
        blockers.append(BlockerCode.P0_BUDGET_OVERFLOW)

    selected_cost = sum(atom.token_cost for atom in selected_atoms)
    if selected_cost > budget.tokens and p0_cost <= budget.tokens:
        blockers.append(BlockerCode.MANDATORY_CLOSURE_BUDGET_OVERFLOW)

    evidence_handles = frozenset(
        evidence_ref
        for atom in selected_atoms
        for evidence_ref in atom.evidence_refs
    )
    content = "\n".join(atom.statement for atom in selected_atoms)
    p0_preserved = (
        p0_atom_ids.issubset(exact_atom_ids)
        and policies_are_exact
        and p0_cost <= budget.tokens
    )
    dependency_closed = not missing_dependencies and all(
        source not in selected or dependency in selected
        for source, dependency in requires
    )

    return CompiledView(
        capsule_refs=tuple(capsule.reference for capsule in supplied),
        task_id=task.task_id,
        principal_id=principal.principal_id,
        adapter=adapter,
        content=content,
        selected_atom_ids=frozenset(selected),
        exact_atom_ids=exact_atom_ids,
        evidence_handles=evidence_handles,
        eligibility_checked=eligibility_checked,
        ranked_capsules=tuple(capsule.reference for capsule in ranked),
        audit_phases=audit_phases,
        missing_dependencies=frozenset(missing_dependencies),
        conflicts=conflicts,
        dependency_closed=dependency_closed,
        p0_preserved=p0_preserved,
        blockers=_unique_blockers(blockers),
    )


def validate_view(
    view: CompiledView,
    capsules: Iterable[Capsule],
    principal: Principal,
) -> ValidationReport:
    """Validate traceability, exact P0, closure, conflicts, and authorization."""

    supplied = tuple(capsules)
    blockers: list[BlockerCode] = list(view.blockers)
    if view.principal_id != principal.principal_id:
        blockers.append(BlockerCode.UNAUTHORIZED_CAPSULE)

    for capsule in supplied:
        blockers.extend(_well_formedness(capsule))
        if principal.principal_id not in capsule.manifest.authorized_principals:
            blockers.append(BlockerCode.UNAUTHORIZED_CAPSULE)

    ranked_refs = set(view.ranked_capsules)
    ranked = tuple(
        capsule for capsule in supplied if capsule.reference in ranked_refs
    )
    atom_by_id = _atom_index(ranked)
    evidence_ids = {
        evidence.evidence_id for capsule in ranked for evidence in capsule.evidence
    }
    selected_atoms = tuple(
        atom_by_id[atom_id]
        for atom_id in view.selected_atom_ids
        if atom_id in atom_by_id
    )
    if len(selected_atoms) != len(view.selected_atom_ids):
        blockers.append(BlockerCode.MALFORMED_CAPSULE)
    required_evidence = {
        evidence_ref
        for atom in selected_atoms
        for evidence_ref in atom.evidence_refs
    }
    if (
        not required_evidence.issubset(evidence_ids)
        or not required_evidence.issubset(view.evidence_handles)
    ):
        blockers.append(BlockerCode.MISSING_EVIDENCE)

    p0_ids = {atom.atom_id for atom in atom_by_id.values() if atom.is_p0}
    if not p0_ids.issubset(view.exact_atom_ids) or not view.p0_preserved:
        blockers.append(BlockerCode.P0_NOT_EXACT)
    if not view.dependency_closed:
        blockers.append(BlockerCode.MISSING_MANDATORY_DEPENDENCY)
    if view.conflicts:
        blockers.append(BlockerCode.UNRESOLVED_CONFLICT)

    unique = _unique_blockers(blockers)
    return ValidationReport(valid=not unique, blockers=unique)


def can_replace(
    old: Capsule, new: Capsule, task: TaskContext
) -> ReplacementDecision:
    """Evaluate compatibility and TER/PIP/BSR as separate obligations."""

    blockers: list[BlockerCode] = []
    blockers.extend(_well_formedness(old))
    blockers.extend(_well_formedness(new))
    contract = new.replacement_contract

    if contract.replaces != old.reference:
        blockers.append(BlockerCode.INCOMPATIBLE_REPLACEMENT_TARGET)
    interface_compatible = (
        old.manifest.provides.issubset(contract.accepts_interfaces)
        and task.required_interfaces.issubset(new.manifest.provides)
    )
    if not interface_compatible:
        blockers.append(BlockerCode.INCOMPATIBLE_INTERFACE)
    if not contract.target_effects_passed:
        blockers.append(BlockerCode.TARGET_EFFECT_FAILED)
    if not contract.protected_invariants_passed:
        blockers.append(BlockerCode.PROTECTED_INVARIANT_FAILED)
    if contract.forbidden_spillover_detected:
        blockers.append(BlockerCode.FORBIDDEN_SPILLOVER)

    external_action_controlled = (
        task.preflight_completed
        or task.approval_granted
        or task.compensation_available
    )
    if task.irreversible_external_action and not external_action_controlled:
        blockers.append(BlockerCode.IRREVERSIBLE_SIDE_EFFECT_UNCONTROLLED)

    unique = _unique_blockers(blockers)
    return ReplacementDecision(
        old_capsule=old.reference,
        new_capsule=new.reference,
        allowed=not unique,
        target_effect_realized=contract.target_effects_passed,
        protected_invariants_preserved=contract.protected_invariants_passed,
        forbidden_spillover_detected=contract.forbidden_spillover_detected,
        interface_compatible=interface_compatible,
        blockers=unique,
    )


def activate(
    candidate: ActivationCandidate, safe_boundary: SafeBoundary
) -> ActivationReceipt:
    """Atomically choose the new reference only when every gate passes."""

    boundary_blockers: tuple[BlockerCode, ...] = ()
    if not safe_boundary.before_next_action:
        boundary_blockers = (BlockerCode.UNSAFE_ACTIVATION_BOUNDARY,)
    blockers = _unique_blockers(
        boundary_blockers,
        candidate.view.blockers,
        candidate.validation.blockers,
        candidate.replacement.blockers,
    )
    activated = not blockers
    return ActivationReceipt(
        activated=activated,
        previous_capsule=candidate.old.reference,
        active_capsule=(
            candidate.new.reference if activated else candidate.old.reference
        ),
        blockers=blockers,
    )


def rollback(receipt: ActivationReceipt) -> RollbackReceipt:
    """Restore the previous capsule reference retained by activation."""

    if not receipt.activated:
        return RollbackReceipt(
            rolled_back=False,
            replaced_capsule=receipt.active_capsule,
            active_capsule=receipt.active_capsule,
            blockers=(BlockerCode.ACTIVATION_NOT_APPLIED,),
        )
    return RollbackReceipt(
        rolled_back=True,
        replaced_capsule=receipt.active_capsule,
        active_capsule=receipt.previous_capsule,
        blockers=(),
    )


__all__ = [
    "ActivationCandidate",
    "ActivationReceipt",
    "Atom",
    "BlockerCode",
    "Budget",
    "Capsule",
    "CompiledView",
    "CompressionPolicy",
    "DependencyGraph",
    "Evidence",
    "IntegrityBundle",
    "Manifest",
    "Principal",
    "ReplacementContract",
    "ReplacementDecision",
    "RollbackReceipt",
    "SafeBoundary",
    "TaskContext",
    "ValidationReport",
    "activate",
    "can_replace",
    "compile_view",
    "rollback",
    "validate_view",
]
