"""Transactional owner for M5 mutable runtime state.

Published Registry rows remain immutable.  This store owns only C-zone state,
and every state transition is authenticated and serialized by SQLite.
"""

from __future__ import annotations

import hmac
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path

from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.swap.runtime_models import (
    ActionLease,
    ActivationReceipt,
    ActiveBinding,
    BootstrapProof,
    BoundaryTicket,
    PreparedReplacement,
    ReconciliationProof,
    RollbackReceipt,
    RuntimeScope,
    RuntimeState,
)
from contractcapsule.validate.run_models import digest_bytes


class RuntimeStoreError(ValueError):
    """Safe, non-disclosing runtime-state failure."""


def _safe_db_call[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Normalize SQLite failures at the public runtime-state boundary."""

    @wraps(func)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except RuntimeStoreError:
            raise
        except sqlite3.Error:
            raise RuntimeStoreError("runtime store unavailable") from None
        except (TypeError, ValueError, KeyError):
            raise RuntimeStoreError("runtime store unavailable") from None

    return wrapped


class ScopeNotInitialized(RuntimeStoreError):
    pass


class ActionInProgress(RuntimeStoreError):
    pass


class UncertainState(RuntimeStoreError):
    pass


class GenerationMismatch(RuntimeStoreError):
    pass


class ReplayConflict(RuntimeStoreError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stamp(value: datetime) -> str:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise RuntimeStoreError("explicit UTC clock required")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


class RuntimeStore:
    """Same-database state owner used by the future swap controller."""

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_composition_sealed", False) and name in {
            "_key",
            "_clock",
            "_binding_validator",
            "_termination_validator",
            "database_path",
        }:
            raise AttributeError("runtime composition is immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        database_path: Path,
        key: bytes,
        *,
        clock: Callable[[], datetime] = _utc_now,
        binding_validator: Callable[[RuntimeScope, ActiveBinding], bool] | None = None,
        termination_validator: Callable[[RuntimeScope, str, bytes], bool] | None = None,
    ) -> None:
        if (
            not isinstance(database_path, Path)
            or type(key) is not bytes
            or len(key) < 32
            or not callable(clock)
            or (binding_validator is not None and not callable(binding_validator))
            or (termination_validator is not None and not callable(termination_validator))
        ):
            raise RuntimeStoreError("invalid runtime store configuration")
        self.database_path = database_path
        self._key = key
        self._clock = clock
        self._binding_validator = binding_validator
        self._termination_validator = termination_validator
        database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._initialize()
        except RuntimeStoreError:
            raise
        except sqlite3.Error:
            raise RuntimeStoreError("runtime store unavailable") from None
        self._composition_sealed = True

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS m5_runtime_scopes (
                    scope_digest TEXT PRIMARY KEY,
                    scope_jcs BLOB NOT NULL,
                    active_jcs BLOB NOT NULL,
                    generation INTEGER NOT NULL CHECK(generation >= 0),
                    action_state TEXT NOT NULL CHECK(action_state IN ('IDLE','RUNNING','UNCERTAIN')),
                    action_epoch INTEGER NOT NULL CHECK(action_epoch >= 0),
                    current_operation_id TEXT,
                    state_signature BLOB NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS m5_runtime_actions (
                    scope_digest TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    action_epoch INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('RUNNING','IDLE','UNCERTAIN')),
                    outcome_digest TEXT,
                    outcome BLOB,
                    action_signature BLOB NOT NULL,
                    PRIMARY KEY(scope_digest, operation_id),
                    FOREIGN KEY(scope_digest) REFERENCES m5_runtime_scopes(scope_digest)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS m5_runtime_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    scope_digest TEXT NOT NULL,
                    expected_generation INTEGER NOT NULL,
                    action_epoch INTEGER NOT NULL,
                    operation_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    signature BLOB NOT NULL,
                    consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed IN (0,1)),
                    record_signature BLOB NOT NULL,
                    FOREIGN KEY(scope_digest) REFERENCES m5_runtime_scopes(scope_digest)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS m5_runtime_prepared (
                    prepared_id TEXT PRIMARY KEY,
                    scope_digest TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    digest TEXT NOT NULL,
                    signature BLOB NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(scope_digest) REFERENCES m5_runtime_scopes(scope_digest)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS m5_runtime_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    scope_digest TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('ACTIVATE','ROLLBACK')),
                    request_digest TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    signature BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(scope_digest) REFERENCES m5_runtime_scopes(scope_digest)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                CREATE TRIGGER IF NOT EXISTS m5_runtime_receipts_no_update
                BEFORE UPDATE ON m5_runtime_receipts
                BEGIN SELECT RAISE(ABORT, 'immutable runtime receipt'); END;
                CREATE TRIGGER IF NOT EXISTS m5_runtime_receipts_no_delete
                BEFORE DELETE ON m5_runtime_receipts
                BEGIN SELECT RAISE(ABORT, 'immutable runtime receipt'); END;
                CREATE TABLE IF NOT EXISTS m5_runtime_audit (
                    event_id TEXT PRIMARY KEY,
                    scope_digest TEXT NOT NULL,
                    event_kind TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    signature BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(scope_digest) REFERENCES m5_runtime_scopes(scope_digest)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                CREATE TRIGGER IF NOT EXISTS m5_runtime_audit_no_update
                BEFORE UPDATE ON m5_runtime_audit
                BEGIN SELECT RAISE(ABORT, 'immutable runtime audit'); END;
                CREATE TRIGGER IF NOT EXISTS m5_runtime_audit_no_delete
                BEFORE DELETE ON m5_runtime_audit
                BEGIN SELECT RAISE(ABORT, 'immutable runtime audit'); END;
                """
            )
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(m5_runtime_actions)")
            }
            if "outcome" not in columns:
                db.execute("ALTER TABLE m5_runtime_actions ADD COLUMN outcome BLOB")
            action_columns = {
                row[1] for row in db.execute("PRAGMA table_info(m5_runtime_actions)")
            }
            if "action_signature" not in action_columns:
                db.execute(
                    "ALTER TABLE m5_runtime_actions ADD COLUMN action_signature BLOB"
                )
                legacy_actions = db.execute(
                    "SELECT scope_digest,operation_id,request_digest,action_epoch,"
                    "state,outcome_digest,outcome FROM m5_runtime_actions"
                ).fetchall()
                for legacy in legacy_actions:
                    action_signature = self._action_signature(
                        scope_digest=legacy[0],
                        operation_id=legacy[1],
                        request_digest=legacy[2],
                        action_epoch=legacy[3],
                        state=legacy[4],
                        outcome_digest=legacy[5],
                        outcome=legacy[6],
                    )
                    db.execute(
                        "UPDATE m5_runtime_actions SET action_signature=? "
                        "WHERE scope_digest=? AND operation_id=?",
                        (action_signature, legacy[0], legacy[1]),
                    )
            missing_action_signature = db.execute(
                "SELECT 1 FROM m5_runtime_actions "
                "WHERE action_signature IS NULL LIMIT 1"
            ).fetchone()
            if missing_action_signature is not None:
                raise RuntimeStoreError("runtime action integrity unavailable")
            scope_columns = {
                row[1] for row in db.execute("PRAGMA table_info(m5_runtime_scopes)")
            }
            if "state_signature" not in scope_columns:
                db.execute(
                    "ALTER TABLE m5_runtime_scopes ADD COLUMN state_signature BLOB"
                )
                legacy_states = db.execute(
                    "SELECT scope_digest,scope_jcs,active_jcs,generation,"
                    "action_state,action_epoch,current_operation_id "
                    "FROM m5_runtime_scopes"
                ).fetchall()
                for legacy in legacy_states:
                    state_signature = self._state_signature(
                        scope_digest=legacy[0],
                        scope_jcs=legacy[1],
                        active_jcs=legacy[2],
                        generation=legacy[3],
                        action_state=legacy[4],
                        action_epoch=legacy[5],
                        current_operation_id=legacy[6],
                    )
                    db.execute(
                        "UPDATE m5_runtime_scopes SET state_signature=? "
                        "WHERE scope_digest=?",
                        (state_signature, legacy[0]),
                    )
            missing_state_signature = db.execute(
                "SELECT 1 FROM m5_runtime_scopes "
                "WHERE state_signature IS NULL LIMIT 1"
            ).fetchone()
            if missing_state_signature is not None:
                raise RuntimeStoreError("runtime state integrity unavailable")
            ticket_columns = {
                row[1] for row in db.execute("PRAGMA table_info(m5_runtime_tickets)")
            }
            if "record_signature" not in ticket_columns:
                db.execute(
                    "ALTER TABLE m5_runtime_tickets ADD COLUMN record_signature BLOB"
                )
                legacy_rows = db.execute(
                    "SELECT ticket_id,scope_digest,expected_generation,action_epoch,"
                    "operation_id,expires_at,signature,consumed "
                    "FROM m5_runtime_tickets"
                ).fetchall()
                for legacy in legacy_rows:
                    if type(legacy[6]) is not bytes:
                        raise RuntimeStoreError("legacy boundary ticket rejected")
                    ticket = BoundaryTicket(
                        ticket_id=legacy[0],
                        scope_digest=legacy[1],
                        expected_generation=legacy[2],
                        action_epoch=legacy[3],
                        operation_id=legacy[4],
                        expires_at=legacy[5],
                        signature="sha256:" + legacy[6].hex(),
                    )
                    if not hmac.compare_digest(
                        ticket.signature, self._ticket_signature(ticket)
                    ):
                        raise RuntimeStoreError("legacy boundary ticket rejected")
                    record_signature = self._ticket_record_signature(
                        ticket, bool(legacy[7])
                    )
                    db.execute(
                        "UPDATE m5_runtime_tickets SET record_signature=? "
                        "WHERE ticket_id=?",
                        (record_signature, legacy[0]),
                    )
            missing_record = db.execute(
                "SELECT 1 FROM m5_runtime_tickets WHERE record_signature IS NULL LIMIT 1"
            ).fetchone()
            if missing_record is not None:
                raise RuntimeStoreError("boundary ticket record integrity unavailable")

    @staticmethod
    def _scope_digest(scope: RuntimeScope) -> str:
        if type(scope) is not RuntimeScope:
            raise RuntimeStoreError("scope rejected")
        return scope.digest

    def _state_signature(
        self,
        *,
        scope_digest: str,
        scope_jcs: bytes,
        active_jcs: bytes,
        generation: int,
        action_state: str,
        action_epoch: int,
        current_operation_id: str | None,
    ) -> bytes:
        return self._sign(
            "ccs-m5-runtime-state/1",
            {
                "scope_digest": scope_digest,
                "scope_jcs": digest_bytes(scope_jcs),
                "active_jcs": digest_bytes(active_jcs),
                "generation": generation,
                "action_state": action_state,
                "action_epoch": action_epoch,
                "current_operation_id": current_operation_id,
            },
        )

    def _action_signature(
        self,
        *,
        scope_digest: str,
        operation_id: str,
        request_digest: str,
        action_epoch: int,
        state: str,
        outcome_digest: str | None,
        outcome: bytes | None,
    ) -> bytes:
        if outcome is not None and type(outcome) is not bytes:
            raise RuntimeStoreError("runtime action integrity unavailable")
        if outcome is not None and outcome_digest != digest_bytes(outcome):
            raise RuntimeStoreError("runtime action integrity unavailable")
        if outcome is None and outcome_digest is not None:
            raise RuntimeStoreError("runtime action integrity unavailable")
        return self._sign(
            "ccs-m5-runtime-action/1",
            {
                "scope_digest": scope_digest,
                "operation_id": operation_id,
                "request_digest": request_digest,
                "action_epoch": action_epoch,
                "state": state,
                "outcome_digest": outcome_digest,
                "outcome": None if outcome is None else digest_bytes(outcome),
            },
        )

    def _verify_action(self, row: sqlite3.Row) -> None:
        if (
            type(row["action_signature"]) is not bytes
            or row["state"] not in {"RUNNING", "IDLE", "UNCERTAIN"}
            or type(row["action_epoch"]) is not int
            or type(row["request_digest"]) is not str
        ):
            raise RuntimeStoreError("runtime action rejected")
        expected = self._action_signature(
            scope_digest=row["scope_digest"],
            operation_id=row["operation_id"],
            request_digest=row["request_digest"],
            action_epoch=row["action_epoch"],
            state=row["state"],
            outcome_digest=row["outcome_digest"],
            outcome=row["outcome"],
        )
        if not hmac.compare_digest(row["action_signature"], expected):
            raise RuntimeStoreError("runtime action rejected")

    @staticmethod
    def _binding_digest(binding: ActiveBinding) -> str:
        if type(binding) is not ActiveBinding:
            raise RuntimeStoreError("binding rejected")
        return binding.digest

    def _validate_binding(self, scope: RuntimeScope, binding: ActiveBinding) -> None:
        if self._binding_validator is None:
            raise RuntimeStoreError("validated binding authority is not configured")
        try:
            accepted = self._binding_validator(scope, binding)
        except Exception:  # noqa: BLE001 - validator failure is a denial.
            accepted = False
        if accepted is not True:
            raise RuntimeStoreError("binding validation rejected")

    def _sign(self, domain: str, payload: object) -> bytes:
        return hmac.digest(
            self._key,
            domain.encode("ascii") + b"\0" + canonical_json_bytes(payload),
            "sha256",
        )

    def _bootstrap_bytes(self, proof: BootstrapProof) -> bytes:
        return self._sign(
            "ccs-m5-runtime-bootstrap/1",
            {
                "scope_digest": proof.scope_digest,
                "binding_digest": proof.binding_digest,
                "issued_at": proof.issued_at,
            },
        )

    def issue_bootstrap(self, scope: RuntimeScope, binding: ActiveBinding) -> BootstrapProof:
        """Trusted composition hook; callers still need the returned proof to initialize."""
        self._validate_binding(scope, binding)
        issued = _stamp(self._clock())
        unsigned = BootstrapProof(
            scope_digest=self._scope_digest(scope),
            binding_digest=self._binding_digest(binding),
            issued_at=issued,
            signature="sha256:" + "0" * 64,
        )
        signature = "sha256:" + self._sign(
            "ccs-m5-runtime-bootstrap/1",
            {
                "scope_digest": unsigned.scope_digest,
                "binding_digest": unsigned.binding_digest,
                "issued_at": unsigned.issued_at,
            },
        ).hex()
        return unsigned.model_copy(update={"signature": signature})

    def _verify_bootstrap(
        self, scope: RuntimeScope, binding: ActiveBinding, proof: BootstrapProof
    ) -> None:
        if type(proof) is not BootstrapProof:
            raise RuntimeStoreError("bootstrap proof rejected")
        if (
            proof.scope_digest != self._scope_digest(scope)
            or proof.binding_digest != self._binding_digest(binding)
            or not hmac.compare_digest(
                proof.signature,
                "sha256:" + self._sign(
                    "ccs-m5-runtime-bootstrap/1",
                    {
                        "scope_digest": proof.scope_digest,
                        "binding_digest": proof.binding_digest,
                        "issued_at": proof.issued_at,
                    },
                ).hex(),
            )
        ):
            raise RuntimeStoreError("bootstrap proof rejected")

    @_safe_db_call
    def initialize(
        self, scope: RuntimeScope, binding: ActiveBinding, proof: BootstrapProof
    ) -> ActiveBinding:
        self._verify_bootstrap(scope, binding, proof)
        self._validate_binding(scope, binding)
        if binding.generation != 0:
            raise RuntimeStoreError("bootstrap requires generation zero")
        scope_digest = self._scope_digest(scope)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Recheck the external binding authority while holding the
            # initialization transaction; the proof is only a preflight.
            self._validate_binding(scope, binding)
            if db.execute(
                "SELECT 1 FROM m5_runtime_scopes WHERE scope_digest=?", (scope_digest,)
            ).fetchone():
                raise RuntimeStoreError("scope already initialized")
            scope_jcs = canonical_json_bytes(scope.model_dump(mode="json"))
            active_jcs = canonical_json_bytes(binding.model_dump(mode="json"))
            db.execute(
                "INSERT INTO m5_runtime_scopes VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    scope_digest,
                    scope_jcs,
                    active_jcs,
                    binding.generation,
                    "IDLE",
                    0,
                    None,
                    self._state_signature(
                        scope_digest=scope_digest,
                        scope_jcs=scope_jcs,
                        active_jcs=active_jcs,
                        generation=binding.generation,
                        action_state="IDLE",
                        action_epoch=0,
                        current_operation_id=None,
                    ),
                    _stamp(self._clock()),
                ),
            )
            self._audit(db, scope_digest, "INITIALIZE", {"binding": binding.digest})
        return binding

    def _row(self, db: sqlite3.Connection, scope: RuntimeScope) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM m5_runtime_scopes WHERE scope_digest=?",
            (self._scope_digest(scope),),
        ).fetchone()
        if row is None:
            raise ScopeNotInitialized("runtime scope is not initialized")
        self._verify_row(row)
        all_actions = db.execute(
            "SELECT * FROM m5_runtime_actions WHERE scope_digest=?",
            (row["scope_digest"],),
        ).fetchall()
        for action_row in all_actions:
            self._verify_action(action_row)
        action_rows = db.execute(
            "SELECT operation_id,action_epoch,state FROM m5_runtime_actions "
            "WHERE scope_digest=? AND state='RUNNING'",
            (row["scope_digest"],),
        ).fetchall()
        if row["action_state"] == "RUNNING":
            current = db.execute(
                "SELECT action_epoch,state FROM m5_runtime_actions "
                "WHERE scope_digest=? AND operation_id=?",
                (row["scope_digest"], row["current_operation_id"]),
            ).fetchone()
            if (
                len(action_rows) != 1
                or current is None
                or current["state"] != "RUNNING"
                or current["action_epoch"] != row["action_epoch"]
            ):
                raise RuntimeStoreError("runtime action state rejected")
        elif action_rows:
            raise RuntimeStoreError("runtime action state rejected")
        latest = db.execute(
            "SELECT state,action_epoch FROM m5_runtime_actions "
            "WHERE scope_digest=? ORDER BY action_epoch DESC LIMIT 1",
            (row["scope_digest"],),
        ).fetchone()
        if (
            latest is not None
            and latest["action_epoch"] == row["action_epoch"]
            and latest["state"] != row["action_state"]
        ):
            raise RuntimeStoreError("runtime action state rejected")
        return row

    def _verify_row(self, row: sqlite3.Row) -> None:
        try:
            stored_scope = RuntimeScope.model_validate_json(row["scope_jcs"])
            stored_binding = ActiveBinding.model_validate_json(row["active_jcs"])
        except (TypeError, ValueError):
            raise RuntimeStoreError("runtime state rejected") from None
        if (
            stored_scope.digest != row["scope_digest"]
            or stored_binding.generation != row["generation"]
            or row["action_state"] not in {"IDLE", "RUNNING", "UNCERTAIN"}
            or type(row["action_epoch"]) is not int
            or (
                row["action_state"] == "RUNNING"
                and (type(row["current_operation_id"]) is not str or not row["current_operation_id"])
            )
            or (
                row["action_state"] != "RUNNING"
                and row["current_operation_id"] is not None
            )
            or type(row["scope_jcs"]) is not bytes
            or type(row["active_jcs"]) is not bytes
            or type(row["state_signature"]) is not bytes
            or not hmac.compare_digest(
                row["state_signature"],
                self._state_signature(
                    scope_digest=row["scope_digest"],
                    scope_jcs=row["scope_jcs"],
                    active_jcs=row["active_jcs"],
                    generation=row["generation"],
                    action_state=row["action_state"],
                    action_epoch=row["action_epoch"],
                    current_operation_id=row["current_operation_id"],
                ),
            )
        ):
            raise RuntimeStoreError("runtime state rejected")

    def _state(self, row: sqlite3.Row) -> RuntimeState:
        self._verify_row(row)
        return RuntimeState.model_validate(
            {
                "scope": RuntimeScope.model_validate_json(row["scope_jcs"]),
                "active": ActiveBinding.model_validate_json(row["active_jcs"]),
                "action_state": row["action_state"],
                "action_epoch": row["action_epoch"],
                "current_operation_id": row["current_operation_id"],
            }
        )

    @_safe_db_call
    def get(self, scope: RuntimeScope) -> RuntimeState:
        with self._connect() as db:
            return self._state(self._row(db, scope))

    @_safe_db_call
    def begin_action(
        self, scope: RuntimeScope, operation_id: str, request_digest: str
    ) -> ActionLease:
        if type(operation_id) is not str or not operation_id or type(request_digest) is not str:
            raise RuntimeStoreError("action request rejected")
        scope_digest = self._scope_digest(scope)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, scope)
            existing = db.execute(
                "SELECT request_digest,action_epoch,state,outcome_digest,outcome FROM m5_runtime_actions WHERE scope_digest=? AND operation_id=?",
                (scope_digest, operation_id),
            ).fetchone()
            if existing is not None:
                if existing["request_digest"] != request_digest:
                    raise ReplayConflict("operation id is bound to another request")
                if existing["state"] == "RUNNING":
                    raise ActionInProgress("action already running")
                if row["action_state"] != "IDLE":
                    raise UncertainState("runtime action is uncertain")
                if (
                    existing["outcome"] is not None
                    and existing["outcome_digest"] != digest_bytes(existing["outcome"])
                ):
                    raise RuntimeStoreError("stored action outcome rejected")
                return ActionLease(
                    scope_digest=scope_digest,
                    operation_id=operation_id,
                    request_digest=request_digest,
                    action_epoch=existing["action_epoch"],
                    state="IDLE",
                    replayed=True,
                    outcome_digest=existing["outcome_digest"],
                    outcome=existing["outcome"],
                )
            if row["action_state"] == "RUNNING":
                raise ActionInProgress("another action is running")
            if row["action_state"] == "UNCERTAIN":
                raise UncertainState("runtime action is uncertain")
            epoch = row["action_epoch"] + 1
            state_signature = self._state_signature(
                scope_digest=scope_digest,
                scope_jcs=row["scope_jcs"],
                active_jcs=row["active_jcs"],
                generation=row["generation"],
                action_state="RUNNING",
                action_epoch=epoch,
                current_operation_id=operation_id,
            )
            db.execute(
                "UPDATE m5_runtime_scopes SET action_state='RUNNING', "
                "action_epoch=?, current_operation_id=?, state_signature=?, "
                "updated_at=? WHERE scope_digest=?",
                (
                    epoch,
                    operation_id,
                    state_signature,
                    _stamp(self._clock()),
                    scope_digest,
                ),
            )
            action_signature = self._action_signature(
                scope_digest=scope_digest,
                operation_id=operation_id,
                request_digest=request_digest,
                action_epoch=epoch,
                state="RUNNING",
                outcome_digest=None,
                outcome=None,
            )
            db.execute(
                "INSERT INTO m5_runtime_actions VALUES (?,?,?,?,?,?,?,?)",
                (
                    scope_digest,
                    operation_id,
                    request_digest,
                    epoch,
                    "RUNNING",
                    None,
                    None,
                    action_signature,
                ),
            )
            self._audit(db, scope_digest, "BEGIN_ACTION", {"operation_id": operation_id, "epoch": epoch})
            return ActionLease(
                scope_digest=scope_digest,
                operation_id=operation_id,
                request_digest=request_digest,
                action_epoch=epoch,
                state="RUNNING",
            )

    @_safe_db_call
    def end_action(
        self,
        scope: RuntimeScope,
        lease: ActionLease,
        *,
        uncertain: bool = False,
        outcome: bytes = b"",
    ) -> None:
        if (
            type(lease) is not ActionLease
            or lease.scope_digest != self._scope_digest(scope)
            or lease.state != "RUNNING"
            or lease.replayed
        ):
            raise RuntimeStoreError("action lease rejected")
        target = "UNCERTAIN" if uncertain else "IDLE"
        if type(outcome) is not bytes:
            raise RuntimeStoreError("action outcome rejected")
        outcome_digest = digest_bytes(outcome)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, scope)
            if (
                row["action_state"] != "RUNNING"
                or row["current_operation_id"] != lease.operation_id
                or row["action_epoch"] != lease.action_epoch
            ):
                raise RuntimeStoreError("action lease is not current")
            action = db.execute(
                "SELECT state,action_epoch,request_digest FROM m5_runtime_actions "
                "WHERE scope_digest=? AND operation_id=?",
                (lease.scope_digest, lease.operation_id),
            ).fetchone()
            if (
                action is None
                or action["state"] != "RUNNING"
                or action["action_epoch"] != lease.action_epoch
                or action["request_digest"] != lease.request_digest
            ):
                raise RuntimeStoreError("action lease is not current")
            db.execute(
                "UPDATE m5_runtime_scopes SET action_state=?, "
                "current_operation_id=NULL, state_signature=?, updated_at=? "
                "WHERE scope_digest=?",
                (
                    target,
                    self._state_signature(
                        scope_digest=lease.scope_digest,
                        scope_jcs=row["scope_jcs"],
                        active_jcs=row["active_jcs"],
                        generation=row["generation"],
                        action_state=target,
                        action_epoch=row["action_epoch"],
                        current_operation_id=None,
                    ),
                    _stamp(self._clock()),
                    lease.scope_digest,
                ),
            )
            db.execute(
                "UPDATE m5_runtime_actions SET state=?, outcome_digest=?, outcome=?, "
                "action_signature=? WHERE scope_digest=? AND operation_id=?",
                (
                    target,
                    outcome_digest,
                    outcome,
                    self._action_signature(
                        scope_digest=lease.scope_digest,
                        operation_id=lease.operation_id,
                        request_digest=lease.request_digest,
                        action_epoch=lease.action_epoch,
                        state=target,
                        outcome_digest=outcome_digest,
                        outcome=outcome,
                    ),
                    lease.scope_digest,
                    lease.operation_id,
                ),
            )
            self._audit(db, lease.scope_digest, "END_ACTION", {"operation_id": lease.operation_id, "state": target})

    @_safe_db_call
    def issue_reconciliation(
        self, scope: RuntimeScope, operation_id: str, termination_evidence: bytes
    ) -> ReconciliationProof:
        if type(operation_id) is not str or not operation_id or type(termination_evidence) is not bytes:
            raise RuntimeStoreError("reconciliation evidence rejected")
        if self._termination_validator is None:
            raise RuntimeStoreError("termination authority is not configured")
        try:
            accepted = self._termination_validator(scope, operation_id, termination_evidence)
        except Exception:  # noqa: BLE001 - termination validation failure is a denial.
            accepted = False
        if accepted is not True:
            raise RuntimeStoreError("termination evidence rejected")
        scope_digest = self._scope_digest(scope)
        with self._connect() as db:
            row = self._row(db, scope)
            action = db.execute(
                "SELECT action_epoch,state FROM m5_runtime_actions WHERE scope_digest=? AND operation_id=?",
                (scope_digest, operation_id),
            ).fetchone()
            if row["action_state"] != "UNCERTAIN" or action is None or action["state"] != "UNCERTAIN":
                raise RuntimeStoreError("reconciliation is not required")
            issued = _stamp(self._clock())
            unsigned = ReconciliationProof(
                scope_digest=scope_digest,
                operation_id=operation_id,
                action_epoch=action["action_epoch"],
                termination_digest=digest_bytes(termination_evidence),
                evidence_digest=digest_bytes(termination_evidence),
                issued_at=issued,
                signature="sha256:" + "0" * 64,
            )
            payload = {
                "scope_digest": unsigned.scope_digest,
                "operation_id": unsigned.operation_id,
                "action_epoch": unsigned.action_epoch,
                "termination_digest": unsigned.termination_digest,
                "evidence_digest": unsigned.evidence_digest,
                "issued_at": unsigned.issued_at,
            }
            signature = "sha256:" + self._sign(
                "ccs-m5-runtime-reconcile/1", payload
            ).hex()
            return unsigned.model_copy(update={"signature": signature})

    @_safe_db_call
    def reconcile(self, scope: RuntimeScope, proof: ReconciliationProof) -> None:
        if type(proof) is not ReconciliationProof or proof.scope_digest != self._scope_digest(scope):
            raise RuntimeStoreError("reconciliation evidence rejected")
        payload = {
            "scope_digest": proof.scope_digest,
            "operation_id": proof.operation_id,
            "action_epoch": proof.action_epoch,
            "termination_digest": proof.termination_digest,
            "evidence_digest": proof.evidence_digest,
            "issued_at": proof.issued_at,
        }
        if not hmac.compare_digest(
            proof.signature,
            "sha256:" + self._sign("ccs-m5-runtime-reconcile/1", payload).hex(),
        ):
            raise RuntimeStoreError("reconciliation evidence rejected")
        scope_digest = self._scope_digest(scope)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, scope)
            action = db.execute(
                "SELECT state,action_epoch,request_digest,outcome_digest,outcome "
                "FROM m5_runtime_actions WHERE scope_digest=? AND operation_id=?",
                (scope_digest, proof.operation_id),
            ).fetchone()
            if (
                row["action_state"] != "UNCERTAIN"
                or action is None
                or action["state"] != "UNCERTAIN"
                or action["action_epoch"] != proof.action_epoch
            ):
                raise RuntimeStoreError("reconciliation is not required")
            db.execute(
                "UPDATE m5_runtime_scopes SET action_state='IDLE', "
                "current_operation_id=NULL, state_signature=?, updated_at=? "
                "WHERE scope_digest=?",
                (
                    self._state_signature(
                        scope_digest=scope_digest,
                        scope_jcs=row["scope_jcs"],
                        active_jcs=row["active_jcs"],
                        generation=row["generation"],
                        action_state="IDLE",
                        action_epoch=row["action_epoch"],
                        current_operation_id=None,
                    ),
                    _stamp(self._clock()),
                    scope_digest,
                ),
            )
            action_signature = self._action_signature(
                scope_digest=scope_digest,
                operation_id=proof.operation_id,
                request_digest=action["request_digest"],
                action_epoch=action["action_epoch"],
                state="IDLE",
                outcome_digest=action["outcome_digest"],
                outcome=action["outcome"],
            )
            db.execute(
                "UPDATE m5_runtime_actions SET state='IDLE', action_signature=? "
                "WHERE scope_digest=? AND operation_id=?",
                (action_signature, scope_digest, proof.operation_id),
            )
            self._audit(db, scope_digest, "RECONCILE", {"operation_id": proof.operation_id, "evidence": proof.evidence_digest})

    def _ticket_signature(self, ticket: BoundaryTicket) -> str:
        value = {
            "ticket_id": ticket.ticket_id,
            "scope_digest": ticket.scope_digest,
            "expected_generation": ticket.expected_generation,
            "action_epoch": ticket.action_epoch,
            "operation_id": ticket.operation_id,
            "expires_at": ticket.expires_at,
        }
        return "sha256:" + self._sign("ccs-m5-runtime-boundary/1", value).hex()

    def _ticket_record_signature(self, ticket: BoundaryTicket, consumed: bool) -> bytes:
        value = {
            "ticket_id": ticket.ticket_id,
            "scope_digest": ticket.scope_digest,
            "expected_generation": ticket.expected_generation,
            "action_epoch": ticket.action_epoch,
            "operation_id": ticket.operation_id,
            "expires_at": ticket.expires_at,
            "consumed": consumed,
        }
        return self._sign("ccs-m5-runtime-ticket-row/1", value)

    @_safe_db_call
    def reserve_boundary(
        self,
        scope: RuntimeScope,
        operation_id: str,
        expected_generation: int,
        *,
        ttl: timedelta = timedelta(seconds=30),
    ) -> BoundaryTicket:
        if type(operation_id) is not str or not operation_id or type(expected_generation) is not int:
            raise RuntimeStoreError("boundary request rejected")
        if (
            type(ttl) is not timedelta
            or ttl <= timedelta(0)
            or ttl > timedelta(minutes=10)
        ):
            raise RuntimeStoreError("boundary lifetime rejected")
        scope_digest = self._scope_digest(scope)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, scope)
            if row["action_state"] == "UNCERTAIN":
                raise UncertainState("uncertain action blocks boundary")
            if row["action_state"] != "IDLE":
                raise ActionInProgress("running action blocks boundary")
            if row["generation"] != expected_generation:
                raise GenerationMismatch("generation changed")
            action = db.execute(
                "SELECT action_epoch,state FROM m5_runtime_actions WHERE scope_digest=? AND operation_id=?",
                (scope_digest, operation_id),
            ).fetchone()
            if action is None or action["state"] != "IDLE" or action["action_epoch"] != row["action_epoch"]:
                raise RuntimeStoreError("boundary operation is not complete")
            expires = _stamp(self._clock() + ttl)
            unsigned = BoundaryTicket(
                ticket_id=str(uuid.uuid4()),
                scope_digest=scope_digest,
                expected_generation=expected_generation,
                action_epoch=row["action_epoch"],
                operation_id=operation_id,
                expires_at=expires,
                signature="sha256:" + "0" * 64,
            )
            ticket = unsigned.model_copy(update={"signature": self._ticket_signature(unsigned)})
            db.execute(
                "INSERT INTO m5_runtime_tickets VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    ticket.ticket_id,
                    ticket.scope_digest,
                    ticket.expected_generation,
                    ticket.action_epoch,
                    ticket.operation_id,
                    ticket.expires_at,
                    bytes.fromhex(ticket.signature.removeprefix("sha256:")),
                    0,
                    self._ticket_record_signature(ticket, False),
                ),
            )
            self._audit(db, scope_digest, "RESERVE_BOUNDARY", {"ticket_id": ticket.ticket_id})
            return ticket

    @_safe_db_call
    def consume_boundary(self, scope: RuntimeScope, ticket: BoundaryTicket) -> BoundaryTicket:
        if type(ticket) is not BoundaryTicket or ticket.scope_digest != self._scope_digest(scope):
            raise RuntimeStoreError("boundary ticket rejected")
        if not hmac.compare_digest(ticket.signature, self._ticket_signature(ticket)):
            raise RuntimeStoreError("boundary ticket rejected")
        scope_digest = self._scope_digest(scope)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, scope)
            self._check_ticket_db(db, scope, ticket, row)
            updated = db.execute(
                "UPDATE m5_runtime_tickets SET consumed=1,record_signature=? "
                "WHERE ticket_id=? AND consumed=0 AND record_signature=?",
                (
                    self._ticket_record_signature(ticket, True),
                    ticket.ticket_id,
                    self._ticket_record_signature(ticket, False),
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeStoreError("boundary ticket consumption failed")
            self._audit(db, scope_digest, "CONSUME_BOUNDARY", {"ticket_id": ticket.ticket_id})
            return ticket

    def _load_prepared_db(
        self,
        db: sqlite3.Connection,
        scope: RuntimeScope,
        prepared_id: str,
        *,
        allow_expired: bool = False,
    ) -> PreparedReplacement:
        scope_digest = self._scope_digest(scope)
        row = db.execute(
            "SELECT prepared_id,scope_digest,payload,digest,signature FROM m5_runtime_prepared WHERE scope_digest=? AND prepared_id=?",
            (scope_digest, prepared_id),
        ).fetchone()
        if row is None:
            raise RuntimeStoreError("prepared record unavailable")
        try:
            record = PreparedReplacement.model_validate_json(row[2])
        except (TypeError, ValueError):
            raise RuntimeStoreError("prepared record rejected") from None
        expected = self._sign(
            "ccs-m5-runtime-prepared/1",
            {
                "prepared_id": row[0],
                "scope_digest": row[1],
                "operation_id": record.operation_id,
                "expires_at": record.expires_at,
                "digest": row[3],
            },
        )
        if type(row[4]) is not bytes or not hmac.compare_digest(expected, row[4]):
            raise RuntimeStoreError("prepared record rejected")
        if (
            record.prepared_id != row[0]
            or record.scope_digest != row[1]
            or record.scope_digest != scope_digest
            or digest_bytes(canonical_json_bytes(record.model_dump(mode="json"))) != row[3]
        ):
            raise RuntimeStoreError("prepared record rejected")
        if not allow_expired and _stamp(self._clock()) >= record.expires_at:
            raise RuntimeStoreError("prepared record expired")
        return record

    def _check_ticket_db(
        self,
        db: sqlite3.Connection,
        scope: RuntimeScope,
        ticket: BoundaryTicket,
        row: sqlite3.Row,
        *,
        expected_operation_id: str | None = None,
        expected_request_digest: str | None = None,
    ) -> None:
        scope_digest = self._scope_digest(scope)
        if (
            type(ticket) is not BoundaryTicket
            or ticket.scope_digest != scope_digest
            or (
                expected_operation_id is not None
                and ticket.operation_id != expected_operation_id
            )
        ):
            raise RuntimeStoreError("boundary ticket rejected")
        if not hmac.compare_digest(ticket.signature, self._ticket_signature(ticket)):
            raise RuntimeStoreError("boundary ticket rejected")
        stored = db.execute(
            "SELECT * FROM m5_runtime_tickets WHERE ticket_id=?", (ticket.ticket_id,)
        ).fetchone()
        if stored is None or stored["consumed"]:
            raise RuntimeStoreError("boundary ticket already consumed")
        public_signature = bytes.fromhex(ticket.signature.removeprefix("sha256:"))
        if (
            stored["scope_digest"] != ticket.scope_digest
            or stored["expected_generation"] != ticket.expected_generation
            or stored["action_epoch"] != ticket.action_epoch
            or stored["operation_id"] != ticket.operation_id
            or stored["expires_at"] != ticket.expires_at
            or stored["signature"] != public_signature
            or type(stored["record_signature"]) is not bytes
            or not hmac.compare_digest(
                stored["record_signature"], self._ticket_record_signature(ticket, False)
            )
        ):
            raise RuntimeStoreError("boundary ticket rejected")
        if _stamp(self._clock()) >= ticket.expires_at:
            raise RuntimeStoreError("boundary ticket expired")
        if (
            row["action_state"] != "IDLE"
            or row["generation"] != ticket.expected_generation
            or row["action_epoch"] != ticket.action_epoch
        ):
            raise RuntimeStoreError("boundary ticket is stale")
        action = db.execute(
            "SELECT state,action_epoch,request_digest FROM m5_runtime_actions "
            "WHERE scope_digest=? AND operation_id=?",
            (scope_digest, ticket.operation_id),
        ).fetchone()
        if (
            action is None
            or action["state"] != "IDLE"
            or action["action_epoch"] != ticket.action_epoch
            or (
                expected_request_digest is not None
                and action["request_digest"] != expected_request_digest
            )
        ):
            raise RuntimeStoreError("boundary operation is not complete")

    def _receipt_signature(self, kind: str, receipt: object) -> str:
        return "sha256:" + self._sign(
            "ccs-m5-runtime-receipt/1",
            {"kind": kind, "receipt": receipt},
        ).hex()

    def _load_receipt_db(
        self, db: sqlite3.Connection, scope: RuntimeScope, receipt_id: str
    ) -> tuple[str, ActivationReceipt | RollbackReceipt]:
        row = db.execute(
            "SELECT receipt_id,scope_digest,operation_id,request_digest,kind,payload,signature "
            "FROM m5_runtime_receipts WHERE scope_digest=? AND receipt_id=?",
            (self._scope_digest(scope), receipt_id),
        ).fetchone()
        if row is None:
            raise RuntimeStoreError("receipt unavailable")
        if row[4] not in {"ACTIVATE", "ROLLBACK"}:
            raise RuntimeStoreError("receipt rejected")
        try:
            model = (
                ActivationReceipt.model_validate_json(row[5])
                if row[4] == "ACTIVATE"
                else RollbackReceipt.model_validate_json(row[5])
            )
        except (TypeError, ValueError):
            raise RuntimeStoreError("receipt rejected") from None
        unsigned = model.model_dump(mode="json", exclude={"signature"})
        if type(row[6]) is not bytes or not hmac.compare_digest(
            self._sign(
                "ccs-m5-runtime-receipt/1",
                {"kind": row[4], "receipt": unsigned},
            ),
            row[6],
        ):
            raise RuntimeStoreError("receipt rejected")
        if (
            model.scope_digest != self._scope_digest(scope)
            or model.receipt_id != receipt_id
            or model.operation_id != row[2]
            or model.request_digest != row[3]
        ):
            raise RuntimeStoreError("receipt rejected")
        expected = self._receipt_signature(row[4], unsigned)
        if model.signature != expected:
            raise RuntimeStoreError("receipt rejected")
        return row[4], model

    @_safe_db_call
    def activate_prepared(
        self,
        scope: RuntimeScope,
        prepared_id: str,
        ticket: BoundaryTicket,
        approval_digest: str,
        *,
        activation_validator: Callable[[PreparedReplacement, str], bool] | None = None,
    ) -> ActivationReceipt:
        if type(approval_digest) is not str or not approval_digest.startswith("sha256:"):
            raise RuntimeStoreError("activation approval rejected")
        scope_digest = self._scope_digest(scope)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, scope)
            record = self._load_prepared_db(
                db, scope, prepared_id, allow_expired=True
            )
            existing = db.execute(
                "SELECT receipt_id FROM m5_runtime_receipts WHERE scope_digest=? AND operation_id=? AND kind='ACTIVATE'",
                (scope_digest, record.operation_id),
            ).fetchone()
            if existing is not None:
                _kind, receipt = self._load_receipt_db(db, scope, existing[0])
                if not isinstance(receipt, ActivationReceipt) or receipt.request_digest != record.request_digest:
                    raise ReplayConflict("activation operation is bound to another request")
                if receipt.prepared_id != record.prepared_id:
                    raise ReplayConflict("activation operation is bound to another preparation")
                return receipt
            if _stamp(self._clock()) >= record.expires_at:
                raise RuntimeStoreError("prepared record expired")
            if record.old_binding.digest != ActiveBinding.model_validate_json(row["active_jcs"]).digest:
                raise RuntimeStoreError("prepared old binding mismatch")
            self._check_ticket_db(
                db,
                scope,
                ticket,
                row,
                expected_operation_id=record.operation_id,
                expected_request_digest=record.request_digest,
            )
            old = ActiveBinding.model_validate_json(row["active_jcs"])
            if record.new_binding.generation != row["generation"] + 1:
                raise GenerationMismatch("prepared generation mismatch")
            if activation_validator is None:
                raise RuntimeStoreError("activation authority unavailable")
            try:
                authorized = activation_validator(record, approval_digest)
            except Exception:  # noqa: BLE001 - authorization failure is a denial.
                authorized = False
            if authorized is not True:
                raise RuntimeStoreError("activation authorization rejected")
            unsigned = ActivationReceipt(
                receipt_id=str(uuid.uuid4()),
                scope_digest=scope_digest,
                operation_id=record.operation_id,
                prepared_id=record.prepared_id,
                ticket_id=ticket.ticket_id,
                request_digest=record.request_digest,
                old_binding=old,
                new_binding=record.new_binding,
                generation_before=row["generation"],
                generation_after=record.new_binding.generation,
                approval_digest=approval_digest,
                signature="sha256:" + "0" * 64,
            )
            receipt = unsigned.model_copy(
                update={
                    "signature": self._receipt_signature(
                        "ACTIVATE", unsigned.model_dump(mode="json", exclude={"signature"})
                    )
                }
            )
            payload = canonical_json_bytes(receipt.model_dump(mode="json"))
            new_active_jcs = canonical_json_bytes(
                record.new_binding.model_dump(mode="json")
            )
            pointer_update = db.execute(
                "UPDATE m5_runtime_scopes SET active_jcs=?, generation=?, "
                "state_signature=?, updated_at=? WHERE scope_digest=? AND generation=?",
                (
                    new_active_jcs,
                    record.new_binding.generation,
                    self._state_signature(
                        scope_digest=scope_digest,
                        scope_jcs=row["scope_jcs"],
                        active_jcs=new_active_jcs,
                        generation=record.new_binding.generation,
                        action_state="IDLE",
                        action_epoch=row["action_epoch"],
                        current_operation_id=None,
                    ),
                    _stamp(self._clock()),
                    scope_digest,
                    row["generation"],
                ),
            )
            if pointer_update.rowcount != 1:
                raise RuntimeStoreError("activation compare-and-swap failed")
            ticket_update = db.execute(
                "UPDATE m5_runtime_tickets SET consumed=1,record_signature=? "
                "WHERE ticket_id=? AND consumed=0 AND record_signature=?",
                (
                    self._ticket_record_signature(ticket, True),
                    ticket.ticket_id,
                    self._ticket_record_signature(ticket, False),
                ),
            )
            if ticket_update.rowcount != 1:
                raise RuntimeStoreError("boundary ticket consumption failed")
            db.execute(
                "INSERT INTO m5_runtime_receipts VALUES (?,?,?,?,?,?,?,?)",
                (
                    receipt.receipt_id,
                    scope_digest,
                    record.operation_id,
                    "ACTIVATE",
                    record.request_digest,
                    payload,
                    bytes.fromhex(receipt.signature.removeprefix("sha256:")),
                    _stamp(self._clock()),
                ),
            )
            self._audit(db, scope_digest, "ACTIVATE", {"receipt_id": receipt.receipt_id})
            return receipt

    @_safe_db_call
    def get_receipt(
        self, scope: RuntimeScope, receipt_id: str
    ) -> ActivationReceipt | RollbackReceipt:
        with self._connect() as db:
            _kind, receipt = self._load_receipt_db(db, scope, receipt_id)
            return receipt

    @_safe_db_call
    def find_activation(
        self, scope: RuntimeScope, prepared_id: str
    ) -> ActivationReceipt | None:
        """Return an authenticated durable activation for crash-safe replay."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT receipt_id FROM m5_runtime_receipts "
                "WHERE scope_digest=? AND kind='ACTIVATE' ORDER BY created_at",
                (self._scope_digest(scope),),
            ).fetchall()
            for row in rows:
                kind, receipt = self._load_receipt_db(db, scope, row[0])
                if (
                    kind == "ACTIVATE"
                    and isinstance(receipt, ActivationReceipt)
                    and receipt.prepared_id == prepared_id
                ):
                    return receipt
        return None

    @_safe_db_call
    def find_rollback(
        self, scope: RuntimeScope, source_receipt_id: str
    ) -> RollbackReceipt | None:
        """Return an authenticated durable rollback for crash-safe replay."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT receipt_id FROM m5_runtime_receipts "
                "WHERE scope_digest=? AND kind='ROLLBACK' ORDER BY created_at",
                (self._scope_digest(scope),),
            ).fetchall()
            for row in rows:
                kind, receipt = self._load_receipt_db(db, scope, row[0])
                if (
                    kind == "ROLLBACK"
                    and isinstance(receipt, RollbackReceipt)
                    and receipt.source_receipt_id == source_receipt_id
                ):
                    return receipt
        return None

    @_safe_db_call
    def rollback_receipt(
        self,
        scope: RuntimeScope,
        receipt_id: str,
        ticket: BoundaryTicket,
        *,
        rollback_validator: Callable[[ActivationReceipt], bool] | None = None,
    ) -> RollbackReceipt:
        scope_digest = self._scope_digest(scope)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, scope)
            kind, source = self._load_receipt_db(db, scope, receipt_id)
            if kind != "ACTIVATE" or not isinstance(source, ActivationReceipt):
                raise RuntimeStoreError("rollback receipt rejected")
            existing = db.execute(
                "SELECT receipt_id FROM m5_runtime_receipts WHERE scope_digest=? AND operation_id=? AND kind='ROLLBACK'",
                (scope_digest, source.operation_id),
            ).fetchone()
            if existing is not None:
                _kind, rollback = self._load_receipt_db(db, scope, existing[0])
                if not isinstance(rollback, RollbackReceipt):
                    raise RuntimeStoreError("rollback receipt rejected")
                return rollback
            if (
                row["generation"] != source.generation_after
                or ActiveBinding.model_validate_json(row["active_jcs"]).digest != source.new_binding.digest
            ):
                raise GenerationMismatch("rollback generation or binding mismatch")
            self._check_ticket_db(
                db,
                scope,
                ticket,
                row,
                expected_operation_id=source.operation_id,
                expected_request_digest=source.request_digest,
            )
            if rollback_validator is None:
                raise RuntimeStoreError("rollback authority unavailable")
            try:
                authorized = rollback_validator(source)
            except Exception:  # noqa: BLE001 - authorization failure is a denial.
                authorized = False
            if authorized is not True:
                raise RuntimeStoreError("rollback authorization rejected")
            restored = source.old_binding.model_copy(update={"generation": row["generation"] + 1})
            unsigned = RollbackReceipt(
                receipt_id=str(uuid.uuid4()),
                source_receipt_id=source.receipt_id,
                scope_digest=scope_digest,
                operation_id=source.operation_id,
                ticket_id=ticket.ticket_id,
                request_digest=source.request_digest,
                restored_binding=restored,
                generation_before=row["generation"],
                generation_after=restored.generation,
                signature="sha256:" + "0" * 64,
            )
            rollback = unsigned.model_copy(
                update={
                    "signature": self._receipt_signature(
                        "ROLLBACK", unsigned.model_dump(mode="json", exclude={"signature"})
                    )
                }
            )
            restored_jcs = canonical_json_bytes(restored.model_dump(mode="json"))
            pointer_update = db.execute(
                "UPDATE m5_runtime_scopes SET active_jcs=?, generation=?, "
                "state_signature=?, updated_at=? WHERE scope_digest=? AND generation=?",
                (
                    restored_jcs,
                    restored.generation,
                    self._state_signature(
                        scope_digest=scope_digest,
                        scope_jcs=row["scope_jcs"],
                        active_jcs=restored_jcs,
                        generation=restored.generation,
                        action_state="IDLE",
                        action_epoch=row["action_epoch"],
                        current_operation_id=None,
                    ),
                    _stamp(self._clock()),
                    scope_digest,
                    row["generation"],
                ),
            )
            if pointer_update.rowcount != 1:
                raise RuntimeStoreError("rollback compare-and-swap failed")
            ticket_update = db.execute(
                "UPDATE m5_runtime_tickets SET consumed=1,record_signature=? "
                "WHERE ticket_id=? AND consumed=0 AND record_signature=?",
                (
                    self._ticket_record_signature(ticket, True),
                    ticket.ticket_id,
                    self._ticket_record_signature(ticket, False),
                ),
            )
            if ticket_update.rowcount != 1:
                raise RuntimeStoreError("boundary ticket consumption failed")
            db.execute(
                "INSERT INTO m5_runtime_receipts VALUES (?,?,?,?,?,?,?,?)",
                (
                    rollback.receipt_id,
                    scope_digest,
                    source.operation_id,
                    "ROLLBACK",
                    source.request_digest,
                    canonical_json_bytes(rollback.model_dump(mode="json")),
                    bytes.fromhex(rollback.signature.removeprefix("sha256:")),
                    _stamp(self._clock()),
                ),
            )
            self._audit(db, scope_digest, "ROLLBACK", {"receipt_id": rollback.receipt_id})
            return rollback

    @_safe_db_call
    def save_prepared(self, record: PreparedReplacement) -> None:
        if type(record) is not PreparedReplacement:
            raise RuntimeStoreError("prepared record rejected")
        serialized = canonical_json_bytes(record.model_dump(mode="json"))
        digest = digest_bytes(serialized)
        signature = self._sign(
            "ccs-m5-runtime-prepared/1",
            {
                "prepared_id": record.prepared_id,
                "scope_digest": record.scope_digest,
                "operation_id": record.operation_id,
                "expires_at": record.expires_at,
                "digest": digest,
            },
        )
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self._row(
                    db,
                    RuntimeScope.model_validate_json(
                        self._scope_json(db, record.scope_digest)
                    ),
                )
                db.execute(
                    "INSERT INTO m5_runtime_prepared VALUES (?,?,?,?,?,?,?)",
                    (
                        record.prepared_id,
                        record.scope_digest,
                        record.operation_id,
                        serialized,
                        digest,
                        signature,
                        record.expires_at,
                    ),
                )
        except RuntimeStoreError:
            raise
        except sqlite3.Error:
            raise RuntimeStoreError("prepared record unavailable") from None

    @_safe_db_call
    def get_prepared(
        self,
        scope: RuntimeScope,
        prepared_id: str,
        *,
        allow_expired: bool = False,
    ) -> PreparedReplacement:
        try:
            with self._connect() as db:
                return self._load_prepared_db(
                    db,
                    scope,
                    prepared_id,
                    allow_expired=allow_expired,
                )
        except RuntimeStoreError:
            raise
        except sqlite3.Error:
            raise RuntimeStoreError("prepared record unavailable") from None

    def _scope_json(self, db: sqlite3.Connection, scope_digest: str) -> bytes:
        row = db.execute("SELECT scope_jcs FROM m5_runtime_scopes WHERE scope_digest=?", (scope_digest,)).fetchone()
        if row is None:
            raise ScopeNotInitialized("runtime scope is not initialized")
        return row[0]

    def _audit(self, db: sqlite3.Connection, scope_digest: str, kind: str, payload: object) -> None:
        raw = canonical_json_bytes(payload)
        event_id = str(uuid.uuid4())
        signature = self._sign("ccs-m5-runtime-audit/1", {"event_id": event_id, "scope_digest": scope_digest, "kind": kind, "payload": digest_bytes(raw)})
        db.execute(
            "INSERT INTO m5_runtime_audit VALUES (?,?,?,?,?,?)",
            (event_id, scope_digest, kind, raw, signature, _stamp(self._clock())),
        )


__all__ = [
    "ActionInProgress",
    "GenerationMismatch",
    "ReplayConflict",
    "RuntimeStore",
    "RuntimeStoreError",
    "ScopeNotInitialized",
    "UncertainState",
]
