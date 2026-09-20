"""Fail-closed pre-tool authorization for M6 high-risk tool classes."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from contractcapsule.models.base import (
    Digest,
    NonEmptyString,
    StrictFrozenModel,
    TimestampString,
)
from contractcapsule.models.canonical import canonical_json_bytes

RiskClass = Literal["low", "medium", "high", "critical"]


class HookReceipt(StrictFrozenModel):
    """Signed projection of a valid compiled-view/contract boundary."""

    operation_id: NonEmptyString
    view_digest: Digest
    contract_digest: Digest
    expires_at: TimestampString
    signature: Digest


def _receipt_signature(receipt: HookReceipt, key: bytes) -> str:
    unsigned = receipt.model_dump(mode="json", exclude={"signature"})
    payload = b"ccs-m6-hook-receipt/1\x00" + canonical_json_bytes(unsigned)
    return "sha256:" + hmac.new(key, payload, hashlib.sha256).hexdigest()


def sign_receipt(
    *,
    operation_id: str,
    view_digest: str,
    contract_digest: str,
    expires_at: str,
    key: bytes,
) -> HookReceipt:
    unsigned = HookReceipt(
        operation_id=operation_id,
        view_digest=view_digest,
        contract_digest=contract_digest,
        expires_at=expires_at,
        signature="sha256:" + "0" * 64,
    )
    return unsigned.model_copy(update={"signature": _receipt_signature(unsigned, key)})


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except (TypeError, ValueError):
        raise ValueError("timestamp rejected") from None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp rejected")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class PreToolHook:
    """Pure decision boundary; it does not execute tools or mutate state."""

    key: bytes
    clock: Callable[[], datetime]
    high_risk_tools: tuple[str, ...] = (
        "shell",
        "filesystem_write",
        "network",
        "external_side_effect",
    )

    def __post_init__(self) -> None:
        if type(self.key) is not bytes or len(self.key) < 32 or not callable(self.clock):
            raise ValueError("hook configuration rejected")

    def decide(self, request: Mapping[str, object]) -> dict[str, str]:
        if not isinstance(request, Mapping) or any(
            field not in request for field in ("tool_name", "risk_class", "operation_id")
        ):
            return {"decision": "deny", "code": "HOOK_INPUT_INVALID"}
        try:
            tool_name = request["tool_name"]
            risk_class = request["risk_class"]
            operation_id = request["operation_id"]
            if (
                type(tool_name) is not str
                or type(risk_class) is not str
                or type(operation_id) is not str
                or not tool_name
                or not operation_id
                or risk_class not in {"low", "medium", "high", "critical"}
            ):
                return {"decision": "deny", "code": "HOOK_INPUT_INVALID"}
            requires_receipt = tool_name in self.high_risk_tools or risk_class in {
                "high",
                "critical",
            }
            if not requires_receipt:
                return {"decision": "allow"}
            raw_receipt = request.get("view_receipt")
            if not isinstance(raw_receipt, Mapping):
                return {"decision": "deny", "code": "VIEW_RECEIPT_REQUIRED"}
            receipt = HookReceipt.model_validate(raw_receipt)
            if receipt.operation_id != operation_id:
                return {"decision": "deny", "code": "OPERATION_MISMATCH"}
            if not hmac.compare_digest(receipt.signature, _receipt_signature(receipt, self.key)):
                return {"decision": "deny", "code": "VIEW_RECEIPT_INVALID"}
            if _parse_utc(_stamp(self.clock())) >= _parse_utc(receipt.expires_at):
                return {"decision": "deny", "code": "VIEW_RECEIPT_EXPIRED"}
            return {"decision": "allow"}
        except Exception:  # noqa: BLE001 - hook failures are always denials.
            return {"decision": "deny", "code": "VIEW_RECEIPT_INVALID"}


def _stamp(value: datetime) -> str:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise ValueError("explicit UTC clock required")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


__all__ = ["HookReceipt", "PreToolHook", "RiskClass", "sign_receipt"]
