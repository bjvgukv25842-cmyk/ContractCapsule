from pathlib import Path

import pytest

from contractcapsule.models.view import CapsuleRef
from contractcapsule.swap.boundary import SafeBoundary
from contractcapsule.swap.runtime_models import ActiveBinding, RuntimeScope
from contractcapsule.swap.store import RuntimeStore


def test_boundary_facade_requires_completed_action_and_consumes_once(tmp_path: Path):
    store = RuntimeStore(
        tmp_path / "registry.db",
        b"b" * 32,
        binding_validator=lambda _scope, _binding: True,
        termination_validator=lambda _scope, _operation, _evidence: True,
    )
    scope = RuntimeScope(
        tenant="tenant",
        principal="principal",
        repository="repo",
        environment="test",
        session="session",
    )
    binding = ActiveBinding(
        capsule=CapsuleRef(
            capsule_id="com.example.policy",
            version="1.0.0",
            digest="sha256:" + "a" * 64,
        ),
        view_digest="sha256:" + "b" * 64,
        input_digest="sha256:" + "c" * 64,
        generation=0,
    )
    store.initialize(scope, binding, store.issue_bootstrap(scope, binding))
    boundary = SafeBoundary(store, scope)
    lease = boundary.begin("op", "sha256:" + "d" * 64)
    with pytest.raises(ValueError, match="action"):
        boundary.reserve("op", expected_generation=0)
    boundary.end(lease)
    ticket = boundary.reserve("op", expected_generation=0)
    assert boundary.consume(ticket).ticket_id == ticket.ticket_id
    with pytest.raises(ValueError, match="ticket"):
        boundary.consume(ticket)
