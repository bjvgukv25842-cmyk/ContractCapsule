"""Authenticated host-recorded SYNTHETIC observations, never process evidence."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from contractcapsule.validate.behavior import BehaviorService, HostRunRecorder
from contractcapsule.validate.journal import RecordError, RecordJournal
from contractcapsule.validate.run_models import (
    CheckCapture,
    EvaluationContext,
    PairEvidence,
    ProcessCapture,
    RunEvidence,
    Snapshot,
    TreeEntry,
    identity,
    stage_subject,
)
from tests.m5_helpers import M5Fixture, digest
from tests.unit.test_execution_contract import parse


def tree(text: str = "initial") -> Snapshot:
    return Snapshot(
        entries=(
            TreeEntry(path=".", kind="directory", mode=0o755),
            TreeEntry(path="src", kind="directory", mode=0o755),
            TreeEntry(
                path="src/main.py",
                kind="file",
                mode=0o644,
                digest=digest(text.encode()),
                size=len(text),
            ),
        )
    )


class Harness:
    def __init__(self, root: Path, amend=None):
        self.fixture = M5Fixture.create(root, amend)
        self.bound = parse(self.fixture)
        self.context = EvaluationContext(
            initial=tree(),
            old_view_digest=digest(b"old view"),
            new_view_digest=digest(b"new view"),
            approval_digest=digest(b"synthetic approval"),
            synthetic=True,
        )
        self.journal = RecordJournal(
            self.fixture.base.registry, b"synthetic-result-key-32-bytes-long"
        )
        self.writer = HostRunRecorder(self.bound, self.context, self.journal)
        self.service = BehaviorService(
            self.bound, self.context, self.journal.verifier(), self.journal
        )
        self.contract = self.bound.request.new.capsule.replacement_contract

    def evidence(self, role="new", repetition=0, *, changes=None, final=None):
        final = final or tree("new" if role == "new" else "old")
        inputs = (self.context.initial.digest_value(), final.digest_value())
        checks = []
        for check in self.bound.profile.checks:
            if check.phase == "pair":
                continue
            observed = getattr(check, role + "_expected")
            if changes and check.check_id in changes:
                observed = changes[check.check_id]
            check_inputs = inputs[:1] if check.phase == "pre" else inputs
            start = 10 if check.phase == "pre" else 50
            process = ProcessCapture(
                subject=stage_subject(
                    self.bound,
                    self.context,
                    role,
                    repetition,
                    check.check_id,
                    check_inputs,
                ),
                container_id="synthetic-" + role + "-" + check.check_id,
                started_ns=start,
                finished_ns=start + 1,
                exit_code=0,
                terminated=True,
                timed_out=False,
                output_limited=False,
                stdout=json.dumps(
                    {"check_id": check.check_id, "observation": observed}
                ).encode(),
                stderr=b"",
            )
            checks.append(
                CheckCapture(check_id=check.check_id, process=process, probes=())
            )
        executor = ProcessCapture(
            subject=stage_subject(
                self.bound, self.context, role, repetition, "executor", inputs[:1]
            ),
            container_id="synthetic-" + role + "-executor",
            started_ns=20,
            finished_ns=30,
            exit_code=0,
            terminated=True,
            timed_out=False,
            output_limited=False,
            stdout=b"",
            stderr=b"",
        )
        return RunEvidence(
            role=role,
            repetition=repetition,
            final=final,
            snapshot_ns=40,
            executor=executor,
            checks=tuple(checks),
        )

    def pair(
        self,
        *,
        repetition=0,
        old_final=None,
        new_final=None,
        changes=None,
        pair_value=True,
        swap_operands=False,
    ):
        old_evidence = self.evidence("old", repetition, final=old_final)
        new_evidence = self.evidence(
            "new", repetition, final=new_final, changes=changes
        )
        old = self.writer.record_run(old_evidence)
        new = self.writer.record_run(new_evidence)
        inputs = (
            self.context.initial.digest_value(),
            old_evidence.final.digest_value(),
            new_evidence.final.digest_value(),
            identity(old.record.model_dump(mode="json")),
            identity(new.record.model_dump(mode="json")),
        )
        if swap_operands:
            inputs = (inputs[0], inputs[2], inputs[1], inputs[4], inputs[3])
        process = ProcessCapture(
            subject=stage_subject(
                self.bound, self.context, "pair", repetition, "differential", inputs
            ),
            container_id="synthetic-pair",
            started_ns=60,
            finished_ns=61,
            exit_code=0,
            terminated=True,
            timed_out=False,
            output_limited=False,
            stdout=json.dumps(
                {"check_id": "differential", "observation": pair_value}
            ).encode(),
            stderr=b"",
        )
        pair = PairEvidence(
            repetition=repetition,
            old_record=old.record,
            new_record=new.record,
            checks=(CheckCapture(check_id="differential", process=process, probes=()),),
        )
        return self.writer.record_pair(old, new, pair)


def test_explicit_old_target_and_three_independent_counts(tmp_path: Path):
    h = Harness(tmp_path)
    old = h.writer.record_run(h.evidence("old"))
    new = h.writer.record_run(h.evidence())
    old_report = h.service.evaluate_contract(old, h.contract)
    report = h.service.evaluate_contract(new, h.contract)
    assert old_report.valid
    assert old_report.ter.numerator == 0
    assert report.valid
    assert (report.ter.numerator, report.ter.denominator) == (1, 1)
    assert (report.pip.numerator, report.pip.denominator) == (1, 1)
    assert (report.bsr.numerator, report.bsr.denominator) == (0, 1)
    h.service.verify_report(report)


@pytest.mark.parametrize(
    "name,value,code",
    [
        ("target", False, "TARGET_FAILED"),
        ("invariant", False, "INVARIANT_FAILED"),
        ("spillover", True, "SPILLOVER_TRIGGERED"),
        ("static", False, "GUARD_FAILED"),
        ("precondition", False, "GUARD_FAILED"),
    ],
)
def test_each_failure_is_retained_and_blocks(tmp_path: Path, name, value, code):
    h = Harness(tmp_path)
    run = h.writer.record_run(h.evidence(changes={name: value}))
    report = h.service.evaluate_contract(run, h.contract)
    assert not report.valid
    assert code in report.blockers
    assert next(t for t in report.traces if t.check_id == name).observation is value
    h.service.verify_report(report)


def test_forged_report_counters_do_not_authenticate(tmp_path: Path):
    h = Harness(tmp_path)
    report = h.service.evaluate_contract(h.writer.record_run(h.evidence()), h.contract)
    forged = report.model_copy(
        update={"ter": report.ter.model_copy(update={"numerator": 100})}
    )
    with pytest.raises(RecordError):
        h.service.verify_report(forged)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "extra",
        "skipped",
        "timeout",
        "abnormal",
        "malformed",
        "wrong_id",
        "non_bool",
        "extra_json",
        "duplicate_key",
        "wrong_input",
        "wrong_phase",
        "unterminated",
    ],
)
def test_invalid_check_records_never_become_false_pass(tmp_path: Path, fault):
    h = Harness(tmp_path)
    evidence = h.evidence()
    checks = list(evidence.checks)
    index = next(i for i, c in enumerate(checks) if c.check_id == "spillover")
    capture = checks[index]
    if fault == "missing":
        checks.pop(index)
    elif fault == "duplicate":
        checks.append(capture)
    elif fault == "extra":
        checks.append(capture.model_copy(update={"check_id": "unknown"}))
    else:
        changes = {
            "skipped": {"stdout": b'{"check_id":"spillover","skip":true}'},
            "timeout": {"timed_out": True},
            "abnormal": {"exit_code": 1},
            "malformed": {"stdout": b"not JSON"},
            "wrong_id": {"stdout": b'{"check_id":"target","observation":false}'},
            "non_bool": {"stdout": b'{"check_id":"spillover","observation":0}'},
            "extra_json": {"stdout": capture.process.stdout + capture.process.stdout},
            "duplicate_key": {
                "stdout": b'{"check_id":"spillover","observation":true,"observation":false}'
            },
            "wrong_input": {"subject": digest(b"other input")},
            "wrong_phase": {"started_ns": 0, "finished_ns": 1},
            "unterminated": {"terminated": False},
        }[fault]
        checks[index] = capture.model_copy(
            update={"process": capture.process.model_copy(update=changes)}
        )
    evidence = evidence.model_copy(update={"checks": tuple(checks)})
    report = h.service.evaluate_contract(h.writer.record_run(evidence), h.contract)
    assert not report.valid
    assert (
        "INVALID_RUN_RECORD" in report.blockers
        or "INVALID_CHECK_RECORD" in report.blockers
    )


@pytest.mark.parametrize("role", ["old", "new"])
def test_wrong_old_new_role_cannot_rebind_run(tmp_path: Path, role):
    h = Harness(tmp_path)
    run = h.writer.record_run(h.evidence(role))
    forged = run.model_copy(update={"role": "old" if role == "new" else "new"})
    assert not h.service.evaluate_contract(forged, h.contract).valid


def test_pair_has_one_observation_and_three_deltas(tmp_path: Path):
    h = Harness(tmp_path)
    old, new = h.pair()
    report = h.service.compare_runs(old, new, h.contract)
    assert report.valid
    assert len(report.traces) == 1
    assert report.traces[0].observation is True
    assert report.initial_to_old == ("src/main.py",)
    assert report.initial_to_new == ("src/main.py",)
    assert report.old_to_new == ("src/main.py",)
    h.service.verify_report(report)


@pytest.mark.parametrize(
    "fault", ["same_outside", "delete", "untracked", "mode", "directory_mode", "type"]
)
def test_both_source_relative_deltas_enforce_scope(tmp_path: Path, fault):
    h = Harness(tmp_path)
    entries = list(tree().entries)
    entries += [
        TreeEntry(path="billing", kind="directory", mode=0o755),
        TreeEntry(
            path="billing/config",
            kind="file",
            mode=0o644,
            digest=digest(b"initial"),
            size=7,
        ),
    ]
    initial = Snapshot(entries=tuple(sorted(entries, key=lambda e: e.path)))
    h.context = h.context.model_copy(update={"initial": initial})
    h.writer = HostRunRecorder(h.bound, h.context, h.journal)
    h.service = BehaviorService(h.bound, h.context, h.journal.verifier(), h.journal)
    altered = {e.path: e for e in initial.entries}
    if fault == "delete":
        del altered["billing/config"]
    elif fault == "untracked":
        altered["billing/new"] = TreeEntry(
            path="billing/new", kind="file", mode=0o644, digest=digest(b"new"), size=3
        )
    elif fault == "directory_mode":
        altered["billing"] = altered["billing"].model_copy(update={"mode": 0o700})
    elif fault == "type":
        altered["billing/config"] = TreeEntry(
            path="billing/config", kind="directory", mode=0o755
        )
    else:
        changes = {"mode": 0o755} if fault == "mode" else {"digest": digest(b"changed")}
        altered["billing/config"] = altered["billing/config"].model_copy(update=changes)
    final = Snapshot(entries=tuple(sorted(altered.values(), key=lambda e: e.path)))
    old, new = h.pair(old_final=final, new_final=final)
    report = h.service.compare_runs(old, new, h.contract)
    assert not report.valid
    assert "SCOPE_VIOLATION" in report.blockers
    assert report.old_to_new == ()
    assert report.initial_to_old and report.initial_to_new


@pytest.mark.parametrize(
    "fault", ["swapped", "false", "missing", "cross_repeat", "early"]
)
def test_pair_record_rejections(tmp_path: Path, fault):
    h = Harness(tmp_path)
    old, new = h.pair(swap_operands=fault == "swapped", pair_value=fault != "false")
    if fault == "missing":
        new = new.model_copy(update={"pair_record": None})
    if fault == "cross_repeat":
        _, new = h.pair(repetition=1)
    if fault == "early":
        raw = h.journal.verifier().verify(
            new.pair_record,
            kind="pair",
            scope=h.service.scope,
            subject=h.service.subject("pair", 0),
        )
        evidence = PairEvidence.model_validate_json(raw)
        capture = evidence.checks[0]
        capture = capture.model_copy(
            update={
                "process": capture.process.model_copy(
                    update={"started_ns": 5, "finished_ns": 6}
                )
            }
        )
        old, new = h.writer.record_pair(
            old, new, evidence.model_copy(update={"checks": (capture,)})
        )
    assert not h.service.compare_runs(old, new, h.contract).valid


def test_repetition_group_retains_mixed_negative_outcomes(tmp_path: Path):
    h = Harness(tmp_path)
    pairs_list = []
    for i in range(3):
        old, new = h.pair(repetition=i, changes={"target": i != 1})
        pairs_list.append(h.service.compare_runs(old, new, h.contract))
    pairs = tuple(pairs_list)
    report = h.service.evaluate_repetitions(pairs)
    assert not report.valid
    assert "UNSTABLE_TWIN_RUN" in report.blockers
    assert [p.new_report.ter.numerator for p in report.pairs] == [1, 0, 1]
    h.service.verify_report(report)
    assert not h.service.evaluate_repetitions((pairs[0], pairs[2])).valid
    assert not h.service.evaluate_repetitions((pairs[0], pairs[0], pairs[2])).valid


def with_probe(raw):
    check = raw["replacement_contract"]["extensions"]["x-m5-execution"]["checks"][3]
    check["subject_probes"] = [
        {
            "probe_id": "subject-target",
            "test_id": "probe",
            "artifact_ids": ["probe"],
            "argv": [],
            "input_state": "current",
        }
    ]


@pytest.mark.parametrize(
    "fault", [None, "missing", "wrong_snapshot", "late", "wrong_container", "extra"]
)
def test_declared_subject_probe_bound_to_current_snapshot(tmp_path: Path, fault):
    h = Harness(tmp_path, with_probe)
    evidence = h.evidence()
    inputs = (h.context.initial.digest_value(), evidence.final.digest_value())
    probe = ProcessCapture(
        subject=stage_subject(
            h.bound, h.context, "new", 0, "subject-target", (inputs[1],)
        ),
        container_id="synthetic-probe",
        started_ns=42,
        finished_ns=45,
        exit_code=2,
        terminated=True,
        timed_out=False,
        output_limited=False,
        stdout=b"subject data",
        stderr=b"",
    )
    # Nonzero subject exit is data for the trusted checker, not a false result.
    if fault == "wrong_snapshot":
        probe = probe.model_copy(
            update={
                "subject": stage_subject(
                    h.bound, h.context, "new", 0, "subject-target", inputs[:1]
                )
            }
        )
    if fault == "late":
        probe = probe.model_copy(update={"finished_ns": 55})
    if fault == "wrong_container":
        probe = probe.model_copy(update={"container_id": "synthetic-new-target"})
    probes = (
        () if fault == "missing" else (probe, probe) if fault == "extra" else (probe,)
    )
    captures = []
    for capture in evidence.checks:
        if capture.check_id == "target":
            process = capture.process.model_copy(
                update={
                    "subject": stage_subject(
                        h.bound, h.context, "new", 0, "target", inputs, probes
                    )
                }
            )
            capture = capture.model_copy(update={"process": process, "probes": probes})
        captures.append(capture)
    report = h.service.evaluate_contract(
        h.writer.record_run(evidence.model_copy(update={"checks": tuple(captures)})),
        h.contract,
    )
    assert report.valid is (fault is None)


@pytest.mark.parametrize(
    "field",
    [
        "operation",
        "task",
        "principal",
        "commit",
        "budget",
        "image",
        "executor",
        "artifact",
        "view",
        "approval",
        "repetition",
    ],
)
def test_authoritative_records_cannot_cross_expected_binding(tmp_path: Path, field):
    h = Harness(tmp_path)
    run = h.writer.record_run(h.evidence())
    bound, context = h.bound, h.context
    request = bound.request
    updates = {
        "operation": {"operation_id": "other"},
        "task": {"task": request.task.model_copy(update={"text": "other"})},
        "commit": {"source_commit": "sha1:" + "b" * 40},
        "budget": {
            "budget": request.budget.model_copy(update={"model_input_tokens": 9999})
        },
    }
    if field in updates:
        bound = bound.model_copy(
            update={"request": request.model_copy(update=updates[field])}
        )
    elif field == "principal":
        from contractcapsule.models.base import Principal

        bound = bound.model_copy(
            update={
                "request": request.model_copy(update={"principal": Principal("other")})
            }
        )
    elif field == "image":
        bound = bound.model_copy(
            update={
                "profile": bound.profile.model_copy(
                    update={
                        "runner": bound.profile.runner.model_copy(
                            update={"image_digest": digest(b"other")}
                        )
                    }
                )
            }
        )
    elif field == "executor":
        bound = bound.model_copy(
            update={
                "profile": bound.profile.model_copy(
                    update={
                        "executor": bound.profile.executor.model_copy(
                            update={"argv": ("other",)}
                        )
                    }
                )
            }
        )
    elif field == "artifact":
        artifact = bound.artifacts[0].model_copy(update={"data": b"other"})
        bound = bound.model_copy(update={"artifacts": (artifact, *bound.artifacts[1:])})
    elif field in {"view", "approval"}:
        key = "new_view_digest" if field == "view" else "approval_digest"
        context = context.model_copy(update={key: digest(b"other")})
    else:
        run = run.model_copy(update={"repetition": 1})
    service = BehaviorService(bound, context, h.journal.verifier(), h.journal)
    assert not service.evaluate_contract(run, h.contract).valid


@pytest.mark.parametrize(
    "fault",
    [
        "no_root",
        "orphan",
        "duplicate",
        "unsafe",
        "no_digest",
        "too_big",
        "file_parent",
        "directory_content",
    ],
)
def test_incomplete_or_malformed_tree_blocks(tmp_path: Path, fault):
    h = Harness(tmp_path)
    entries = list(tree().entries)
    if fault == "no_root":
        entries.pop(0)
    elif fault == "orphan":
        entries.pop(1)
    elif fault == "duplicate":
        entries.append(entries[-1])
    elif fault == "file_parent":
        entries[1] = TreeEntry(path="src", kind="file", mode=0o644, digest=digest(b""))
    elif fault == "directory_content":
        entries[0] = entries[0].model_copy(update={"digest": digest(b"bad")})
    else:
        variants: dict[str, dict[str, Any]] = {
            "unsafe": {"path": "../escape"},
            "no_digest": {"digest": None},
            "too_big": {"size": 999999999},
        }
        values = variants[fault]
        entries[-1] = entries[-1].model_copy(update=values)
    final = Snapshot(entries=tuple(sorted(entries, key=lambda e: e.path)))
    assert not h.service.evaluate_contract(
        h.writer.record_run(h.evidence(final=final)), h.contract
    ).valid


def test_tampered_pair_payload_invalidates_existing_report(tmp_path: Path):
    h = Harness(tmp_path)
    old, new = h.pair()
    report = h.service.compare_runs(old, new, h.contract)
    assert report.valid
    with sqlite3.connect(h.fixture.base.registry.database_path) as connection:
        connection.execute("DROP TRIGGER m5_records_no_update")
        connection.execute(
            "UPDATE m5_records SET payload=? WHERE record_id=?",
            (b"{}", new.pair_record.record_id),
        )
    with pytest.raises(RecordError):
        h.service.verify_report(report)


def with_pair_probe(raw):
    check = raw["replacement_contract"]["extensions"]["x-m5-execution"]["checks"][-1]
    check["subject_probes"] = [
        {
            "probe_id": "pair-new",
            "test_id": "probe",
            "artifact_ids": ["probe"],
            "argv": [],
            "input_state": "new_final",
        }
    ]


@pytest.mark.parametrize("fault", [None, "old_operand", "before_post", "timeout"])
def test_pair_subject_probe_exact_operand_and_phase(tmp_path: Path, fault):
    h = Harness(tmp_path, with_pair_probe)
    old, new = h.pair()
    raw = h.journal.verifier().verify(
        new.pair_record,
        kind="pair",
        scope=h.service.scope,
        subject=h.service.subject("pair", 0),
    )
    pair = PairEvidence.model_validate_json(raw)
    inputs = (
        h.context.initial.digest_value(),
        tree("old").digest_value(),
        tree("new").digest_value(),
        identity(old.record.model_dump(mode="json")),
        identity(new.record.model_dump(mode="json")),
    )
    operand = inputs[1] if fault == "old_operand" else inputs[2]
    probe = ProcessCapture(
        subject=stage_subject(h.bound, h.context, "pair", 0, "pair-new", (operand,)),
        container_id="synthetic-pair-probe",
        started_ns=5 if fault == "before_post" else 52,
        finished_ns=55,
        exit_code=0,
        terminated=True,
        timed_out=fault == "timeout",
        output_limited=False,
        stdout=b"observed new state",
        stderr=b"",
    )
    capture = pair.checks[0]
    process = capture.process.model_copy(
        update={
            "subject": stage_subject(
                h.bound, h.context, "pair", 0, "differential", inputs, (probe,)
            )
        }
    )
    pair = pair.model_copy(
        update={
            "checks": (
                capture.model_copy(update={"process": process, "probes": (probe,)}),
            )
        }
    )
    old, new = h.writer.record_pair(old, new, pair)
    assert h.service.compare_runs(old, new, h.contract).valid is (fault is None)


def test_all_required_repetitions_pass_and_forged_group_fails(tmp_path: Path):
    h = Harness(tmp_path)
    pairs = []
    for i in range(3):
        old, new = h.pair(repetition=i)
        pairs.append(h.service.compare_runs(old, new, h.contract))
    report = h.service.evaluate_repetitions(tuple(pairs))
    assert report.valid
    h.service.verify_report(report)
    with pytest.raises(RecordError):
        h.service.verify_report(report.model_copy(update={"pairs": tuple(pairs[:2])}))


def test_old_explicit_false_expectation_cannot_be_ignored(tmp_path: Path):
    h = Harness(tmp_path)
    run = h.writer.record_run(h.evidence("old", changes={"target": True}))
    report = h.service.evaluate_contract(run, h.contract)
    assert not report.valid
    assert "TARGET_FAILED" in report.blockers


def test_forged_run_reference_and_duplicate_container_fail(tmp_path: Path):
    h = Harness(tmp_path)
    evidence = h.evidence()
    run = h.writer.record_run(evidence)
    forged = run.model_copy(
        update={"record": run.record.model_copy(update={"record_id": "made-up"})}
    )
    assert not h.service.evaluate_contract(forged, h.contract).valid
    first = evidence.checks[0]
    first = first.model_copy(
        update={
            "process": first.process.model_copy(
                update={"container_id": evidence.executor.container_id}
            )
        }
    )
    evidence = evidence.model_copy(update={"checks": (first, *evidence.checks[1:])})
    assert not h.service.evaluate_contract(
        h.writer.record_run(evidence), h.contract
    ).valid


def test_aborted_before_executor_preserves_missing_execution(tmp_path: Path):
    h = Harness(tmp_path)
    captures = h.evidence(changes={"precondition": False}).checks[:1]
    aborted = RunEvidence(
        role="new",
        repetition=0,
        executor=None,
        final=None,
        snapshot_ns=None,
        checks=captures,
    )
    run = h.writer.record_run(aborted)
    report = h.service.evaluate_contract(run, h.contract)
    assert not report.valid
    payload = h.journal.verifier().verify(
        run.record,
        kind="run",
        scope=h.service.scope,
        subject=h.service.subject("new", 0),
    )
    stored = RunEvidence.model_validate_json(payload)
    assert stored.executor is None and stored.final is None
    assert stored.checks[0].process.stdout == captures[0].process.stdout


def test_empty_paired_check_set_is_not_vacuous_success(tmp_path: Path):
    def amend(raw):
        contract = raw["replacement_contract"]
        contract["verification"]["differential"] = []
        profile = contract["extensions"]["x-m5-execution"]
        profile["checks"] = [c for c in profile["checks"] if c["phase"] != "pair"]

    h = Harness(tmp_path, amend)
    old = h.writer.record_run(h.evidence("old"))
    new = h.writer.record_run(h.evidence())
    pair = PairEvidence(
        repetition=0, old_record=old.record, new_record=new.record, checks=()
    )
    old, new = h.writer.record_pair(old, new, pair)
    assert not h.service.compare_runs(old, new, h.contract).valid
