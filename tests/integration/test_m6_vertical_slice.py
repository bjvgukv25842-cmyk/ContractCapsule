"""One deterministic M6 boundary path using a local fixture and fake agent."""

from __future__ import annotations

import stat
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent
from typing import Any, cast

from contractcapsule.adapters.base import AgentTask
from contractcapsule.adapters.codex import CodexAdapter
from contractcapsule.adapters.hook import PreToolHook, sign_receipt
from contractcapsule.compile.budget import LocalTokenCounter
from contractcapsule.compile.compiler import ViewCompiler
from contractcapsule.compile.evidence import NativeEvidenceResolver
from contractcapsule.compile.renderers import NeutralViewRenderer
from contractcapsule.mcp.server import MCPService, handle_request
from contractcapsule.models.base import Principal
from contractcapsule.models.view import (
    CompileRequest,
    EvidenceHandle,
    EvidenceMaterial,
    TaskContext,
    ViewBudget,
    view_manifest_digest,
)
from contractcapsule.resolve.policies import StaticEligibilityAuthorizer
from contractcapsule.resolve.rank import FTS5BM25Ranker
from contractcapsule.storage.registry import PublishedCapsule
from tests.m4_helpers import M4Fixture
from tests.unit.test_eligibility import AS_OF, access_grant, freshness_for, task_context


class _AllowAll:
    def authorize_request(
        self, action: str, principal: Principal, params: dict[str, Any]
    ) -> bool:
        del action, principal, params
        return True


class _EvidenceSpy:
    def __init__(self) -> None:
        self.handle: EvidenceHandle | None = None

    def expand(
        self,
        handle: EvidenceHandle,
        principal: Principal,
        task: TaskContext,
        as_of: str,
    ) -> EvidenceMaterial:
        del principal, task, as_of
        if self.handle is None or handle != self.handle:
            raise ValueError("unexpected evidence handle")
        return EvidenceMaterial(handle=handle, excerpt="Rule 0", full_text="Rule 0\n")


class _SwapSpy:
    def __init__(self) -> None:
        self.activations: list[tuple[object, ...]] = []
        self.rollbacks: list[tuple[object, ...]] = []

    def activate(self, *args: object) -> dict[str, str]:
        self.activations.append(args)
        return {"receipt_id": "activation-1"}

    def rollback(self, *args: object) -> dict[str, str]:
        self.rollbacks.append(args)
        return {"receipt_id": "rollback-1"}


def _compiler(
    fixture: M4Fixture, publication: PublishedCapsule
) -> tuple[ViewCompiler, TaskContext]:
    authorizer = StaticEligibilityAuthorizer(grants=(access_grant(),))
    freshness = freshness_for(publication)  # type: ignore[arg-type]
    evidence = NativeEvidenceResolver(fixture.registry, authorizer, freshness, {}, {})
    compiler = ViewCompiler(
        registry=fixture.registry,
        authorizer=authorizer,
        freshness=freshness,
        ranker=FTS5BM25Ranker(),
        counter=LocalTokenCounter("offline-test-model"),
        evidence=evidence,
        renderer=NeutralViewRenderer(),
    )
    return compiler, task_context(text="token")


