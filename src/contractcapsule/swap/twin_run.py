"""Trusted host composition of complete authenticated Docker twin attempts."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.models.view import CompiledView
from contractcapsule.storage.registry import Registry
from contractcapsule.swap.attempts import AttemptStore
from contractcapsule.swap.docker_runner import DockerRunner
from contractcapsule.swap.source import git_tree
from contractcapsule.swap.trees import RunnerError
from contractcapsule.swap.twin_models import (
    AdmissionCheck,
    AttemptManifest,
    TwinFailure,
    TwinOutcome,
)
from contractcapsule.swap.twin_stages import PairRunner
from contractcapsule.swap.twin_validation import (
    ExecutionPolicy,
    admission,
    check_requests,
    compile_lock,
    service_configuration,
    utc_stamp,
)
from contractcapsule.validate.approvals import Approval, ApprovalVerifier
from contractcapsule.validate.artifacts import LocalArtifactResolver
from contractcapsule.validate.behavior import BehaviorService, HostRunRecorder
from contractcapsule.validate.contracts import (
    execution_subject,
    parse_execution_contract,
)
from contractcapsule.validate.integrity import ValidationService
from contractcapsule.validate.journal import RecordJournal
from contractcapsule.validate.models import BoundExecution, ReplacementRequest
from contractcapsule.validate.run_models import (
    EvaluationContext,
    RepetitionReport,
    digest_bytes,
    evaluation_scope,
    identity,
)


@dataclass(frozen=True)
class TwinRunner:
    request: ReplacementRequest
    registry: Registry
    artifacts: LocalArtifactResolver
    old_validation: ValidationService
    new_validation: ValidationService
    runner: DockerRunner
    approval_verifier: ApprovalVerifier
    execution_policy: ExecutionPolicy
    journal: RecordJournal
    attempt_store: AttemptStore
    repositories: Mapping[str, Path]
    clock: Callable[[], datetime]

    @property
    def services(self) -> tuple[ValidationService, ValidationService]:
        return self.old_validation, self.new_validation

    def _bind(self, approval: Approval) -> tuple[BoundExecution, bytes]:
        bound = parse_execution_contract(self.request, self.registry, self.artifacts)
        self.approval_verifier.verify_execution(approval, bound, now=self.clock())
        self.execution_policy.check(approval)
        check_requests(bound, self.services)
        if (
            self.runner.config != bound.profile.runner
            or self.journal.registry is not self.registry
            or self.attempt_store.database_path != self.registry.database_path
        ):
            raise RunnerError("composition mismatch")
        for service in self.services:
            if (
                type(service) is not ValidationService
                or service.compiler.registry is not self.registry
                or service.artifacts is not self.artifacts
                or service.journal is not self.journal
                or service.clock is not self.clock
            ):
                raise RunnerError("validation composition mismatch")
        if self.request.source_repository not in self.repositories:
            raise RunnerError("source mapping unavailable")
        payload = canonical_json_bytes(
            {
                "domain": "ccs-m5-twin-binding/1",
                "execution": execution_subject(bound),
                "profile": bound.profile.model_dump(mode="json"),
                "compile_requests": [compile_lock(s) for s in self.services],
                "configuration": [service_configuration(s) for s in self.services],
                "packages": {
                    key: str(path) for key, path in self.artifacts.packages.items()
                },
                "source_root": str(self.repositories[self.request.source_repository]),
                "execution_policy": self.execution_policy.configuration_digest,
                "approval": approval.model_dump(mode="json"),
            }
        )
        return bound, payload

    def _attempt_key(self, bound: BoundExecution) -> str:
        return identity(
            {
                "scope": evaluation_scope(bound),
                "operation_id": self.request.operation_id,
            }
        )

    def run(self, approval: Approval) -> TwinOutcome | TwinFailure:
        try:
            bound, binding = self._bind(approval)
            row = self.attempt_store.reserve(
                self._attempt_key(bound), digest_bytes(binding)
            )
            if row.state == "COMPLETE":
                if row.manifest is None:
                    raise RunnerError("attempt outcome missing")
                outcome = TwinOutcome.model_validate_json(row.manifest)
                self.verify_outcome(outcome)
                return outcome
            outcome = self._execute(bound, binding, approval)
            self.verify_outcome(outcome)
            return outcome
        except Exception:  # noqa: BLE001 - current authority failure withholds prior evidence.
            return TwinFailure(
                operation_id=self.request.operation_id, code="TWIN_RUN_REJECTED"
            )

    def _execute(
        self, bound: BoundExecution, binding: bytes, approval: Approval
    ) -> TwinOutcome:
        admissions: list[AdmissionCheck] = []
        context = None
        repetitions = None
        stages: PairRunner | None = None
        blockers: list[str] = []
        try:
            views = tuple(s.compiler.compile_view(s.request) for s in self.services)
            old_view, new_view = views
            self._fresh(bound, binding, approval, (old_view, new_view), admissions)
            source = git_tree(
                self.repositories[self.request.source_repository],
                self.request.source_commit,
                bound.profile.runner,
            )
            context = EvaluationContext(
                initial=source.snapshot,
                old_view_digest=identity(old_view.model_dump(mode="json")),
                new_view_digest=identity(new_view.model_dump(mode="json")),
                approval_digest=identity(approval.model_dump(mode="json")),
                synthetic=approval.synthetic,
            )
            recorder = HostRunRecorder(bound, context, self.journal)
            behavior = BehaviorService(
                bound, context, self.journal.verifier(), self.journal
            )
            stages = PairRunner(
                bound,
                context,
                source,
                (old_view, new_view),
                self.runner,
                recorder,
                behavior,
                lambda: self._fresh(
                    bound, binding, approval, (old_view, new_view), admissions
                ),
            )
            pairs = []
            for index in range(bound.profile.repetitions):
                pairs.append(stages.pair(index))
                if stages.uncertain:
                    break
            repetitions = behavior.evaluate_repetitions(tuple(pairs))
            blockers.extend(stages.blockers)
            blockers.extend(repetitions.blockers)
            self._fresh(bound, binding, approval, (old_view, new_view), admissions)
        except Exception:  # noqa: BLE001 - retain authorized failures, never rerun them.
            blockers.append("TWIN_EXECUTION_ABORTED")
        return self._finish(
            bound, binding, approval, context, repetitions, stages, admissions, blockers
        )

    def _fresh(
        self,
        bound: BoundExecution,
        binding: bytes,
        approval: Approval,
        views: tuple[CompiledView, CompiledView],
        admissions: list[AdmissionCheck],
    ) -> None:
        current, payload = self._bind(approval)
        if payload != binding or execution_subject(current) != execution_subject(bound):
            raise RunnerError("current composition changed")
        admissions.append(
            admission(
                current,
                approval,
                self.approval_verifier,
                self.execution_policy,
                self.clock(),
                self.services,
                views,
            )
        )

    def _finish(
        self,
        bound: BoundExecution,
        binding: bytes,
        approval: Approval,
        context: EvaluationContext | None,
        repetitions: RepetitionReport | None,
        stages: PairRunner | None,
        admissions: list[AdmissionCheck],
        blockers: list[str],
    ) -> TwinOutcome:
        state = "FAILED"
        if stages and stages.uncertain:
            state = "UNCERTAIN"
        elif repetitions and repetitions.valid and not blockers:
            state = "COMPLETE"
        manifest = AttemptManifest.model_validate(
            {
                "operation_id": self.request.operation_id,
                "scope": evaluation_scope(bound),
                "binding_digest": digest_bytes(binding),
                "binding_payload": binding,
                "approval_digest": identity(approval.model_dump(mode="json")),
                "source_commit": self.request.source_commit,
                "context": context,
                "repetitions": tuple(range(bound.profile.repetitions)),
                "repetition_record": repetitions.record if repetitions else None,
                "admissions": tuple(admissions),
                "stages": tuple(stages.stages) if stages else (),
                "created_at": utc_stamp(self.clock()),
                "state": state,
                "blockers": tuple(sorted(set(blockers))),
            }
        )
        # The record payload covers the complete outcome, including failure groups.
        payload = canonical_json_bytes(
            {
                "manifest": manifest.model_dump(mode="json"),
                "approval": approval.model_dump(mode="json"),
                "repetitions": repetitions.model_dump(mode="json")
                if repetitions
                else None,
            }
        )
        ref = self.journal.append(
            kind="twin",
            scope=manifest.scope,
            subject=manifest.binding_digest,
            payload=payload,
        )
        outcome = TwinOutcome(
            manifest=manifest, approval=approval, repetitions=repetitions, record=ref
        )
        self.attempt_store.complete(
            self._attempt_key(bound), outcome.model_dump_json().encode()
        )
        return outcome

    def verify_outcome(self, outcome: TwinOutcome) -> None:
        """Verify exact durable outcome against this trusted composition and current authority.

        Authentication of a retained failure never turns it into a valid group.
        Current denial raises without returning old private identifiers.
        """
        from contractcapsule.swap.twin_verify import verify_records

        if type(outcome) is not TwinOutcome:
            raise RunnerError("twin outcome rejected")
        bound, binding = self._bind(outcome.approval)
        manifest = outcome.manifest
        row = self.attempt_store.get(self._attempt_key(bound))
        if (
            row is None
            or row.state != "COMPLETE"
            or row.manifest != outcome.model_dump_json().encode()
            or row.binding_digest != digest_bytes(binding)
        ):
            raise RunnerError("twin attempt rejected")
        if (
            manifest.binding_payload != binding
            or manifest.binding_digest != digest_bytes(binding)
            or manifest.operation_id != self.request.operation_id
        ):
            raise RunnerError("twin binding rejected")
        payload = self.journal.verifier().verify(
            outcome.record,
            kind="twin",
            scope=evaluation_scope(bound),
            subject=digest_bytes(binding),
        )
        if payload != outcome.payload_bytes():
            raise RunnerError("twin payload rejected")
        views = tuple(s.compiler.compile_view(s.request) for s in self.services)
        old_view, new_view = views
        self._fresh(bound, binding, outcome.approval, (old_view, new_view), [])
        if manifest.context is not None:
            source = git_tree(
                self.repositories[self.request.source_repository],
                self.request.source_commit,
                bound.profile.runner,
            )
            expected = EvaluationContext(
                initial=source.snapshot,
                old_view_digest=identity(old_view.model_dump(mode="json")),
                new_view_digest=identity(new_view.model_dump(mode="json")),
                approval_digest=identity(outcome.approval.model_dump(mode="json")),
                synthetic=outcome.approval.synthetic,
            )
            if manifest.context != expected:
                raise RunnerError("twin context rejected")
        verify_records(outcome, bound, self.journal)
