"""Real paired execution acceptance; unavailable Docker is a failure, never a skip."""

import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest

from contractcapsule.resolve.policies import StaticEligibilityAuthorizer
from contractcapsule.swap.attempts import AttemptStore
from contractcapsule.swap.docker_runner import DockerRunner
from contractcapsule.swap.trees import RunnerError
from contractcapsule.swap.twin_models import TwinFailure, TwinOutcome
from contractcapsule.validate.run_models import (
    RunEvidence,
    evaluation_scope,
    run_subject,
)
from tests.m5_twin_helpers import TwinFixture


def test_actual_published_context_drives_identical_executor(tmp_path):
    fixture = TwinFixture(tmp_path)
    (fixture.source / "src/config.txt").write_text("dirty worktree\n")
    outcome = fixture.runner.run(fixture.approval)
    assert isinstance(outcome, TwinOutcome), outcome
    assert outcome.valid, outcome
    pair = outcome.repetitions.pairs[0]
    assert pair.old_report.ter.numerator == 0
    assert pair.new_report.ter.numerator == 1
    assert pair.new_report.pip.numerator == 1
    assert pair.new_report.bsr.numerator == 0
    assert pair.old_to_new == ("src/config.txt",)
    fixture.runner.verify_outcome(outcome)
    assert len(outcome.manifest.stages) == 15
    assert len({s.process.container_id for s in outcome.manifest.stages}) == 15
    assert all(s.process.terminated for s in outcome.manifest.stages)
    restored = replace(
        fixture.runner,
        attempt_store=AttemptStore(
            fixture.base.registry.database_path, fixture.attempts._key
        ),
    )
    assert restored.run(fixture.approval) == outcome
    for changed in (
        outcome.model_copy(
            update={"manifest": outcome.manifest.model_copy(update={"state": "FAILED"})}
        ),
        outcome.model_copy(
            update={"repetitions": outcome.repetitions.model_copy(update={"pairs": ()})}
        ),
    ):
        with pytest.raises((RunnerError, ValueError)):
            restored.verify_outcome(changed)
    fixture.revoked = True
    assert isinstance(restored.run(fixture.approval), TwinFailure)


def read_run(fixture, outcome, role="new"):
    agent = getattr(outcome.repetitions.pairs[0], role)
    payload = fixture.journal.verifier().verify(
        agent.record,
        kind="run",
        scope=evaluation_scope(fixture.bound),
        subject=run_subject(fixture.bound, outcome.manifest.context, role, 0),
    )
    return RunEvidence.model_validate_json(payload)


def test_real_high_risk_keeps_all_three_predeclared_pairs(tmp_path):
    fixture = TwinFixture(tmp_path, high=True)
    outcome = fixture.runner.run(fixture.approval)
    assert isinstance(outcome, TwinOutcome) and outcome.valid, outcome
    assert [p.old.repetition for p in outcome.repetitions.pairs] == [0, 1, 2]
    assert len(outcome.manifest.stages) == 45
    assert len({s.process.container_id for s in outcome.manifest.stages}) == 45
    assert all(
        p.old_report.ter.numerator == 0 and p.new_report.ter.numerator == 1
        for p in outcome.repetitions.pairs
    )
    fixture.runner.verify_outcome(outcome)


@pytest.mark.parametrize(
    "program",
    [
        b'print(\'{"check_id":"precondition","observation":false}\')',
        b'print(\'{"check_id":"precondition","observation":true,"extra":1}\')',
    ],
)
def test_precondition_rejection_records_missing_executors_and_exact_negative_replay(
    tmp_path, program
):
    fixture = TwinFixture(tmp_path, program_changes={"precondition": program})
    outcome = fixture.runner.run(fixture.approval)
    assert isinstance(outcome, TwinOutcome) and not outcome.valid, outcome
    assert [s.stage_id for s in outcome.manifest.stages] == [
        "precondition",
        "precondition",
    ]
    for role in ("old", "new"):
        run = read_run(fixture, outcome, role)
        assert run.executor is None and run.final is None and run.snapshot_ns is None
        assert len(run.checks) == 1
    fixture.runner.verify_outcome(outcome)
    assert fixture.runner.run(fixture.approval) == outcome


