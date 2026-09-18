"""Policy-bound orchestration for atomic M5 runtime replacement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.swap.runtime_models import (
    ActivationReceipt,
    BoundaryTicket,
    PreparedReplacement,
    RollbackReceipt,
    RuntimeScope,
)
from contractcapsule.swap.store import RuntimeStore, RuntimeStoreError
from contractcapsule.validate.approvals import (
    Approval,
    ApprovalVerifier,
    activation_subject,
)
from contractcapsule.validate.run_models import digest_bytes


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SwapController:
    """Scope-bound replacement coordinator.

    The controller owns policy checks; the store owns the durable pointer CAS.
    There is deliberately no public setter for the active binding.
    """

    store: RuntimeStore
    scope: RuntimeScope
    validator: Callable[[PreparedReplacement], bool]
    approval_verifier: ApprovalVerifier | None = None
    rollback_validator: Callable[[ActivationReceipt], bool] | None = None
    clock: Callable[[], datetime] = _utc_now

    def __post_init__(self) -> None:
        if type(self.store) is not RuntimeStore or type(self.scope) is not RuntimeScope:
            raise RuntimeStoreError("swap composition rejected")
        if not callable(self.validator) or not callable(self.clock):
            raise RuntimeStoreError("swap composition rejected")

    def _check_record(self, record: PreparedReplacement) -> None:
        if type(record) is not PreparedReplacement:
            raise RuntimeStoreError("prepared record rejected")
        if record.scope_digest != self.scope.digest:
            raise RuntimeStoreError("prepared scope rejected")
        try:
            accepted = self.validator(record)
        except Exception:  # noqa: BLE001 - policy failure is a denial.
            accepted = False
        if accepted is not True:
            raise RuntimeStoreError("replacement validation rejected")

    def prepare(self, record: PreparedReplacement) -> PreparedReplacement:
        self._check_record(record)
        self.store.save_prepared(record)
        return record

    def _approval_digest(
        self, record: PreparedReplacement, approval: object | None
    ) -> str:
        needs_approval = record.approval_required or record.effective_risk in {
            "high",
            "critical",
        }
        if approval is None:
            if needs_approval:
                raise RuntimeStoreError("distinct activation approval required")
            return digest_bytes(
                canonical_json_bytes(
                    {
                        "domain": "ccs-m5-no-approval/1",
                        "prepared_digest": record.digest,
                    }
                )
            )
        if self.approval_verifier is None:
            raise RuntimeStoreError("activation approval authority unavailable")
        if type(approval) is not Approval:
            raise RuntimeStoreError("activation approval rejected")
        if approval.issuer == self.scope.principal:
            raise RuntimeStoreError("activation approval must be distinct")
        subject = activation_subject(
            operation_id=record.operation_id,
            prepared_digest=record.digest,
            scope_digest=record.scope_digest,
            request_digest=record.request_digest,
            expected_generation=record.old_binding.generation,
        )
        try:
            checked = self.approval_verifier.verify(
                approval,
                domain="activation",
                operation_id=record.operation_id,
                subject=subject,
                now=self.clock(),
            )
        except Exception as error:
            raise RuntimeStoreError("activation approval rejected") from error
        return digest_bytes(canonical_json_bytes(checked.model_dump(mode="json")))

    def activate(
        self,
        prepared_id: str,
        ticket: BoundaryTicket,
        approval: object | None = None,
    ) -> ActivationReceipt:
        replay = self.store.find_activation(self.scope, prepared_id)
        if replay is not None:
            return replay
        # A durable activation receipt must remain replayable after the
        # preparation TTL; the store still rejects a new activation after
        # expiry once it finds no prior receipt.
        record = self.store.get_prepared(
            self.scope, prepared_id, allow_expired=True
        )
        self._check_record(record)
        approval_digest = self._approval_digest(record, approval)
        def transaction_gate(
            current_record: PreparedReplacement, current_digest: str
        ) -> bool:
            if current_record.digest != record.digest or current_digest != approval_digest:
                return False
            try:
                self._check_record(current_record)
                return self._approval_digest(current_record, approval) == current_digest
            except Exception:  # noqa: BLE001 - authorization failure is a denial.
                return False

        return self.store.activate_prepared(
            self.scope,
            prepared_id,
            ticket,
            approval_digest,
            activation_validator=transaction_gate,
        )

    def rollback(
        self, receipt_id: str, ticket: BoundaryTicket
    ) -> RollbackReceipt:
        replay = self.store.find_rollback(self.scope, receipt_id)
        if replay is not None:
            return replay
        if self.rollback_validator is None:
            raise RuntimeStoreError("rollback authority unavailable")
        rollback_validator = self.rollback_validator
        source = self.store.get_receipt(self.scope, receipt_id)
        if not isinstance(source, ActivationReceipt):
            raise RuntimeStoreError("rollback receipt rejected")
        try:
            if rollback_validator(source) is not True:
                raise RuntimeStoreError("rollback authorization rejected")
        except RuntimeStoreError:
            raise
        except Exception as error:
            raise RuntimeStoreError("rollback authorization rejected") from error

        def transaction_gate(current_source: ActivationReceipt) -> bool:
            if current_source.digest != source.digest:
                return False
            try:
                return rollback_validator(current_source) is True
            except Exception:  # noqa: BLE001 - authorization failure is a denial.
                return False

        return self.store.rollback_receipt(
            self.scope,
            receipt_id,
            ticket,
            rollback_validator=transaction_gate,
        )


__all__ = ["SwapController"]
