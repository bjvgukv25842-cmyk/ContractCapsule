"""Integration contract tests for the narrow MCP JSON-RPC facade."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from contractcapsule.mcp.server import MCPService, handle_json, handle_request
from contractcapsule.models.base import Principal
from contractcapsule.models.view import (
    CapsuleRef,
    CompiledView,
    EvidenceHandle,
    EvidenceMaterial,
    TaskContext,
    TokenAccounting,
    ValidationReport,
    ViewManifest,
)
from contractcapsule.storage.registry import PublishedCapsule
from contractcapsule.swap.runtime_models import (
    ActivationReceipt,
    ActiveBinding,
    BoundaryTicket,
    RollbackReceipt,
)
from tests.m4_helpers import M4Fixture

TIME = "2026-09-20T00:00:00Z"
DIGEST = "sha256:" + "a" * 64


class AllowAllMCPAuthorizer:
    def authorize_request(
        self, action: str, principal: Principal, params: dict[str, Any]
    ) -> bool:
        del action, principal, params
        return True


class DenyMCPAuthorizer:
    def authorize_request(
        self, action: str, principal: Principal, params: dict[str, Any]
    ) -> bool:
        del action, principal, params
        return False


class FakeCompiler:
    def __init__(self, view: CompiledView) -> None:
        self.view = view
        self.requests: list[Any] = []

    def compile_view(self, request: Any) -> CompiledView:
        self.requests.append(request)
        return self.view


class FakeEvidence:
    def __init__(self, material: EvidenceMaterial) -> None:
        self.material = material
        self.calls: list[tuple[Any, ...]] = []

    def expand(
        self,
        handle: EvidenceHandle,
        principal: Principal,
        task: TaskContext,
        as_of: str,
    ) -> EvidenceMaterial:
        self.calls.append((handle, principal, task, as_of))
        return self.material


class FakeSwap:
    def __init__(self, activation: ActivationReceipt, rollback: RollbackReceipt) -> None:
        self.activation = activation
        self.rollback_receipt = rollback
        self.activation_calls: list[tuple[Any, ...]] = []
        self.rollback_calls: list[tuple[Any, ...]] = []

    def activate(self, *args: Any) -> ActivationReceipt:
        self.activation_calls.append(args)
        return self.activation

    def rollback(self, *args: Any) -> RollbackReceipt:
        self.rollback_calls.append(args)
        return self.rollback_receipt


class EmptyRegistry:
    def get(self, *_args: Any) -> PublishedCapsule:
        raise RuntimeError("not configured")


def _task() -> dict[str, Any]:
    return {
        "task_id": "task-1",
        "tenant": "example",
        "repository": "example/api",
        "paths": ["src/a.py"],
        "environment": "dev",
        "text": "token",
    }


def _view() -> CompiledView:
    validation = ValidationReport(valid=True)
    manifest = ViewManifest(
        task_id="task-1",
        tenant="example",
        repository="example/api",
        as_of=TIME,
        task_digest=DIGEST,
        permission_digest=DIGEST,
        request_digest=DIGEST,
        model_id="test-model",
        tokenizer_profile="test-tokenizer",
        renderer_version="ccs-neutral/1.0.0",
        tokens=TokenAccounting(
            total=1,
            available=10,
            sections={"P0": 1},
            boundary_adjustment=0,
        ),
        validation=validation,
    )
    return CompiledView(content="P0: token\n", manifest=manifest, validation=validation)


def _runtime_receipts() -> tuple[BoundaryTicket, ActivationReceipt, RollbackReceipt]:
    ref = CapsuleRef(capsule_id="com.example.policy", version="1.0.0", digest=DIGEST)
    old = ActiveBinding(capsule=ref, view_digest=DIGEST, input_digest=DIGEST, generation=0)
    new = ActiveBinding(capsule=ref, view_digest=DIGEST, input_digest=DIGEST, generation=1)
    ticket = BoundaryTicket(
        ticket_id="ticket-1",
        scope_digest=DIGEST,
        expected_generation=0,
        action_epoch=0,
        operation_id="operation-1",
        expires_at=TIME,
        signature=DIGEST,
    )
    activation = ActivationReceipt(
        receipt_id="receipt-1",
        scope_digest=DIGEST,
        operation_id="operation-1",
        prepared_id="prepared-1",
        ticket_id=ticket.ticket_id,
        request_digest=DIGEST,
        old_binding=old,
        new_binding=new,
        generation_before=0,
        generation_after=1,
        approval_digest=DIGEST,
        signature=DIGEST,
    )
    rollback = RollbackReceipt(
        receipt_id="rollback-1",
        source_receipt_id=activation.receipt_id,
        scope_digest=DIGEST,
        operation_id="operation-1",
        ticket_id=ticket.ticket_id,
        request_digest=DIGEST,
        restored_binding=old.model_copy(update={"generation": 2}),
        generation_before=1,
        generation_after=2,
        signature=DIGEST,
    )
    return ticket, activation, rollback


def _service(
    registry: Any,
    *,
    authorizer: Any | None = None,
    compiler: Any | None = None,
    evidence: Any | None = None,
    swap: Any | None = None,
) -> MCPService:
    if not callable(getattr(registry, "get", None)):
        registry = EmptyRegistry()
    return MCPService(
        registry=registry,
        compiler=compiler or FakeCompiler(_view()),
        evidence=evidence or SimpleNamespace(expand=lambda *_args: None),
        swap=swap or SimpleNamespace(activate=lambda *_args: None, rollback=lambda *_args: None),
        authorizer=authorizer or AllowAllMCPAuthorizer(),
    )


def test_unknown_and_malformed_json_rpc_are_stable_errors() -> None:
    service = _service(SimpleNamespace())
    assert handle_request(
        service,
        {"jsonrpc": "2.0", "id": 1, "method": "unknown", "params": {}},
    ) == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": "METHOD_NOT_FOUND", "message": "method not found"},
    }
    assert handle_request(service, {"jsonrpc": "1.0", "id": 1, "method": "unknown"}) == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": "INVALID_REQUEST", "message": "invalid request"},
    }
    assert handle_json(service, "not-json") == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": "INVALID_REQUEST", "message": "invalid request"},
    }


def test_permission_denial_does_not_call_compiler() -> None:
    compiler = FakeCompiler(_view())
    service = _service(SimpleNamespace(), authorizer=DenyMCPAuthorizer(), compiler=compiler)
    response = handle_request(
        service,
        {
            "jsonrpc": "2.0",
            "id": "compile-1",
            "method": "compile_view",
            "params": {
                "principal_id": "reader",
                "capsules": [],
                "task": _task(),
                "budget": {"model_input_tokens": 10},
                "as_of": TIME,
                "model_id": "test-model",
                "tokenizer_profile": "test-tokenizer",
            },
        },
    )
    assert response["error"]["code"] == "PERMISSION_DENIED"
    assert compiler.requests == []


def test_compile_view_uses_registry_refs_and_replay_identity(tmp_path: Path) -> None:
    fixture = M4Fixture.create(tmp_path)
    publication = fixture.publish()
    compiler = FakeCompiler(_view())
    service = _service(fixture.registry, compiler=compiler)
    manifest_digest = "sha256:" + "b" * 64
    response = handle_request(
        service,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "compile_view",
            "params": {
                "principal_id": "reader",
                "capsules": [
                    {
                        "capsule_id": publication.capsule.control_manifest.capsule_id,
                        "version": publication.capsule.control_manifest.version,
                        "digest": publication.capsule.control_manifest.content_digest,
                    }
                ],
                "task": _task(),
                "budget": {"model_input_tokens": 10},
                "as_of": TIME,
                "model_id": "test-model",
                "tokenizer_profile": "test-tokenizer",
                "expected_manifest_digest": manifest_digest,
            },
        },
    )
    assert response["result"]["manifest_digest"] != manifest_digest
    assert response["result"]["view"]["content"] == "P0: token\n"
    assert len(compiler.requests) == 1
    assert isinstance(compiler.requests[0].capsules[0], PublishedCapsule)


def test_expand_evidence_reauthorizes_and_returns_material() -> None:
    ref = CapsuleRef(capsule_id="com.example.policy", version="1.0.0", digest=DIGEST)
    handle = EvidenceHandle(
        capsule=ref,
        evidence_id="ev-1",
        atom_ids=("atom-1",),
        mode="CAS",
        content_digest=DIGEST,
        span_digest=None,
        resolver_version="1.0.0",
    )
    material = EvidenceMaterial(handle=handle, excerpt="rule\n", full_text="rule\n")
    evidence = FakeEvidence(material)
    service = _service(SimpleNamespace(), evidence=evidence)
    result = handle_request(
        service,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "expand_evidence",
            "params": {
                "principal_id": "reader",
                "handle": handle.model_dump(mode="json"),
                "task": _task(),
                "as_of": TIME,
            },
        },
    )
    assert result["result"]["evidence"]["full_text"] == "rule\n"
    assert evidence.calls[0][1] == Principal("reader")


def test_activation_and_rollback_delegate_without_exposing_keys() -> None:
    ticket, activation, rollback = _runtime_receipts()
    swap = FakeSwap(activation, rollback)
    service = _service(SimpleNamespace(), swap=swap)
    activated = handle_request(
        service,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "activate_capsule",
            "params": {
                "prepared_id": "prepared-1",
                "ticket": ticket.model_dump(mode="json"),
            },
        },
    )
    rolled_back = handle_request(
        service,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "rollback_capsule",
            "params": {
                "receipt_id": activation.receipt_id,
                "ticket": ticket.model_dump(mode="json"),
            },
        },
    )
    assert activated["result"]["receipt"]["receipt_id"] == activation.receipt_id
    assert rolled_back["result"]["receipt"]["receipt_id"] == rollback.receipt_id
    assert swap.activation_calls[0][0] == "prepared-1"
    assert swap.rollback_calls[0][0] == activation.receipt_id
    assert "key" not in str(activated)
    assert "secret" not in str(activated)


def test_compare_capsules_returns_only_public_identity(tmp_path: Path) -> None:
    fixture = M4Fixture.create(tmp_path)
    publication = fixture.publish()
    ref = {
        "capsule_id": publication.capsule.control_manifest.capsule_id,
        "version": publication.capsule.control_manifest.version,
        "digest": publication.capsule.control_manifest.content_digest,
    }
    response = handle_request(
        _service(fixture.registry),
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "compare_capsules",
            "params": {"principal_id": "reader", "old": ref, "new": ref},
        },
    )
    assert response["result"]["same_digest"] is True
    assert response["result"]["changed_manifest_fields"] == []
    assert "semantic_payload" not in str(response)


@pytest.mark.parametrize("method", ["activate_capsule", "rollback_capsule"])
def test_swap_parse_failures_are_non_disclosing(method: str) -> None:
    response = handle_request(
        _service(SimpleNamespace()),
        {"jsonrpc": "2.0", "id": 7, "method": method, "params": {}},
    )
    assert response["error"]["code"] == "INVALID_PARAMS"
    assert "Traceback" not in str(response)
