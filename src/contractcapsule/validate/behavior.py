"""Request-scoped behavioral evaluation of authenticated host records."""

import json
from dataclasses import dataclass
from typing import Any

from contractcapsule.models.core import ReplacementContract
from contractcapsule.validate.journal import RecordError, RecordJournal, RecordVerifier
from contractcapsule.validate.models import BoundExecution, CheckBinding
from contractcapsule.validate.run_models import (
    AgentRun,
    CheckCapture,
    CheckTrace,
    CompletedRunEvidence,
    ContractReport,
    Count,
    DifferentialReport,
    EvaluationContext,
    PairEvidence,
    ProcessCapture,
    RepetitionReport,
    RunEvidence,
    StageRole,
    evaluation_scope,
    identity,
    run_subject,
    stage_subject,
)
from contractcapsule.validate.snapshots import (
    scope_violations,
    tree_delta,
    validate_snapshot,
)


@dataclass(frozen=True)
class HostRunRecorder:
    bound: BoundExecution
    context: EvaluationContext
    journal: RecordJournal

    def record_run(self, evidence: RunEvidence) -> AgentRun:
        record = self.journal.append(
            kind="run",
            scope=evaluation_scope(self.bound),
            subject=run_subject(
                self.bound, self.context, evidence.role, evidence.repetition
            ),
            payload=evidence.payload_bytes(),
        )
        return AgentRun(
            role=evidence.role, repetition=evidence.repetition, record=record
        )

    def record_pair(
        self, old: AgentRun, new: AgentRun, evidence: PairEvidence
    ) -> tuple[AgentRun, AgentRun]:
        reference = self.journal.append(
            kind="pair",
            scope=evaluation_scope(self.bound),
            subject=run_subject(self.bound, self.context, "pair", evidence.repetition),
            payload=evidence.payload_bytes(),
        )
        return old.model_copy(update={"pair_record": reference}), new.model_copy(
            update={"pair_record": reference}
        )


