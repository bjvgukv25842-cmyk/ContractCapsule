"""M6 pre-tool hook and Skill boundary tests."""

from datetime import UTC, datetime

from contractcapsule.adapters.hook import PreToolHook, sign_receipt


def _hook(now: datetime) -> PreToolHook:
    return PreToolHook(key=b"h" * 32, clock=lambda: now)


def _receipt(expires_at: str):
    return sign_receipt(
        operation_id="op-1",
        view_digest="sha256:" + "a" * 64,
        contract_digest="sha256:" + "b" * 64,
        expires_at=expires_at,
        key=b"h" * 32,
    ).model_dump(mode="json")


def test_low_risk_tool_does_not_require_a_receipt() -> None:
    assert _hook(datetime(2026, 9, 20, tzinfo=UTC)).decide(
        {"tool_name": "read", "risk_class": "low", "operation_id": "op-1"}
    ) == {"decision": "allow"}


def test_high_risk_tool_requires_a_valid_current_receipt() -> None:
    hook = _hook(datetime(2026, 9, 20, tzinfo=UTC))
    request = {
        "tool_name": "shell",
        "risk_class": "high",
        "operation_id": "op-1",
        "view_receipt": _receipt("2026-09-20T00:01:00Z"),
    }
    assert hook.decide(request) == {"decision": "allow"}
    request["view_receipt"] = _receipt("2026-09-19T23:59:59Z")
    assert hook.decide(request) == {"decision": "deny", "code": "VIEW_RECEIPT_EXPIRED"}


def test_hook_rejects_wrong_operation_and_tampered_signature() -> None:
    hook = _hook(datetime(2026, 9, 20, tzinfo=UTC))
    request = {
        "tool_name": "filesystem_write",
        "risk_class": "critical",
        "operation_id": "op-2",
        "view_receipt": _receipt("2026-09-20T00:01:00Z"),
    }
    assert hook.decide(request) == {"decision": "deny", "code": "OPERATION_MISMATCH"}
    request["operation_id"] = "op-1"
    request["view_receipt"]["view_digest"] = "sha256:" + "c" * 64
    assert hook.decide(request) == {"decision": "deny", "code": "VIEW_RECEIPT_INVALID"}


def test_hook_malformed_input_is_a_stable_denial() -> None:
    assert _hook(datetime(2026, 9, 20, tzinfo=UTC)).decide({"risk_class": "high"}) == {
        "decision": "deny",
        "code": "HOOK_INPUT_INVALID",
    }
