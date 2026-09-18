import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from contractcapsule.models.view import CapsuleRef
from contractcapsule.swap.runtime_models import (
    ActionLease,
    ActiveBinding,
    PreparedReplacement,
    RuntimeScope,
)
from contractcapsule.swap.store import (
    ActionInProgress,
    GenerationMismatch,
    ReplayConflict,
    RuntimeStore,
    ScopeNotInitialized,
    UncertainState,
)


def scope(session: str = "session-1") -> RuntimeScope:
    return RuntimeScope(
        tenant="tenant-a",
        principal="principal-a",
        repository="example/api",
        environment="test",
        session=session,
    )


def binding(version: str = "1.0.0", generation: int = 0) -> ActiveBinding:
    return ActiveBinding(
        capsule=CapsuleRef(
            capsule_id="com.example.policy",
            version=version,
            digest="sha256:" + ("0" if version == "1.0.0" else "1") * 64,
        ),
        view_digest="sha256:" + "1" * 64,
        input_digest="sha256:" + "2" * 64,
        generation=generation,
    )


def make_store(path: Path, *, clock=None) -> RuntimeStore:
    binding_validator = lambda _scope, _binding: True
    termination_validator = lambda _scope, _operation, evidence: evidence == b"container-stopped"
    if clock is None:
        return RuntimeStore(
            path,
            b"k" * 32,
            binding_validator=binding_validator,
            termination_validator=termination_validator,
        )
    return RuntimeStore(
        path,
        b"k" * 32,
        clock=clock,
        binding_validator=binding_validator,
        termination_validator=termination_validator,
    )


