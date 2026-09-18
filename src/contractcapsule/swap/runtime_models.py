"""Immutable transport models for the mutable M5 C-zone state owner."""

from __future__ import annotations

import base64
import hashlib
from typing import Annotated, Literal

from pydantic import Field, field_serializer, field_validator, model_validator

from contractcapsule.models.base import (
    Digest,
    NonEmptyString,
    StrictFrozenModel,
    TimestampString,
)
from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.models.view import CapsuleRef

Natural = Annotated[int, Field(ge=0)]
ActionState = Literal["IDLE", "RUNNING", "UNCERTAIN"]


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class RuntimeScope(StrictFrozenModel):
    """The complete isolation key for runtime state."""

    tenant: NonEmptyString
    principal: NonEmptyString
    repository: NonEmptyString
    environment: NonEmptyString
    session: NonEmptyString

    @property
    def digest(self) -> Digest:
        return _digest(self.model_dump(mode="json"))


class ActiveBinding(StrictFrozenModel):
    """A durable binding snapshot; it is not itself activation authority."""

    capsule: CapsuleRef
    view_digest: Digest
    input_digest: Digest
    generation: Natural

    @property
    def digest(self) -> Digest:
        return _digest(self.model_dump(mode="json"))


class BootstrapProof(StrictFrozenModel):
    scope_digest: Digest
    binding_digest: Digest
    issued_at: TimestampString
    signature: Digest


class ReconciliationProof(StrictFrozenModel):
    scope_digest: Digest
    operation_id: NonEmptyString
    action_epoch: Natural
    termination_digest: Digest
    evidence_digest: Digest
    issued_at: TimestampString
    signature: Digest


class RuntimeState(StrictFrozenModel):
    scope: RuntimeScope
    active: ActiveBinding
    action_state: ActionState
    action_epoch: Natural
    current_operation_id: NonEmptyString | None = None


class ActionLease(StrictFrozenModel):
    scope_digest: Digest
    operation_id: NonEmptyString
    request_digest: Digest
    action_epoch: Natural
    state: Literal["RUNNING", "IDLE"]
    replayed: bool = False
    outcome_digest: Digest | None = None
    outcome: bytes | None = Field(default=None, repr=False)

    @field_validator("outcome", mode="before")
    @classmethod
    def _decode_outcome(cls, value: object) -> bytes | None:
        if value is None or type(value) is bytes:
            return value
        if type(value) is str:
            try:
                return base64.b64decode(value.encode("ascii"), validate=True)
            except (ValueError, UnicodeError):
                raise ValueError("action outcome encoding is invalid") from None
        raise ValueError("action outcome must be bytes")

    @field_serializer("outcome")
    def _encode_outcome(self, value: bytes | None) -> str | None:
        return None if value is None else base64.b64encode(value).decode("ascii")


class BoundaryTicket(StrictFrozenModel):
    ticket_id: NonEmptyString
    scope_digest: Digest
    expected_generation: Natural
    action_epoch: Natural
    operation_id: NonEmptyString
    expires_at: TimestampString
    signature: Digest


class PreparedReplacement(StrictFrozenModel):
    """Opaque, authenticated hand-off record consumed by M5-6."""

    prepared_id: NonEmptyString
    scope_digest: Digest
    operation_id: NonEmptyString
    request_digest: Digest
    old_binding: ActiveBinding
    new_binding: ActiveBinding
    evidence_digest: Digest
    expires_at: TimestampString
    payload: bytes = Field(repr=False)
    effective_risk: Literal["low", "medium", "high", "critical"] = "low"
    approval_required: bool = False

    @field_validator("payload", mode="before")
    @classmethod
    def _decode_payload(cls, value: object) -> bytes:
        if type(value) is bytes:
            return value
        if type(value) is str:
            try:
                return base64.b64decode(value.encode("ascii"), validate=True)
            except (ValueError, UnicodeError):
                raise ValueError("prepared payload encoding is invalid") from None
        raise ValueError("prepared payload must be bytes")

    @field_serializer("payload")
    def _encode_payload(self, value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    @model_validator(mode="after")
    def _generation(self) -> PreparedReplacement:
        if self.new_binding.generation != self.old_binding.generation + 1:
            raise ValueError("prepared binding generation must advance exactly once")
        return self

    @property
    def digest(self) -> Digest:
        return _digest(self.model_dump(mode="json"))


class ActivationReceipt(StrictFrozenModel):
    receipt_id: NonEmptyString
    scope_digest: Digest
    operation_id: NonEmptyString
    prepared_id: NonEmptyString
    ticket_id: NonEmptyString
    request_digest: Digest
    old_binding: ActiveBinding
    new_binding: ActiveBinding
    generation_before: Natural
    generation_after: Natural
    approval_digest: Digest
    applied: bool = True
    rolled_back: bool = False
    signature: Digest

    @model_validator(mode="after")
    def _receipt_generations(self) -> ActivationReceipt:
        if self.generation_after != self.generation_before + 1:
            raise ValueError("receipt generation must advance exactly once")
        if self.old_binding.generation != self.generation_before:
            raise ValueError("receipt old binding generation mismatch")
        if self.new_binding.generation != self.generation_after:
            raise ValueError("receipt new binding generation mismatch")
        return self

    @property
    def digest(self) -> Digest:
        return _digest(self.model_dump(mode="json"))


class RollbackReceipt(StrictFrozenModel):
    receipt_id: NonEmptyString
    source_receipt_id: NonEmptyString
    scope_digest: Digest
    operation_id: NonEmptyString
    ticket_id: NonEmptyString
    request_digest: Digest
    restored_binding: ActiveBinding
    generation_before: Natural
    generation_after: Natural
    applied: bool = True
    signature: Digest

    @model_validator(mode="after")
    def _receipt_generations(self) -> RollbackReceipt:
        if self.generation_after != self.generation_before + 1:
            raise ValueError("rollback generation must advance exactly once")
        if self.restored_binding.generation != self.generation_after:
            raise ValueError("rollback binding generation mismatch")
        return self

    @property
    def digest(self) -> Digest:
        return _digest(self.model_dump(mode="json"))


__all__ = [
    "ActionLease",
    "ActionState",
    "ActivationReceipt",
    "ActiveBinding",
    "BootstrapProof",
    "BoundaryTicket",
    "PreparedReplacement",
    "ReconciliationProof",
    "RollbackReceipt",
    "RuntimeScope",
    "RuntimeState",
]