@dataclass(frozen=True)
class BehaviorService:
    bound: BoundExecution
    context: EvaluationContext
    verifier: RecordVerifier
    journal: RecordJournal

    @property
    def scope(self) -> str:
        return evaluation_scope(self.bound)

    def subject(self, role: StageRole, repetition: int) -> str:
        return run_subject(self.bound, self.context, role, repetition)

    def compare_runs(
        self, old: AgentRun, new: AgentRun, contract: ReplacementContract
    ) -> DifferentialReport:
        old_report = self.evaluate_contract(old, contract)
        new_report = self.evaluate_contract(new, contract)
        blockers = list(old_report.blockers + new_report.blockers)
        traces: tuple[CheckTrace, ...] = ()
        deltas: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] = ((), (), ())
        try:
            self._contract(contract)
            old_evidence, new_evidence = self._pair_runs(old, new)
            deltas = (
                tree_delta(self.context.initial, old_evidence.final),
                tree_delta(self.context.initial, new_evidence.final),
                tree_delta(old_evidence.final, new_evidence.final),
            )
            if any(
                scope_violations(
                    d, contract.allowed_scope, contract.forbidden_spillover
                )
                for d in deltas[:2]
            ):
                blockers.append("SCOPE_VIOLATION")
            self._cross_preconditions(old_evidence, new_evidence)
            traces = self._pair_traces(old, new, old_evidence, new_evidence)
            blockers.extend(_trace_blockers(traces))
        except Exception:  # noqa: BLE001 - fail closed without private exception data.
            blockers.append("INVALID_PAIR_RECORD")
        report = DifferentialReport(
            valid=not blockers,
            blockers=tuple(sorted(set(blockers))),
            old=old,
            new=new,
            old_report=old_report,
            new_report=new_report,
            traces=traces,
            initial_to_old=deltas[0],
            initial_to_new=deltas[1],
            old_to_new=deltas[2],
        )
        return self._persist(report)

    def evaluate_repetitions(
        self, pairs: tuple[DifferentialReport, ...]
    ) -> RepetitionReport:
        blockers = []
        try:
            for pair in pairs:
                self.verify_report(pair)
            indices = [p.old.repetition for p in pairs]
            if sorted(indices) != list(range(self.bound.profile.repetitions)):
                raise RecordError("record rejected")
            if not all(p.valid for p in pairs):
                blockers.append("REPETITION_FAILED")
            fingerprints = {_outcome(p) for p in pairs}
            if len(fingerprints) != 1:
                blockers.append("UNSTABLE_TWIN_RUN")
        except Exception:  # noqa: BLE001 - untrusted report transport fails closed.
            blockers.append("INVALID_REPEAT_GROUP")
        return self._persist(
            RepetitionReport(valid=not blockers, blockers=tuple(blockers), pairs=pairs)
        )

    def _pair_runs(
        self, old: AgentRun, new: AgentRun
    ) -> tuple[CompletedRunEvidence, CompletedRunEvidence]:
        if (
            old.role != "old"
            or new.role != "new"
            or old.repetition != new.repetition
            or old.pair_record is None
            or old.pair_record != new.pair_record
        ):
            raise RecordError("record rejected")
        return self._read_run(old), self._read_run(new)

    def _cross_preconditions(
        self, old: CompletedRunEvidence, new: CompletedRunEvidence
    ) -> None:
        pre_ids = {c.check_id for c in self.bound.profile.checks if c.phase == "pre"}
        end = max(
            (
                c.process.finished_ns
                for run in (old, new)
                for c in run.checks
                if c.check_id in pre_ids
            ),
            default=0,
        )
        if end > min(old.executor.started_ns, new.executor.started_ns):
            raise RecordError("record rejected")

    def _pair_traces(
        self,
        old: AgentRun,
        new: AgentRun,
        old_evidence: CompletedRunEvidence,
        new_evidence: CompletedRunEvidence,
    ) -> tuple[CheckTrace, ...]:
        payload = self.verifier.verify(
            new.pair_record,
            kind="pair",
            scope=self.scope,
            subject=self.subject("pair", old.repetition),
        )
        evidence = PairEvidence.model_validate_json(payload)
        if (
            evidence.payload_bytes() != payload
            or evidence.old_record != old.record
            or evidence.new_record != new.record
            or evidence.repetition != old.repetition
        ):
            raise RecordError("record rejected")
        checks = tuple(c for c in self.bound.profile.checks if c.phase == "pair")
        if not checks:
            raise RecordError("record rejected")
        _membership(evidence.checks, tuple(c.check_id for c in checks))
        inputs = (
            self.context.initial.digest_value(),
            old_evidence.final.digest_value(),
            new_evidence.final.digest_value(),
            identity(old.record.model_dump(mode="json")),
            identity(new.record.model_dump(mode="json")),
        )
        earliest = max(
            c.process.finished_ns
            for r in (old_evidence, new_evidence)
            for c in r.checks
        )
        result = []
        for check, capture in zip(checks, evidence.checks, strict=True):
            if (
                check.check_id != capture.check_id
                or capture.process.started_ns < earliest
            ):
                raise RecordError("record rejected")
            self._check_capture(
                check, capture, "pair", old.repetition, inputs, earliest
            )
            result.append(
                CheckTrace(
                    check_id=check.check_id,
                    role=check.role,
                    observation=_observation(capture.process.stdout, check.check_id),
                    expected=True,
                    valid=True,
                )
            )
        return tuple(result)

    def evaluate_contract(
        self, run: AgentRun, contract: ReplacementContract
    ) -> ContractReport:
        traces: tuple[CheckTrace, ...] = ()
        blockers: list[str] = []
        try:
            self._contract(contract)
            evidence = self._read_run(run)
            traces = self._run_traces(evidence)
            blockers.extend(_trace_blockers(traces))
        except Exception:  # noqa: BLE001 - untrusted evidence never becomes a pass.
            blockers.append("INVALID_RUN_RECORD")
        report = ContractReport(
            valid=not blockers,
            blockers=tuple(sorted(set(blockers))),
            run=run,
            ter=_count(traces, "target"),
            pip=_count(traces, "invariant"),
            bsr=_count(traces, "spillover"),
            traces=traces,
        )
        return self._persist(report)

    def _contract(self, contract: ReplacementContract) -> None:
        if (
            type(contract) is not ReplacementContract
            or contract != self.bound.request.new.capsule.replacement_contract
        ):
            raise RecordError("record rejected")
        for role in ("target", "invariant", "spillover"):
            if not any(c.role == role for c in self.bound.profile.checks):
                raise RecordError("record rejected")

    def _read_run(self, run: AgentRun) -> CompletedRunEvidence:
        if (
            type(run) is not AgentRun
            or not 0 <= run.repetition < self.bound.profile.repetitions
        ):
            raise RecordError("record rejected")
        payload = self.verifier.verify(
            run.record,
            kind="run",
            scope=evaluation_scope(self.bound),
            subject=run_subject(self.bound, self.context, run.role, run.repetition),
        )
        evidence = CompletedRunEvidence.model_validate_json(payload)
        if evidence.payload_bytes() != payload or (
            evidence.role,
            evidence.repetition,
        ) != (run.role, run.repetition):
            raise RecordError("record rejected")
        containers = _containers(evidence.checks) + [evidence.executor.container_id]
        if len(containers) != len(set(containers)):
            raise RecordError("record rejected")
        validate_snapshot(self.context.initial, self.bound.profile.runner)
        validate_snapshot(evidence.final, self.bound.profile.runner)
        return evidence

    def _process(
        self, capture: ProcessCapture, expected: str, *, probe: bool = False
    ) -> None:
        runner = self.bound.profile.runner
        exit_valid = capture.exit_code is not None and (
            capture.exit_code >= 0 if probe else capture.exit_code == 0
        )
        if (
            capture.subject != expected
            or not exit_valid
            or not capture.terminated
            or capture.timed_out
            or capture.output_limited
            or capture.finished_ns < capture.started_ns
            or capture.finished_ns - capture.started_ns
            > runner.timeout_seconds * 1_000_000_000
            or len(capture.stdout) > runner.stdout_limit_bytes
            or len(capture.stderr) > runner.stderr_limit_bytes
        ):
            raise RecordError("record rejected")

    def _check_capture(
        self,
        check: CheckBinding,
        capture: CheckCapture,
        role: StageRole,
        repetition: int,
        inputs: tuple[str, ...],
        earliest: int,
    ) -> None:
        if len(capture.probes) != len(check.subject_probes):
            raise RecordError("record rejected")
        states = {"initial": inputs[0], "current": inputs[-1]}
        if role == "pair":
            states.update(old_final=inputs[1], new_final=inputs[2])
        containers = [capture.process.container_id]
        for binding, observed in zip(check.subject_probes, capture.probes, strict=True):
            expected = stage_subject(
                self.bound,
                self.context,
                role,
                repetition,
                binding.probe_id,
                (states[binding.input_state],),
            )
            self._process(observed, expected, probe=True)
            if (
                observed.started_ns < earliest
                or observed.finished_ns > capture.process.started_ns
            ):
                raise RecordError("record rejected")
            containers.append(observed.container_id)
        if (
            len(containers) != len(set(containers))
            or capture.process.started_ns < earliest
        ):
            raise RecordError("record rejected")
        expected = stage_subject(
            self.bound,
            self.context,
            role,
            repetition,
            check.check_id,
            inputs,
            capture.probes,
        )
        self._process(capture.process, expected)

    def _run_traces(self, evidence: CompletedRunEvidence) -> tuple[CheckTrace, ...]:
        inputs = (self.context.initial.digest_value(), evidence.final.digest_value())
        expected = stage_subject(
            self.bound,
            self.context,
            evidence.role,
            evidence.repetition,
            "executor",
            inputs[:1],
        )
        self._process(evidence.executor, expected)
        if evidence.snapshot_ns < evidence.executor.finished_ns:
            raise RecordError("record rejected")
        checks = tuple(c for c in self.bound.profile.checks if c.phase != "pair")
        _membership(evidence.checks, tuple(c.check_id for c in checks))
        captured = {c.check_id: c for c in evidence.checks}
        traces = []
        for check in checks:
            capture = captured[check.check_id]
            check_inputs = inputs[:1] if check.phase == "pre" else inputs
            expected_value = (
                check.old_expected if evidence.role == "old" else check.new_expected
            )
            valid = False
            observation = None
            try:
                earliest = 0 if check.phase == "pre" else evidence.snapshot_ns
                self._check_capture(
                    check,
                    capture,
                    evidence.role,
                    evidence.repetition,
                    check_inputs,
                    earliest,
                )
                if (
                    check.phase == "pre"
                    and capture.process.finished_ns > evidence.executor.started_ns
                ):
                    raise RecordError("record rejected")
                if (
                    check.phase == "post"
                    and capture.process.started_ns < evidence.snapshot_ns
                ):
                    raise RecordError("record rejected")
                observation = _observation(capture.process.stdout, check.check_id)
                valid = True
            except Exception:  # noqa: BLE001 - retain an invalid trace, never default false.
                valid = False
            traces.append(
                CheckTrace(
                    check_id=check.check_id,
                    role=check.role,
                    observation=observation,
                    expected=bool(expected_value),
                    valid=valid,
                )
            )
        return tuple(traces)

    def _report_subject(
        self, report: ContractReport | DifferentialReport | RepetitionReport
    ) -> str:
        members: list[Any]
        if isinstance(report, RepetitionReport):
            members = [self._report_subject(p) for p in report.pairs]
        elif isinstance(report, DifferentialReport):
            members = [
                report.old.model_dump(mode="json"),
                report.new.model_dump(mode="json"),
            ]
        else:
            members = [report.run.model_dump(mode="json")]
        return identity(
            {
                "binding": self.subject("pair", 0),
                "kind": report.kind,
                "members": members,
            }
        )

    def _persist[T: (ContractReport, DifferentialReport, RepetitionReport)](
        self, report: T
    ) -> T:
        try:
            reference = self.journal.append(
                kind=report.kind,
                scope=evaluation_scope(self.bound),
                subject=self._report_subject(report),
                payload=report.payload_bytes(),
            )
            return report.model_copy(update={"record": reference})
        except Exception:  # noqa: BLE001 - journal failure is a critical blocker.
            return report.model_copy(
                update={
                    "valid": False,
                    "blockers": (*report.blockers, "REPORT_PERSISTENCE_FAILED"),
                }
            )

    def verify_report(
        self, report: ContractReport | DifferentialReport | RepetitionReport
    ) -> None:
        try:
            if type(report) not in {
                ContractReport,
                DifferentialReport,
                RepetitionReport,
            }:
                raise RecordError("record rejected")
            payload = self.verifier.verify(
                report.record,
                kind=report.kind,
                scope=evaluation_scope(self.bound),
                subject=self._report_subject(report),
            )
            if payload != report.payload_bytes():
                raise RecordError("record rejected")
            if isinstance(report, ContractReport):
                self._read_run(report.run)
            elif isinstance(report, DifferentialReport):
                self.verify_report(report.old_report)
                self.verify_report(report.new_report)
                old, new = self._pair_runs(report.old, report.new)
                self._pair_traces(report.old, report.new, old, new)
            else:
                for pair in report.pairs:
                    self.verify_report(pair)
        except Exception:  # noqa: BLE001 - expose only the safe rejection boundary.
            raise RecordError("record rejected") from None