def test_bootstrap_requires_signed_validation_and_only_empty_session(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    current = scope()
    with pytest.raises(ScopeNotInitialized):
        store.get(current)
    proof = store.issue_bootstrap(current, binding())
    initial = store.initialize(current, binding(), proof)
    assert initial.generation == 0
    with pytest.raises(ValueError, match="already initialized"):
        store.initialize(current, binding(), proof)


def test_forged_bootstrap_proof_cannot_initialize_scope(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    proof = store.issue_bootstrap(scope(), binding())
    forged = proof.model_copy(update={"binding_digest": "sha256:" + "f" * 64})
    with pytest.raises(ValueError, match="bootstrap"):
        store.initialize(scope(), binding(), forged)


def test_scope_isolation_and_generation_compare(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    first, other = scope(), scope("session-2")
    store.initialize(first, binding(), store.issue_bootstrap(first, binding()))
    with pytest.raises(ScopeNotInitialized):
        store.get(other)
    lease = store.begin_action(first, "operation-1", "sha256:" + "a" * 64)
    with pytest.raises(ActionInProgress):
        store.begin_action(first, "operation-2", "sha256:" + "b" * 64)
    store.end_action(first, lease)
    with pytest.raises(GenerationMismatch):
        store.reserve_boundary(first, "operation-1", expected_generation=1)


def test_tampered_runtime_generation_is_rejected(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    current = scope()
    store.initialize(current, binding(), store.issue_bootstrap(current, binding()))
    with sqlite3.connect(store.database_path) as db:
        db.execute("UPDATE m5_runtime_scopes SET generation=99 WHERE scope_digest=?", (current.digest,))
    with pytest.raises(ValueError, match="runtime state"):
        store.get(current)


def test_tampered_active_binding_is_rejected(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    current = scope()
    old = binding()
    store.initialize(current, old, store.issue_bootstrap(current, old))
    forged = binding("2.0.0", 0)
    with sqlite3.connect(store.database_path) as db:
        db.execute(
            "UPDATE m5_runtime_scopes SET active_jcs=? WHERE scope_digest=?",
            (forged.model_dump_json(), current.digest),
        )
    with pytest.raises(ValueError, match="runtime state"):
        store.get(current)


def test_operation_id_is_idempotent_only_for_identical_request(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    current = scope()
    store.initialize(current, binding(), store.issue_bootstrap(current, binding()))
    lease = store.begin_action(current, "operation-1", "sha256:" + "a" * 64)
    store.end_action(current, lease, outcome=b"durable-result")
    replay = store.begin_action(current, "operation-1", "sha256:" + "a" * 64)
    assert replay.replayed
    assert replay.outcome == b"durable-result"
    assert replay.outcome_digest is not None
    with pytest.raises(ReplayConflict):
        store.begin_action(current, "operation-1", "sha256:" + "b" * 64)


def test_forged_action_lease_cannot_close_running_action(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    current = scope()
    store.initialize(current, binding(), store.issue_bootstrap(current, binding()))
    lease = store.begin_action(current, "operation-1", "sha256:" + "a" * 64)
    forged = ActionLease(
        scope_digest=lease.scope_digest,
        operation_id=lease.operation_id,
        request_digest="sha256:" + "f" * 64,
        action_epoch=lease.action_epoch,
        state="RUNNING",
    )
    with pytest.raises(ValueError, match="lease"):
        store.end_action(current, forged)
    assert store.get(current).action_state == "RUNNING"
    store.end_action(current, lease)


def test_tampered_action_outcome_is_rejected(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    current = scope()
    store.initialize(current, binding(), store.issue_bootstrap(current, binding()))
    lease = store.begin_action(current, "operation-1", "sha256:" + "a" * 64)
    store.end_action(current, lease, outcome=b"original")
    with sqlite3.connect(store.database_path) as db:
        db.execute(
            "UPDATE m5_runtime_actions SET outcome=? WHERE scope_digest=? AND operation_id=?",
            (b"forged", current.digest, "operation-1"),
        )
    with pytest.raises(ValueError, match="runtime action"):
        store.begin_action(current, "operation-1", "sha256:" + "a" * 64)


def test_uncertain_action_requires_explicit_reconciliation(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    current = scope()
    store.initialize(current, binding(), store.issue_bootstrap(current, binding()))
    lease = store.begin_action(current, "operation-1", "sha256:" + "a" * 64)
    store.end_action(current, lease, uncertain=True)
    with pytest.raises(UncertainState):
        store.reserve_boundary(current, "operation-1", expected_generation=0)
    proof = store.issue_reconciliation(current, "operation-1", b"container-stopped")
    store.reconcile(current, proof)
    assert store.get(current).action_state == "IDLE"
    replay = store.begin_action(current, "operation-1", "sha256:" + "a" * 64)
    assert replay.replayed


def test_forged_reconciliation_evidence_cannot_clear_uncertain_state(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    current = scope()
    store.initialize(current, binding(), store.issue_bootstrap(current, binding()))
    lease = store.begin_action(current, "operation-1", "sha256:" + "a" * 64)
    store.end_action(current, lease, uncertain=True)
    proof = store.issue_reconciliation(current, "operation-1", b"container-stopped")
    forged = proof.model_copy(update={"evidence_digest": "sha256:" + "f" * 64})
    with pytest.raises(ValueError, match="reconciliation"):
        store.reconcile(current, forged)
    assert store.get(current).action_state == "UNCERTAIN"


def test_two_store_connections_serialize_competing_actions(tmp_path: Path):
    path = tmp_path / "registry.db"
    first = make_store(path)
    second = make_store(path)
    current = scope()
    first.initialize(current, binding(), first.issue_bootstrap(current, binding()))
    lease = first.begin_action(current, "operation-1", "sha256:" + "a" * 64)
    with pytest.raises(ActionInProgress):
        second.begin_action(current, "operation-2", "sha256:" + "b" * 64)
    first.end_action(current, lease)


def test_expired_or_reused_boundary_ticket_is_rejected(tmp_path: Path):
    now = datetime(2026, 9, 18, tzinfo=UTC)
    clock = lambda: now
    store = make_store(tmp_path / "registry.db", clock=clock)
    current = scope()
    store.initialize(current, binding(), store.issue_bootstrap(current, binding()))
    lease = store.begin_action(current, "operation-1", "sha256:" + "a" * 64)
    store.end_action(current, lease)
    ticket = store.reserve_boundary(current, "operation-1", 0, ttl=timedelta(seconds=1))
    store.consume_boundary(current, ticket)
    with pytest.raises(ValueError, match="ticket"):
        store.consume_boundary(current, ticket)
    later = now + timedelta(seconds=2)
    object.__setattr__(store, "_clock", lambda: later)
    lease = store.begin_action(current, "operation-2", "sha256:" + "b" * 64)
    store.end_action(current, lease)
    fresh = store.reserve_boundary(current, "operation-2", 0, ttl=timedelta(seconds=1))
    object.__setattr__(store, "_clock", lambda: later + timedelta(seconds=2))
    with pytest.raises(ValueError, match="expired"):
        store.consume_boundary(current, fresh)


def test_consumed_ticket_row_tampering_is_rejected(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    current = scope()
    store.initialize(current, binding(), store.issue_bootstrap(current, binding()))
    lease = store.begin_action(current, "operation-1", "sha256:" + "a" * 64)
    store.end_action(current, lease)
    ticket = store.reserve_boundary(current, "operation-1", 0)
    store.consume_boundary(current, ticket)
    with sqlite3.connect(store.database_path) as db:
        db.execute(
            "UPDATE m5_runtime_tickets SET consumed=0 WHERE ticket_id=?",
            (ticket.ticket_id,),
        )
    with pytest.raises(ValueError, match="ticket"):
        store.consume_boundary(current, ticket)


def test_runtime_composition_cannot_be_mutated_normally(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    with pytest.raises(AttributeError, match="immutable"):
        store._clock = lambda: datetime.now(UTC)  # type: ignore[misc]


def test_malformed_clock_and_ttl_fail_closed(tmp_path: Path):
    with pytest.raises(ValueError, match="configuration"):
        RuntimeStore(tmp_path / "bad.db", b"k" * 32, clock=None)  # type: ignore[arg-type]
    store = make_store(tmp_path / "registry.db")
    current = scope()
    store.initialize(current, binding(), store.issue_bootstrap(current, binding()))
    lease = store.begin_action(current, "operation-1", "sha256:" + "a" * 64)
    store.end_action(current, lease)
    with pytest.raises(ValueError, match="lifetime"):
        store.reserve_boundary(current, "operation-1", 0, ttl=None)  # type: ignore[arg-type]


def test_prepared_record_is_authenticated_and_reloaded(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    current = scope()
    old = binding()
    store.initialize(current, old, store.issue_bootstrap(current, old))
    record = PreparedReplacement(
        prepared_id="prepared-1",
        scope_digest=current.digest,
        operation_id="operation-1",
        request_digest="sha256:" + "a" * 64,
        old_binding=old,
        new_binding=binding("2.0.0", 1),
        evidence_digest="sha256:" + "b" * 64,
        expires_at="2026-09-19T00:00:00Z",
        payload=b"\xff\x00verified-evidence",
    )
    store.save_prepared(record)
    assert store.get_prepared(current, record.prepared_id) == record
    with pytest.raises(ValueError, match="prepared"):
        with sqlite3.connect(store.database_path) as db:
            db.execute(
                "UPDATE m5_runtime_prepared SET payload=? WHERE prepared_id=?",
                (record.model_copy(update={"operation_id": "forged"}).model_dump_json(), record.prepared_id),
            )
        store.get_prepared(current, record.prepared_id)


def test_duplicate_prepared_record_has_safe_error(tmp_path: Path):
    store = make_store(tmp_path / "registry.db")
    current = scope()
    old = binding()
    store.initialize(current, old, store.issue_bootstrap(current, old))
    record = PreparedReplacement(
        prepared_id="prepared-duplicate",
        scope_digest=current.digest,
        operation_id="operation-1",
        request_digest="sha256:" + "a" * 64,
        old_binding=old,
        new_binding=binding("2.0.0", 1),
        evidence_digest="sha256:" + "b" * 64,
        expires_at="2026-09-19T00:00:00Z",
        payload=b"evidence",
    )
    store.save_prepared(record)
    with pytest.raises(ValueError, match="prepared"):
        store.save_prepared(record)


def test_legacy_runtime_rows_are_authenticated_by_additive_migration(tmp_path: Path):
    path = tmp_path / "registry.db"
    store = make_store(path)
    current = scope()
    store.initialize(current, binding(), store.issue_bootstrap(current, binding()))
    lease = store.begin_action(current, "operation-1", "sha256:" + "a" * 64)
    store.end_action(current, lease, outcome=b"legacy-outcome")
    ticket = store.reserve_boundary(current, "operation-1", 0)
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE m5_runtime_actions DROP COLUMN action_signature")
        db.execute("ALTER TABLE m5_runtime_scopes DROP COLUMN state_signature")
        db.execute("ALTER TABLE m5_runtime_tickets DROP COLUMN record_signature")
    migrated = make_store(path)
    assert migrated.get(current).active == binding()
    replay = migrated.begin_action(current, "operation-1", "sha256:" + "a" * 64)
    assert replay.outcome == b"legacy-outcome"
    migrated.consume_boundary(current, ticket)