@pytest.mark.parametrize("fault", ["expired", "mismatched", "revoked"])
def test_no_candidate_executes_without_current_execution_approval(tmp_path, fault):
    fixture = TwinFixture(tmp_path)
    approval = fixture.approval
    if fault == "expired":
        fixture.now += timedelta(hours=2)
    elif fault == "revoked":
        fixture.revoked = True
    else:
        approval = approval.model_copy(update={"operation_id": "foreign"})
    assert isinstance(fixture.runner.run(approval), TwinFailure)
    with sqlite3.connect(fixture.base.registry.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM m5_twin_attempts").fetchone()[0] == 0


@pytest.mark.parametrize('fault', ['revoked', 'expired', 'permission', 'artifact'])
def test_between_stage_denial_redacts_reply_but_retains_actual_negative(tmp_path, monkeypatch, fault):
    fixture = TwinFixture(tmp_path)
    real = DockerRunner.run_stage
    def revoke_after_stage(runner, *args, **kwargs):
        result = real(runner, *args, **kwargs)
        if fault == 'revoked':
            fixture.revoked = True
        elif fault == 'expired':
            fixture.now += timedelta(hours=2)
        elif fault == 'artifact':
            (fixture.root / 'twin-package/tests/behavioral/executor.py').write_bytes(b'tampered')
        else:
            authorizer = StaticEligibilityAuthorizer(grants=())
            object.__setattr__(fixture.old_validation.compiler, 'authorizer', authorizer)
            object.__setattr__(fixture.old_validation.compiler.evidence, 'authorizer', authorizer)
        return result
    monkeypatch.setattr(DockerRunner, 'run_stage', revoke_after_stage)
    reply = fixture.runner.run(fixture.approval)
    assert isinstance(reply, TwinFailure), reply
    assert set(reply.model_dump()) == {'operation_id', 'code'}
    row = fixture.attempts.get(fixture.runner._attempt_key(fixture.bound))
    assert row.state == 'COMPLETE'
    stored = TwinOutcome.model_validate_json(row.manifest)
    assert not stored.valid and stored.manifest.state == 'FAILED'
    assert len(stored.manifest.stages) == 1
    assert stored.manifest.stages[0].stage_id == 'precondition'
    assert read_run(fixture, stored, 'old').executor is None
    assert read_run(fixture, stored, 'new').executor is None


def test_failed_manifest_persistence_keeps_reserved_attempt_and_blocks_retry(tmp_path, monkeypatch):
    fixture = TwinFixture(tmp_path, program_changes={'precondition': b'print("false")'})
    def unavailable(*args, **kwargs):
        raise OSError('synthetic persistence failure')
    monkeypatch.setattr(AttemptStore, 'complete', unavailable)
    assert isinstance(fixture.runner.run(fixture.approval), TwinFailure)
    row = fixture.attempts.get(fixture.runner._attempt_key(fixture.bound))
    assert row.state == 'RUNNING' and row.manifest is None
    assert isinstance(fixture.runner.run(fixture.approval), TwinFailure)


@pytest.mark.parametrize(
    ("program", "profile_change", "flag"),
    [
        (
            b"import time\ntime.sleep(30)\n",
            lambda profile: profile["runner"].update(timeout_seconds=1),
            "timed_out",
        ),
        (
            b"while True:\n print('x' * 4096, flush=True)\n",
            lambda profile: profile["runner"].update(
                stdout_limit_bytes=256, timeout_seconds=10
            ),
            "output_limited",
        ),
    ],
)
def test_resource_failure_is_persisted_and_replay_does_not_rerun(
    tmp_path, program, profile_change, flag
):
    fixture = TwinFixture(
        tmp_path,
        program_changes={"executor": program},
        profile_change=profile_change,
    )
    outcome = fixture.runner.run(fixture.approval)
    assert isinstance(outcome, TwinOutcome), outcome
    assert not outcome.valid
    assert outcome.manifest.state in {"FAILED", "UNCERTAIN"}
    resource_stages = [
        stage
        for stage in outcome.manifest.stages
        if stage.stage_id == "executor" and stage.process is not None
    ]
    assert resource_stages
    assert any(getattr(stage.process, flag) for stage in resource_stages)
    assert all(stage.process.terminated for stage in resource_stages)
    fixture.runner.verify_outcome(outcome)

    row = fixture.attempts.get(fixture.runner._attempt_key(fixture.bound))
    assert row is not None and row.state == "COMPLETE" and row.manifest is not None
    assert fixture.runner.run(fixture.approval) == outcome
