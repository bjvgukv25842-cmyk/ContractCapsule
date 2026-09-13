"""Verify all stored links, including honestly incomplete negative Task3 groups."""

from contractcapsule.swap.trees import RunnerError
from contractcapsule.swap.twin_models import TwinOutcome
from contractcapsule.validate.behavior import BehaviorService
from contractcapsule.validate.journal import RecordJournal
from contractcapsule.validate.models import BoundExecution
from contractcapsule.validate.run_models import (
    ContractReport,
    DifferentialReport,
    EvaluationContext,
    PairEvidence,
    RepetitionReport,
    RunEvidence,
    evaluation_scope,
    identity,
    run_subject,
)


def _subject(report, bound, context):
    if type(report) is RepetitionReport:
        members = [_subject(p, bound, context) for p in report.pairs]
    elif type(report) is DifferentialReport:
        members = [
            report.old.model_dump(mode="json"),
            report.new.model_dump(mode="json"),
        ]
    else:
        members = [report.run.model_dump(mode="json")]
    return identity(
        {
            "binding": run_subject(bound, context, "pair", 0),
            "kind": report.kind,
            "members": members,
        }
    )


def _report(
    report: ContractReport | DifferentialReport | RepetitionReport,
    bound: BoundExecution,
    context: EvaluationContext,
    journal: RecordJournal,
) -> None:
    verifier = journal.verifier()
    payload = verifier.verify(
        report.record,
        kind=report.kind,
        scope=evaluation_scope(bound),
        subject=_subject(report, bound, context),
    )
    if payload != report.payload_bytes():
        raise RunnerError("behavioral report payload rejected")
    if type(report) is RepetitionReport:
        for pair in report.pairs:
            _report(pair, bound, context, journal)
    elif type(report) is DifferentialReport:
        _report(report.old_report, bound, context, journal)
        _report(report.new_report, bound, context, journal)
        if (
            report.old_report.run != report.old
            or report.new_report.run != report.new
            or report.old.pair_record != report.new.pair_record
        ):
            raise RunnerError("pair linkage rejected")
        payload = verifier.verify(
            report.old.pair_record,
            kind="pair",
            scope=evaluation_scope(bound),
            subject=run_subject(bound, context, "pair", report.old.repetition),
        )
        evidence_pair = PairEvidence.model_validate_json(payload)
        if (
            evidence_pair.payload_bytes() != payload
            or evidence_pair.old_record != report.old.record
            or evidence_pair.new_record != report.new.record
            or evidence_pair.repetition != report.old.repetition
        ):
            raise RunnerError("pair evidence rejected")
    elif isinstance(report, ContractReport):
        run = report.run
        payload = verifier.verify(
            run.record,
            kind="run",
            scope=evaluation_scope(bound),
            subject=run_subject(bound, context, run.role, run.repetition),
        )
        evidence = RunEvidence.model_validate_json(payload)
        if (
            evidence.payload_bytes() != payload
            or evidence.role != run.role
            or evidence.repetition != run.repetition
        ):
            raise RunnerError("run evidence rejected")


def verify_records(
    outcome: TwinOutcome, bound: BoundExecution, journal: RecordJournal
) -> None:
    manifest = outcome.manifest
    for admission in manifest.admissions:
        for report in admission.reports:
            if report.scope_digest is None or report.subject_digest is None:
                raise RunnerError("admission identity absent")
            payload = journal.verifier().verify(
                report.record,
                kind=report.kind,
                scope=report.scope_digest,
                subject=report.subject_digest,
            )
            if payload != report.payload_bytes():
                raise RunnerError("admission record rejected")
    if outcome.repetitions is None:
        if outcome.valid or manifest.repetition_record is not None:
            raise RunnerError("missing repetition report")
        return
    if (
        manifest.context is None
        or manifest.repetition_record != outcome.repetitions.record
    ):
        raise RunnerError("repetition linkage rejected")
    _report(outcome.repetitions, bound, manifest.context, journal)
    if outcome.valid:
        service = BehaviorService(bound, manifest.context, journal.verifier(), journal)
        service.verify_report(outcome.repetitions)
        if (
            manifest.blockers
            or tuple(p.old.repetition for p in outcome.repetitions.pairs)
            != manifest.repetitions
        ):
            raise RunnerError("incomplete valid group")