def _count(traces: tuple[CheckTrace, ...], role: str) -> Count:
    relevant = [t for t in traces if t.role == role]
    return Count(
        numerator=sum(t.valid and t.observation is True for t in relevant),
        denominator=len(relevant),
    )


def _membership(captures: tuple[CheckCapture, ...], expected: tuple[str, ...]) -> None:
    ids = [c.check_id for c in captures]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise RecordError("record rejected")


def _containers(captures: tuple[CheckCapture, ...]) -> list[str]:
    return [
        process.container_id
        for capture in captures
        for process in (capture.process, *capture.probes)
    ]


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecordError("record rejected")
        result[key] = value
    return result


def _observation(raw: bytes, check_id: str) -> bool:
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json)
    if (
        type(value) is not dict
        or set(value) != {"check_id", "observation"}
        or value["check_id"] != check_id
        or type(value["observation"]) is not bool
    ):
        raise RecordError("record rejected")
    return value["observation"]


def _trace_blockers(traces: tuple[CheckTrace, ...]) -> tuple[str, ...]:
    codes = {
        "target": "TARGET_FAILED",
        "invariant": "INVARIANT_FAILED",
        "spillover": "SPILLOVER_TRIGGERED",
    }
    return tuple(
        "INVALID_CHECK_RECORD"
        if not trace.valid
        else codes.get(trace.role, "GUARD_FAILED")
        for trace in traces
        if not trace.valid or trace.observation is not trace.expected
    )


def _outcome(pair: DifferentialReport) -> str:
    return identity(
        {
            "valid": pair.valid,
            "blockers": pair.blockers,
            "traces": [
                [t.model_dump(mode="json") for t in traces]
                for traces in (
                    pair.old_report.traces,
                    pair.new_report.traces,
                    pair.traces,
                )
            ],
        }
    )
