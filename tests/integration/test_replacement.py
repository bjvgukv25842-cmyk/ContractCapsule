from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from contractcapsule.models.view import CapsuleRef
from contractcapsule.swap.controller import SwapController
from contractcapsule.swap.runtime_models import ActiveBinding, PreparedReplacement
from contractcapsule.validate.approvals import ApprovalAuthority, activation_subject
from tests.unit.test_swap_store import binding, make_store, scope


def prepared(old: ActiveBinding, current_scope, *, risk="low", required=False):
    new = old.model_copy(
        update={
            "capsule": CapsuleRef(
                capsule_id=old.capsule.capsule_id,
                version="2.0.0",
                digest="sha256:" + "3" * 64,
            ),
            "generation": old.generation + 1,
        }
    )
    return PreparedReplacement(
        prepared_id="prepared-1",
        scope_digest=current_scope.digest,
        operation_id="activate-1",
        request_digest="sha256:" + "a" * 64,
        old_binding=old,
        new_binding=new,
        evidence_digest="sha256:" + "b" * 64,
        expires_at="2026-09-19T00:00:00Z",
        payload=b"validated-prepared-evidence",
        effective_risk=risk,
        approval_required=required,
    )


def ready(tmp_path: Path):
    current_scope = scope()
    store = make_store(tmp_path / "registry.db", clock=lambda: datetime(2026, 9, 18, tzinfo=UTC))
    old = binding()
    store.initialize(current_scope, old, store.issue_bootstrap(current_scope, old))
    lease = store.begin_action(current_scope, "activate-1", "sha256:" + "a" * 64)
    store.end_action(current_scope, lease, outcome=b"validated")
    ticket = store.reserve_boundary(current_scope, "activate-1", 0, ttl=timedelta(minutes=1))
    return store, current_scope, old, ticket


def test_prepare_and_activate_updates_only_runtime_binding(tmp_path: Path):
    store, current_scope, old, ticket = ready(tmp_path)
    record = prepared(old, current_scope)
    controller = SwapController(store, current_scope, validator=lambda _record: True)
    controller.prepare(record)
    receipt = controller.activate(record.prepared_id, ticket)
    state = store.get(current_scope)
    assert receipt.applied and state.active == record.new_binding
    assert state.active.generation == 1
    replay = controller.activate(record.prepared_id, ticket)
    assert replay == receipt


def test_failed_gate_preserves_active_pointer(tmp_path: Path):
    store, current_scope, old, _ticket = ready(tmp_path)
    record = prepared(old, current_scope)
    controller = SwapController(store, current_scope, validator=lambda _record: False)
    with pytest.raises(ValueError, match="validation"):
        controller.prepare(record)
    assert store.get(current_scope).active == old


def test_rollback_restores_old_binding_at_new_generation(tmp_path: Path):
    store, current_scope, old, ticket = ready(tmp_path)
    record = prepared(old, current_scope)
    controller = SwapController(
        store,
        current_scope,
        validator=lambda _record: True,
        rollback_validator=lambda _receipt: True,
    )
    controller.prepare(record)
    receipt = controller.activate(record.prepared_id, ticket)
    # The rollback ticket is bound to the source activation operation.
    rollback_ticket = store.reserve_boundary(current_scope, "activate-1", 1)
    rollback = controller.rollback(receipt.receipt_id, rollback_ticket)
    assert rollback.applied
    assert store.get(current_scope).active == old.model_copy(update={"generation": 2})
    assert controller.rollback(receipt.receipt_id, rollback_ticket) == rollback


def test_activation_rejects_high_risk_without_distinct_approval(tmp_path: Path):
    store, current_scope, old, ticket = ready(tmp_path)
    record = prepared(old, current_scope, risk="high", required=False)
    controller = SwapController(store, current_scope, validator=lambda _record: True)
    controller.prepare(record)
    with pytest.raises(ValueError, match="approval"):
        controller.activate(record.prepared_id, ticket)


def test_high_risk_activation_requires_bound_activation_approval(tmp_path: Path):
    store, current_scope, old, ticket = ready(tmp_path)
    record = prepared(old, current_scope, risk="high")
    authority = ApprovalAuthority("reviewer", b"r" * 32)
    subject = activation_subject(
        operation_id=record.operation_id,
        prepared_digest=record.digest,
        scope_digest=record.scope_digest,
        request_digest=record.request_digest,
        expected_generation=record.old_binding.generation,
    )
    approval = authority.issue(
        domain="activation",
        operation_id=record.operation_id,
        subject=subject,
        issued_at=datetime(2026, 9, 18, tzinfo=UTC),
        expires_at=datetime(2026, 9, 19, tzinfo=UTC),
        synthetic=True,
    )
    controller = SwapController(
        store,
        current_scope,
        validator=lambda _record: True,
        approval_verifier=authority.verifier(),
    )
    controller.prepare(record)
    receipt = controller.activate(record.prepared_id, ticket, approval)
    assert receipt.approval_digest.startswith("sha256:")


