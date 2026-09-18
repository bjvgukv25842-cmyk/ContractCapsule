"""M5-7 reference path: validate, execute, activate, restart, and rollback."""

from datetime import timedelta

from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.resolve.policies import capsule_ref
from contractcapsule.swap.controller import SwapController
from contractcapsule.swap.runtime_models import (
    ActiveBinding,
    PreparedReplacement,
    RuntimeScope,
)
from contractcapsule.swap.store import RuntimeStore
from contractcapsule.validate.run_models import digest_bytes, identity
from tests.m5_helpers import digest
from tests.m5_twin_helpers import TwinFixture


def test_reference_task_reaches_activation_and_rollback(tmp_path):
    fixture = TwinFixture(tmp_path)
    outcome = fixture.runner.run(fixture.approval)
    assert outcome.valid
    fixture.runner.verify_outcome(outcome)

    bound, binding_payload = fixture.runner._bind(fixture.approval)
    old_view = fixture.old_validation.compiler.compile_view(
        fixture.old_validation.request
    )
    new_view = fixture.new_validation.compiler.compile_view(
        fixture.new_validation.request
    )
    scope = RuntimeScope(
        tenant=bound.request.task.tenant,
        principal=bound.request.principal.principal_id,
        repository=bound.request.source_repository,
        environment=bound.request.task.environment,
        session="m5-exit-reference",
    )
    evidence = outcome.payload_bytes()
    request_digest = digest(
        canonical_json_bytes(
            {
                "operation_id": bound.request.operation_id,
                "binding": digest_bytes(binding_payload),
                "evidence": digest_bytes(evidence),
            }
        )
    )
    old_binding = ActiveBinding(
        capsule=capsule_ref(fixture.old.capsule),
        view_digest=identity(old_view.model_dump(mode="json")),
        input_digest=digest_bytes(evidence),
        generation=0,
    )
    new_binding = ActiveBinding(
        capsule=capsule_ref(fixture.new.capsule),
        view_digest=identity(new_view.model_dump(mode="json")),
        input_digest=digest_bytes(evidence),
        generation=1,
    )
    store = RuntimeStore(
        fixture.base.registry.database_path,
        b"m" * 32,
        clock=fixture.clock,
        binding_validator=lambda _scope, _binding: True,
        termination_validator=lambda _scope, _operation, proof: proof == b"stopped",
    )
    store.initialize(scope, old_binding, store.issue_bootstrap(scope, old_binding))
    lease = store.begin_action(scope, bound.request.operation_id, request_digest)
    store.end_action(scope, lease, outcome=evidence)
    ticket = store.reserve_boundary(scope, bound.request.operation_id, 0)
    prepared = PreparedReplacement(
        prepared_id="m5-exit-prepared",
        scope_digest=scope.digest,
        operation_id=bound.request.operation_id,
        request_digest=request_digest,
        old_binding=old_binding,
        new_binding=new_binding,
        evidence_digest=digest_bytes(evidence),
        expires_at=(fixture.now + timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z"
        ),
        payload=evidence,
    )
    controller = SwapController(
        store,
        scope,
        validator=lambda record: record.evidence_digest == digest_bytes(evidence),
        rollback_validator=lambda receipt: receipt.new_binding == new_binding,
        clock=fixture.clock,
    )
    controller.prepare(prepared)
    activation = controller.activate(prepared.prepared_id, ticket)
    assert activation.new_binding == new_binding

    restarted = RuntimeStore(
        fixture.base.registry.database_path,
        b"m" * 32,
        clock=fixture.clock,
        binding_validator=lambda _scope, _binding: True,
        termination_validator=lambda _scope, _operation, proof: proof == b"stopped",
    )
    assert restarted.get(scope).active == new_binding
    assert restarted.get_receipt(scope, activation.receipt_id) == activation

    rollback_ticket = restarted.reserve_boundary(
        scope, bound.request.operation_id, expected_generation=1
    )
    rollback = controller.rollback(activation.receipt_id, rollback_ticket)
    assert rollback.applied
    assert restarted.get(scope).active == old_binding.model_copy(update={"generation": 2})
