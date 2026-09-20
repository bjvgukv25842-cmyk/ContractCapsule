from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from experiments.models import ExperimentConfig, RunRecord, RunStore
from experiments.preflight import PreflightError, preflight_config
from experiments.run import RunRefusal, run_once
from experiments.score import ScoreError, score_task


def _task(tmp_path: Path) -> dict[str, object]:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "target.py").write_text("print('target')\n", encoding="utf-8")
    (tests / "invariant.py").write_text("print('invariant')\n", encoding="utf-8")
    return {
        "task_id": "task-001",
        "repository_commit": "a" * 40,
        "max_runtime_seconds": 5,
        "tests": {
            "target": ["tests/target.py"],
            "invariant": ["tests/invariant.py"],
        },
        "root": str(tmp_path),
    }


def _config(tmp_path: Path) -> ExperimentConfig:
    return ExperimentConfig(
        study_id="m7-test",
        agent="codex",
        model="unavailable",
        conditions=("B0", "CC"),
        repetitions=1,
        runtime_budget_tokens=128,
        timeout_seconds=5,
        output_path=tmp_path / "runs.jsonl",
    )


def test_run_id_is_stable_and_store_is_append_only(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.jsonl")
    config = _config(tmp_path)
    first = RunRecord.new(
        task_id="task-001",
        condition="CC",
        agent="codex",
        repetition=0,
        repository_commit="a" * 40,
        capsule_digests=["sha256:" + "1" * 64],
        prompt_digest="sha256:" + "2" * 64,
        raw_event_path="raw/task-001.jsonl",
        exit_code=0,
        infrastructure_failure=False,
    )
    second = RunRecord.new(
        task_id="task-001",
        condition="CC",
        agent="codex",
        repetition=0,
        repository_commit="a" * 40,
        capsule_digests=["sha256:" + "1" * 64],
        prompt_digest="sha256:" + "2" * 64,
        raw_event_path="raw/task-001.jsonl",
        exit_code=0,
        infrastructure_failure=False,
    )
    assert first.run_id == second.run_id
    store.append(first)
    store.append(first)
    assert store.get(first.run_id) == first
    assert len((tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    with pytest.raises(ValueError):
        store.append(first.model_copy(update={"exit_code": 1}))
    assert config.study_id == "m7-test"


def test_only_infrastructure_failures_are_retryable(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.jsonl")
    base = {
        "task_id": "task-001",
        "condition": "B0",
        "agent": "codex",
        "repetition": 0,
        "repository_commit": "a" * 40,
        "capsule_digests": [],
        "prompt_digest": "sha256:" + "2" * 64,
        "raw_event_path": "raw/task-001.jsonl",
        "exit_code": 1,
    }
    infra = RunRecord.new(**base, infrastructure_failure=True, failure_code="TIMEOUT")
    task_failure = RunRecord.new(
        **{**base, "condition": "B1"},
        infrastructure_failure=False,
        failure_code="TARGET_FAILED",
    )
    store.append(infra)
    store.append(task_failure)
    assert store.retry_eligible(infra.run_id)
    assert not store.retry_eligible(task_failure.run_id)
    retry = infra.retry_attempt()
    assert retry.run_id != infra.run_id
    assert retry.attempt_id != infra.attempt_id
    assert retry.retry_of == infra.run_id


def test_dry_run_refuses_without_preflight_receipt(tmp_path: Path) -> None:
    task = _task(tmp_path)
    config = _config(tmp_path)
    with pytest.raises(RunRefusal, match="preflight"):
        run_once(task, config=config, store=RunStore(config.output_path), dry_run=False)


def test_preflight_rejects_duplicate_yaml_keys_and_records_unavailable_metadata(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("agent: codex\nagent: claude\n", encoding="utf-8")
    with pytest.raises(PreflightError):
        preflight_config(config_path)
    receipt = preflight_config(_config(tmp_path), output_path=tmp_path / "receipt.json")
    assert receipt.agent == "codex"
    assert receipt.version is None
    assert receipt.model is None
    assert receipt.digest.startswith("sha256:")
    assert (tmp_path / "receipt.json").exists()


def test_scorer_uses_declared_relative_tests_and_ignores_condition_labels(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    (tmp_path / "tests" / "target.py").write_text(
        "import sys\nprint('ok' if 'B0' not in sys.argv else 'bad')\n",
        encoding="utf-8",
    )
    result = score_task(
        task,
        condition="B0",
        command=[sys.executable, "tests/target.py"],
        cwd=tmp_path,
        timeout_seconds=2,
        labels={"target": True, "invariant": False},
    )
    assert result.target_passed is True
    assert result.condition is None
    with pytest.raises(ScoreError):
        score_task(task, command=[sys.executable, "../escape.py"], cwd=tmp_path)


def test_run_record_round_trips_jsonl(tmp_path: Path) -> None:
    record = RunRecord.new(
        task_id="task-001",
        condition="B1",
        agent="codex",
        repetition=0,
        repository_commit="a" * 40,
        capsule_digests=[],
        prompt_digest="sha256:" + "2" * 64,
        raw_event_path="raw/a.jsonl",
        exit_code=0,
        infrastructure_failure=False,
    )
    store = RunStore(tmp_path / "runs.jsonl")
    store.append(record)
    loaded = RunRecord.model_validate_json(
        json.dumps(json.loads((tmp_path / "runs.jsonl").read_text()))
    )
    assert loaded == record