def test_execution_only_approval_cannot_activate(tmp_path: Path):
    store, current_scope, old, ticket = ready(tmp_path)
    record = prepared(old, current_scope, risk="critical")
    authority = ApprovalAuthority("reviewer", b"r" * 32)
    approval = authority.issue(
        domain="execution",
        operation_id=record.operation_id,
        subject="sha256:" + "e" * 64,
        issued_at=datetime(2026, 9, 18, tzinfo=UTC),
        expires_at=datetime(2026, 9, 19, tzinfo=UTC),
        synthetic=True,
    )
    controller = SwapController(
        store,
        current_scope,
        validator=lambda _record: True,
        approval_verifier=authority.verifier(),
    )
    controller.prepare(record)
    with pytest.raises(ValueError, match="approval"):
        controller.activate(record.prepared_id, ticket, approval)


def test_activation_audit_failure_rolls_back_pointer_and_ticket(tmp_path: Path):
    store, current_scope, old, ticket = ready(tmp_path)
    record = prepared(old, current_scope)
    controller = SwapController(store, current_scope, validator=lambda _record: True)
    controller.prepare(record)

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("audit sink unavailable")

    original_audit = store._audit
    store._audit = fail_audit  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="audit sink"):
        controller.activate(record.prepared_id, ticket)
    assert store.get(current_scope).active == old
    assert store.find_activation(current_scope, record.prepared_id) is None
    store._audit = original_audit  # type: ignore[method-assign]
    receipt = controller.activate(record.prepared_id, ticket)
    assert receipt.applied


def test_activation_replay_survives_expiry_and_revocation(tmp_path: Path):
    store, current_scope, old, ticket = ready(tmp_path)
    record = prepared(old, current_scope)
    allowed = True

    def policy(_record):
        return allowed

    controller = SwapController(store, current_scope, validator=policy)
    controller.prepare(record)
    receipt = controller.activate(record.prepared_id, ticket)
    object.__setattr__(store, "_clock", lambda: datetime(2026, 9, 20, tzinfo=UTC))
    allowed = False
    assert controller.activate(record.prepared_id, ticket) == receipt


def test_transaction_time_activation_revocation_blocks_pointer_change(tmp_path: Path):
    store, current_scope, old, ticket = ready(tmp_path)
    record = prepared(old, current_scope)
    calls = 0

    def policy(_record):
        nonlocal calls
        calls += 1
        return calls < 3

    controller = SwapController(store, current_scope, validator=policy)
    controller.prepare(record)
    with pytest.raises(ValueError, match="authorization"):
        controller.activate(record.prepared_id, ticket)
    assert calls == 3
    assert store.get(current_scope).active == old


def test_rollback_rechecks_current_authority_inside_transaction(tmp_path: Path):
    store, current_scope, old, ticket = ready(tmp_path)
    record = prepared(old, current_scope)
    decisions = iter((True, False))

    def rollback_policy(_receipt):
        return next(decisions)

    controller = SwapController(
        store,
        current_scope,
        validator=lambda _record: True,
        rollback_validator=rollback_policy,
    )
    controller.prepare(record)
    activation = controller.activate(record.prepared_id, ticket)
    rollback_ticket = store.reserve_boundary(current_scope, "activate-1", 1)
    with pytest.raises(ValueError, match="authorization"):
        controller.rollback(activation.receipt_id, rollback_ticket)
    assert store.get(current_scope).active == record.new_binding


def test_ticket_and_request_are_bound_to_prepared_operation(tmp_path: Path):
    store, current_scope, old, ticket = ready(tmp_path)
    other = prepared(old, current_scope).model_copy(
        update={
            "prepared_id": "prepared-other",
            "operation_id": "other-operation",
        }
    )
    controller = SwapController(store, current_scope, validator=lambda _record: True)
    controller.prepare(other)
    with pytest.raises(ValueError, match="ticket"):
        controller.activate(other.prepared_id, ticket)

    mismatched = prepared(old, current_scope).model_copy(
        update={"prepared_id": "prepared-mismatch", "request_digest": "sha256:" + "f" * 64}
    )
    controller.prepare(mismatched)
    with pytest.raises(ValueError, match="operation"):
        controller.activate(mismatched.prepared_id, ticket)
