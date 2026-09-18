from pathlib import Path

import pytest

from contractcapsule.swap.controller import SwapController
from tests.integration.test_replacement import prepared, ready


def test_mid_tool_call_activation_is_rejected(tmp_path: Path):
    store, current_scope, old, _ticket = ready(tmp_path)
    lease = store.begin_action(current_scope, "tool-call", "sha256:" + "d" * 64)
    record = prepared(old, current_scope)
    controller = SwapController(store, current_scope, validator=lambda _record: True)
    controller.prepare(record)
    with pytest.raises(ValueError, match="running"):
        store.reserve_boundary(current_scope, "tool-call", expected_generation=0)
    store.end_action(current_scope, lease, outcome=b"tool-finished")


def test_irreversible_action_requires_control(tmp_path: Path):
    store, current_scope, old, ticket = ready(tmp_path)
    record = prepared(old, current_scope, risk="critical", required=False)
    controller = SwapController(store, current_scope, validator=lambda _record: True)
    controller.prepare(record)
    with pytest.raises(ValueError, match="approval"):
        controller.activate(record.prepared_id, ticket)


def test_failed_gate_preserves_active_pointer(tmp_path: Path):
    store, current_scope, old, _ticket = ready(tmp_path)
    record = prepared(old, current_scope)
    controller = SwapController(store, current_scope, validator=lambda _record: False)
    with pytest.raises(ValueError):
        controller.prepare(record)
    assert store.get(current_scope).active == old
