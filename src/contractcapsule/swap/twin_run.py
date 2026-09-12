"""Trusted host orchestration for authenticated Docker twin executions."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from contractcapsule.compile.compiler import ViewCompiler
from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.models.view import CompiledView, CompileRequest
from contractcapsule.storage.registry import Registry
from contractcapsule.swap.attempts import AttemptStore
from contractcapsule.swap.docker_runner import DockerRunner, StageResult
from contractcapsule.swap.source import git_tree
from contractcapsule.swap.trees import FrozenTree, RunnerError
from contractcapsule.swap.twin_models import AttemptManifest, TwinFailure, TwinOutcome
from contractcapsule.validate.approvals import Approval, ApprovalVerifier
from contractcapsule.validate.artifacts import LocalArtifactResolver
from contractcapsule.validate.behavior import BehaviorService, HostRunRecorder
from contractcapsule.validate.contracts import (
    execution_subject,
    parse_execution_contract,
)
from contractcapsule.validate.integrity import ValidationService
from contractcapsule.validate.journal import RecordJournal
from contractcapsule.validate.models import (
    BoundExecution,
    ReplacementRequest,
)
from contractcapsule.validate.run_models import (
    CheckCapture,
    EvaluationContext,
    PairEvidence,
    RunEvidence,
    stage_subject,
)


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class TwinResult:
    """Compatibility type retained while the untrusted legacy facade is removed."""

    old: StageResult
    new: StageResult


class TwinRunner:
    """Explicitly composed trusted host runner.

    The runner never accepts caller supplied program strings. Programs and
    checks come solely from the Task1 artifact binding and are staged through
    the restricted DockerRunner.
    """

    def __init__(
        self,
        config=None,
        *,
        request: ReplacementRequest | None = None,
        registry: Registry | None = None,
        artifacts: LocalArtifactResolver | None = None,
        compiler: ViewCompiler | None = None,
        old_compiler: ViewCompiler | None = None,
        new_compiler: ViewCompiler | None = None,
        runner: DockerRunner | None = None,
        approval_verifier: ApprovalVerifier | None = None,
        journal: RecordJournal | None = None,
        attempt_store: AttemptStore | None = None,
        source_root=None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.config = config
        self.request = request
        self.registry = registry
        self.artifacts = artifacts
        self.compiler = compiler
        self.old_compiler = old_compiler or compiler
        self.new_compiler = new_compiler or compiler
        self.runner = runner
        self.approval_verifier = approval_verifier
        self.journal = journal
        self.attempt_store = attempt_store
        self.source_root = source_root
        self.clock = clock

    def run_pair(self, **_: object) -> TwinResult:
        raise RunnerError("legacy program-string twin facade is unavailable")

    def run(self, approval: Approval) -> TwinOutcome | TwinFailure:
        request = self.request
        if type(request) is not ReplacementRequest:
            return TwinFailure(operation_id="unknown", code="COMPOSITION_UNAVAILABLE")
        try:
            bound = self._bind()
            if self.approval_verifier is None or self.journal is None:
                raise RunnerError("composition unavailable")
            checked = self.approval_verifier.verify_execution(
                approval, bound, now=self.clock()
            )
            binding_digest = _digest(
                {
                    "execution": execution_subject(bound),
                    "profile": bound.profile.model_dump(mode="json"),
                }
            )
            if self.attempt_store is not None:
                reserved = self.attempt_store.reserve(
                    request.operation_id, binding_digest
                )
                if reserved.state == "COMPLETE":
                    raise RunnerError("attempt already complete; verified replay required")
            old_view, new_view = self._compile_and_validate(bound)
            source = self._source(bound)
            context = EvaluationContext(
                initial=source.snapshot,
                old_view_digest=_digest(old_view.model_dump(mode="json")),
                new_view_digest=_digest(new_view.model_dump(mode="json")),
                approval_digest=_digest(checked.model_dump(mode="json")),
                synthetic=checked.synthetic,
            )
            recorder = HostRunRecorder(
                bound, context, self.journal
            )
            behavior = BehaviorService(
                bound, context, self.journal.verifier(), self.journal
            )
            pairs = tuple(
                self._run_pair_once(
                    bound, context, recorder, behavior, source, old_view, new_view, index
                )
                for index in range(bound.profile.repetitions)
            )
            repetitions = behavior.evaluate_repetitions(pairs)
            state = "COMPLETE" if repetitions.valid else "FAILED"
            if repetitions.record is None:
                raise RunnerError("repetition report persistence failed")
            manifest = AttemptManifest(
                operation_id=request.operation_id,
                binding_digest=binding_digest,
                approval_digest=checked.signature,
                source_commit=request.source_commit,
                context=context,
                repetitions=tuple(range(bound.profile.repetitions)),
                repetition_record=repetitions.record,
                created_at=self.clock()
                .astimezone(UTC)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z"),
                state=state,  # type: ignore[arg-type]
            )
            if self.attempt_store is not None:
                self.attempt_store.complete(
                    request.operation_id, manifest.payload_bytes()
                )
            return TwinOutcome(
                manifest=manifest, approval=checked, repetitions=repetitions
            )
        except RunnerError as exc:
            return TwinFailure(operation_id=request.operation_id, code=str(exc) or "TWIN_RUN_REJECTED")
        except Exception:  # noqa: BLE001 - stable external failure boundary
            return TwinFailure(operation_id=request.operation_id, code="TWIN_RUN_REJECTED")

    def _bind(self) -> BoundExecution:
        if self.registry is None or self.artifacts is None or self.request is None:
            raise RunnerError("composition unavailable")
        if self.artifacts is None:
            raise RunnerError("artifact resolver unavailable")
        return parse_execution_contract(self.request, self.registry, self.artifacts)

    def _compile_and_validate(
        self, bound: BoundExecution
    ) -> tuple[CompiledView, CompiledView]:
        if self.old_compiler is None or self.new_compiler is None:
            raise RunnerError("compiler unavailable")
        common: dict[str, object] = {
            "task": bound.request.task,
            "principal": bound.request.principal,
            "budget": bound.request.budget,
            "as_of": self.clock().astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "model_id": bound.request.model_id,
            "tokenizer_profile": bound.request.tokenizer_profile,
            "renderer_version": bound.request.renderer_version,
        }
        old_request = CompileRequest(capsules=(bound.request.old,), **common)  # type: ignore[arg-type]
        new_request = CompileRequest(capsules=(bound.request.new,), **common)  # type: ignore[arg-type]
        old_view = self.old_compiler.compile_view(old_request)
        new_view = self.new_compiler.compile_view(new_request)
        if not old_view.validation.valid or not new_view.validation.valid:
            raise RunnerError("view validation failed")
        for request, view, compiler, capsule in (
            (old_request, old_view, self.old_compiler, bound.request.old.capsule),
            (new_request, new_view, self.new_compiler, bound.request.new.capsule),
        ):
            service = ValidationService(
                request, compiler, self.artifacts, self._journal(), self.clock  # type: ignore[arg-type]
            )
            reports = (
                service.validate_integrity(capsule),
                service.validate_evidence(capsule),
                service.validate_compression(view, [capsule]),
            )
            if any(not report.valid for report in reports):
                raise RunnerError("independent view validation failed")
        return old_view, new_view

    def _journal(self) -> RecordJournal:
        if self.journal is None:
            raise RunnerError("journal unavailable")
        return self.journal

    def _source(self, bound: BoundExecution) -> FrozenTree:
        if self.source_root is None:
            raise RunnerError("source root unavailable")
        return git_tree(
            self.source_root,
            bound.request.source_commit,
            bound.profile.runner,
            bound.request.source_repository,
        )

    def _run_pair_once(
        self,
        bound: BoundExecution,
        context: EvaluationContext,
        recorder: HostRunRecorder,
        behavior: BehaviorService,
        source: FrozenTree,
        old_view: CompiledView,
        new_view: CompiledView,
        repetition: int,
    ):
        if self.runner is None:
            raise RunnerError("stage runner unavailable")
        pre = tuple(item for item in bound.profile.checks if item.phase == "pre")
        old_pre = self._check_group(bound, context, source, old_view, "old", repetition, pre)
        new_pre = self._check_group(bound, context, source, new_view, "new", repetition, pre)
        if any(
            capture.process.exit_code != 0
            or not capture.process.terminated
            or capture.process.timed_out
            or capture.process.output_limited
            for capture in (*old_pre, *new_pre)
        ):
            raise RunnerError("precondition failed")
        old_run, old_agent = self._run_role(
            bound, context, recorder, source, old_view, "old", repetition, old_pre
        )
        new_run, new_agent = self._run_role(
            bound, context, recorder, source, new_view, "new", repetition, new_pre
        )
        pair_checks = tuple(item for item in bound.profile.checks if item.phase == "pair")
        pair_captures = self._check_group(
            bound,
            context,
            source,
            new_view,
            "pair",
            repetition,
            pair_checks,
            old_final=old_run.final,
            new_final=new_run.final,
        )
        evidence = PairEvidence(
            repetition=repetition,
            old_record=old_agent.record,
            new_record=new_agent.record,
            checks=pair_captures,
        )
        old_agent, new_agent = recorder.record_pair(old_agent, new_agent, evidence)
        return behavior.compare_runs(
            old_agent,
            new_agent,
            bound.request.new.capsule.replacement_contract,
        )

    def _run_role(
        self, bound, context, recorder, source, view, role, repetition, pre
    ):
        executor = bound.profile.executor
        stage = self._stage(
            bound, context, source, view, role, repetition, executor, "executor", source
        )
        if stage.tree is None or stage.snapshot_ns is None:
            raise RunnerError("executor capture failed")
        post = tuple(item for item in bound.profile.checks if item.phase == "post")
        captures = self._check_group(
            bound,
            context,
            stage.tree,
            view,
            role,
            repetition,
            post,
            old_final=stage.tree,
            new_final=stage.tree,
        )
        evidence = RunEvidence(
            role=role,
            repetition=repetition,
            final=stage.tree,
            snapshot_ns=stage.snapshot_ns,
            executor=stage.process,
            checks=(*pre, *captures),
        )
        agent = recorder.record_run(evidence)
        return evidence, agent

    def _check_group(
        self, bound, context, workspace, view, role, repetition, checks,
        *, old_final=None, new_final=None
    ):
        result = []
        for check in checks:
            inputs = {"initial": workspace}
            if role == "pair":
                inputs = {"initial": workspace, "old_final": old_final, "new_final": new_final}
            stage = self._stage(
                bound, context, workspace, view, role, repetition,
                check, check.check_id, workspace, inputs=inputs
            )
            result.append(
                CheckCapture(check_id=check.check_id, process=stage.process, probes=())
            )
        return tuple(result)

    def _stage(
        self, bound, context, workspace, view, role, repetition, invocation,
        stage_id, seed, *, inputs=None
    ):
        if self.runner is None:
            raise RunnerError("stage runner unavailable")
        values = dict(inputs or {"initial": seed})
        values["task"] = canonical_json_bytes(bound.request.task.model_dump(mode="json"))
        values["view"] = canonical_json_bytes(view.model_dump(mode="json"))
        values["observations"] = b"{}"
        if stage_id == "executor" or getattr(invocation, "phase", None) == "pre":
            semantic = (values["initial"],)
        elif getattr(invocation, "phase", None) == "pair":
            semantic = (values["initial"], values["old_final"], values["new_final"])
        else:
            semantic = (values["initial"], values.get("current", workspace))
        digests = tuple(
            value.snapshot.digest_value() if isinstance(value, FrozenTree)
            else _digest(value)
            for value in semantic
        )
        subject = stage_subject(bound, context, role, repetition, stage_id, digests)
        return self.runner.run_stage(
            subject, invocation, bound.artifacts, values, workspace=workspace
        )

    @staticmethod
    def verify_outcome(outcome: TwinOutcome, *, operation_id: str) -> None:
        if (
            type(outcome) is not TwinOutcome
            or outcome.manifest.operation_id != operation_id
            or not outcome.valid
        ):
            raise RunnerError("twin outcome rejected")
