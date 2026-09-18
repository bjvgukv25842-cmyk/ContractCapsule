"""Explicit safe-boundary facade for the M5 runtime state owner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from contractcapsule.swap.runtime_models import (
    ActionLease,
    BoundaryTicket,
    ReconciliationProof,
    RuntimeScope,
)
from contractcapsule.swap.store import RuntimeStore


@dataclass(frozen=True)
class SafeBoundary:
    """A scope-bound facade; it has no unconditional active-pointer setter."""

    store: RuntimeStore
    scope: RuntimeScope

    def begin(self, operation_id: str, request_digest: str) -> ActionLease:
        return self.store.begin_action(self.scope, operation_id, request_digest)

    def end(
        self,
        lease: ActionLease,
        *,
        uncertain: bool = False,
        outcome: bytes = b"",
    ) -> None:
        self.store.end_action(
            self.scope, lease, uncertain=uncertain, outcome=outcome
        )

    def issue_reconciliation(
        self, operation_id: str, termination_evidence: bytes
    ) -> ReconciliationProof:
        return self.store.issue_reconciliation(
            self.scope, operation_id, termination_evidence
        )

    def reconcile(self, proof: ReconciliationProof) -> None:
        self.store.reconcile(self.scope, proof)

    def reserve(
        self,
        operation_id: str,
        *,
        expected_generation: int,
        ttl: timedelta = timedelta(seconds=30),
    ) -> BoundaryTicket:
        return self.store.reserve_boundary(
            self.scope, operation_id, expected_generation, ttl=ttl
        )

    def consume(self, ticket: BoundaryTicket) -> BoundaryTicket:
        return self.store.consume_boundary(self.scope, ticket)


__all__ = ["SafeBoundary"]