def _fake_codex(path: Path, marker: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        + dedent(
            f"""
            import json
            import sys

            if sys.argv[1:] == ["--version"]:
                print(json.dumps({{"agent": "codex", "version": "1.2.3", "model": "m6-test"}}))
            else:
                open({str(marker)!r}, "w", encoding="utf-8").write("ran")
                print(json.dumps({{"agent": "codex", "version": "1.2.3", "model": "m6-test"}}))
                print(json.dumps({{"usage": {{"input_tokens": 2, "output_tokens": 1}}}}))
            """
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_m6_vertical_slice_gates_agent_and_preserves_public_identity(tmp_path: Path) -> None:
    fixture = M4Fixture.create(tmp_path)
    publication = fixture.publish(
        atoms=({"statement": "Rule 0 must hold.\n", "compression_class": "P0_EXACT"},)
    )
    compiler, task = _compiler(fixture, publication)
    evidence = _EvidenceSpy()
    swap = _SwapSpy()
    service = MCPService(
        registry=fixture.registry,
        compiler=compiler,
        evidence=evidence,
        swap=swap,
        authorizer=_AllowAll(),
    )
    ref = publication.capsule.control_manifest
    reference = {
        "capsule_id": ref.capsule_id,
        "version": ref.version,
        "digest": ref.content_digest,
    }
    discovered = handle_request(
        service,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "discover_capsules",
            "params": {"principal_id": "reader"},
        },
    )
    discovered_result = cast(dict[str, Any], discovered["result"])
    discovered_capsules = cast(list[dict[str, Any]], discovered_result["capsules"])
    assert discovered_capsules[0]["digest"] == ref.content_digest

    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "compile_view",
        "params": {
            "principal_id": "reader",
            "capsules": [reference],
            "task": task.model_dump(mode="json"),
            "budget": ViewBudget(model_input_tokens=10000).model_dump(mode="json"),
            "as_of": AS_OF,
            "model_id": "offline-test-model",
            "tokenizer_profile": "ccs-neutral-o200k/1.0.0",
        },
    }
    compiled = handle_request(service, request)
    assert "result" in compiled
    view = compiler.compile_view(
        # The MCP request is the same trusted projection used for this local
        # adapter seam; the public response is checked against its digest.
        CompileRequest(
            capsules=(publication,),
            task=task,
            principal=Principal("reader"),
            budget=ViewBudget(model_input_tokens=10000),
            as_of=AS_OF,
            model_id="offline-test-model",
            tokenizer_profile="ccs-neutral-o200k/1.0.0",
        )
    )
    compiled_result = cast(dict[str, Any], compiled["result"])
    assert compiled_result["manifest_digest"] == view_manifest_digest(view.manifest)
    assert view.evidence_handles
    evidence.handle = view.evidence_handles[0]
    expanded = handle_request(
        service,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "expand_evidence",
            "params": {
                "principal_id": "reader",
                "handle": evidence.handle.model_dump(mode="json"),
                "task": task.model_dump(mode="json"),
                "as_of": AS_OF,
            },
        },
    )
    expanded_result = cast(dict[str, Any], expanded["result"])
    expanded_evidence = cast(dict[str, Any], expanded_result["evidence"])
    assert expanded_evidence["full_text"] == "Rule 0\n"

    marker = tmp_path / "agent-ran"
    binary = _fake_codex(tmp_path / "codex-fake", marker)
    adapter = CodexAdapter(binary=str(binary), timeout_seconds=5)
    hook = PreToolHook(
        key=b"m" * 32,
        clock=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )
    denied = hook.decide(
        {"tool_name": "shell", "risk_class": "high", "operation_id": "op-1"}
    )
    assert denied == {"decision": "deny", "code": "VIEW_RECEIPT_REQUIRED"}
    assert not marker.exists()
    receipt = sign_receipt(
        operation_id="op-1",
        view_digest=view_manifest_digest(view.manifest),
        contract_digest="sha256:" + "b" * 64,
        expires_at="2030-01-01T00:01:00Z",
        key=b"m" * 32,
    )
    assert hook.decide(
        {
            "tool_name": "shell",
            "risk_class": "high",
            "operation_id": "op-1",
            "view_receipt": receipt.model_dump(mode="json"),
        }
    ) == {"decision": "allow"}
    run = adapter.run(
        AgentTask(task_id="task-1", prompt="solve", cwd=tmp_path, timeout_seconds=5),
        view,
        tmp_path,
    )
    assert run.metadata.agent == "codex"
    assert marker.read_text(encoding="utf-8") == "ran"

    # The MCP boundary still delegates replacement; it does not let the
    # adapter mutate the active pointer directly.
    ticket = {
        "ticket_id": "ticket-1",
        "scope_digest": "sha256:" + "a" * 64,
        "expected_generation": 0,
        "action_epoch": 0,
        "operation_id": "op-1",
        "expires_at": "2030-01-01T00:01:00Z",
        "signature": "sha256:" + "c" * 64,
    }
    activated = handle_request(
        service,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "activate_capsule",
            "params": {"prepared_id": "prepared-1", "ticket": ticket},
        },
    )
    rolled_back = handle_request(
        service,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "rollback_capsule",
            "params": {"receipt_id": "activation-1", "ticket": ticket},
        },
    )
    activated_result = cast(dict[str, Any], activated["result"])
    rolled_back_result = cast(dict[str, Any], rolled_back["result"])
    assert cast(dict[str, Any], activated_result["receipt"])["receipt_id"] == "activation-1"
    assert cast(dict[str, Any], rolled_back_result["receipt"])["receipt_id"] == "rollback-1"
    assert len(swap.activations) == 1
    assert len(swap.rollbacks) == 1
