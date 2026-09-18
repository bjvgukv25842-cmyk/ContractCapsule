"""Post-publication authority distinct from publication identity."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from contractcapsule.models.base import (
    Digest,
    NonEmptyString,
    StrictFrozenModel,
    TimestampString,
)
from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.validate.contracts import execution_subject
from contractcapsule.validate.models import BoundExecution


class ApprovalError(ValueError):
    """Safe authority failure. Verification never consumes approval."""


class Approval(StrictFrozenModel):
    issuer: NonEmptyString
    domain: Literal["execution", "activation"]
    operation_id: NonEmptyString
    subject: Digest
    issued_at: TimestampString
    expires_at: TimestampString
    synthetic: bool
    signature: Digest


def _utc(value: datetime) -> str:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise ApprovalError("explicit UTC clock required")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except (TypeError, ValueError):
        raise ApprovalError("approval rejected") from None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ApprovalError("approval rejected")
    return parsed.astimezone(UTC)


def _signature(key: bytes, approval: Approval) -> str:
    payload = approval.model_dump(mode="json", exclude={"signature"})
    data = b"ccs-m5-approval-envelope/1.0.0\x00" + canonical_json_bytes(payload)
    return "sha256:" + hmac.new(key, data, hashlib.sha256).hexdigest()


def activation_subject(
    *,
    operation_id: str,
    prepared_digest: str,
    scope_digest: str,
    request_digest: str,
    expected_generation: int,
) -> str:
    """Bind Task5/6 prepared evidence; approval envelope excluded by construction."""
    payload = {
        "domain": "ccs-m5-activation-approval/1.0.0",
        "operation_id": operation_id,
        "prepared_digest": prepared_digest,
        "scope_digest": scope_digest,
        "request_digest": request_digest,
        "expected_generation": expected_generation,
    }
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class ApprovalVerifier:
    issuer: str
    _key: bytes = field(repr=False)

    def verify(
        self,
        approval: object,
        *,
        domain: Literal["execution", "activation"],
        operation_id: str,
        subject: str,
        now: datetime,
    ) -> Approval:
        try:
            if type(approval) is not Approval:
                raise ApprovalError("approval rejected")
            checked = Approval.model_validate(dict(approval.__dict__))
            current = _parse_utc(_utc(now))
            valid = (
                checked.issuer == self.issuer
                and checked.domain == domain
                and checked.operation_id == operation_id
                and checked.subject == subject
                and _parse_utc(checked.issued_at) <= current < _parse_utc(checked.expires_at)
                and hmac.compare_digest(
                    checked.signature, _signature(self._key, checked)
                )
            )
            if not valid:
                raise ApprovalError("approval rejected")
            return checked
        except (ValueError, TypeError, AttributeError) as error:
            raise ApprovalError("approval rejected") from error

    def verify_execution(
        self, approval: object, bound: BoundExecution, *, now: datetime
    ) -> Approval:
        return self.verify(
            approval,
            domain="execution",
            operation_id=bound.request.operation_id,
            subject=execution_subject(bound),
            now=now,
        )


@dataclass(frozen=True)
class ApprovalAuthority:
    issuer: str
    _key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not self.issuer or type(self._key) is not bytes or len(self._key) < 16:
            raise ApprovalError("invalid authority configuration")

    def verifier(self) -> ApprovalVerifier:
        return ApprovalVerifier(self.issuer, self._key)

    def issue(
        self,
        *,
        domain: Literal["execution", "activation"],
        operation_id: str,
        subject: str,
        issued_at: datetime,
        expires_at: datetime,
        synthetic: bool,
    ) -> Approval:
        start, end = _utc(issued_at), _utc(expires_at)
        if start >= end:
            raise ApprovalError("invalid approval interval")
        unsigned = Approval(
            issuer=self.issuer,
            domain=domain,
            operation_id=operation_id,
            subject=subject,
            issued_at=start,
            expires_at=end,
            synthetic=synthetic,
            signature="sha256:" + "0" * 64,
        )
        return Approval.model_validate(
            {**unsigned.__dict__, "signature": _signature(self._key, unsigned)}
        )

    def issue_execution(
        self,
        bound: BoundExecution,
        *,
        issued_at: datetime,
        expires_at: datetime,
        synthetic: bool,
    ) -> Approval:
        return self.issue(
            domain="execution",
            operation_id=bound.request.operation_id,
            subject=execution_subject(bound),
            issued_at=issued_at,
            expires_at=expires_at,
            synthetic=synthetic,
        )
