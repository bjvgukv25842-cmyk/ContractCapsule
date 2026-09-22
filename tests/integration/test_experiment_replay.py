from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from baselines import Budget, provider_for
from benchmark.loader import load_task
from benchmark.schema import TaskSpec
from experiments.models import ExperimentConfig, RunRecord, RunStore
from experiments.preflight import PreflightError, preflight_config
from experiments.run import RunRefusal, run_once
from experiments.score import ScoreError, score_task


def _write_task_package(
    tmp_path: Path,
    *,
    approval: str = "approved",
    executable: bool = True,
    target_command: str = "tests/target.py",
    repository_commit: str = "a" * 40,
) -> TaskSpec:
    for relative in (
        "capsules/old",
        "capsules/new",
        "gold",
        "tests/target",
        "tests/invariant",
        "tests/spillover",
        "licenses",
    ):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    (tmp_path / "prompt.md").write_text("exercise\n", encoding="utf-8")
    (tmp_path / "capsules/old/context.md").write_text("old\n", encoding="utf-8")
    (tmp_path / "capsules/new/context.md").write_text("new\n", encoding="utf-8")
    (tmp_path / "tests/target/fixture.txt").write_text("target\n", encoding="utf-8")
    (tmp_path / "tests/invariant/fixture.txt").write_text("invariant\n", encoding="utf-8")
    (tmp_path / "tests/spillover/fixture.txt").write_text("spillover\n", encoding="utf-8")
    (tmp_path / "tests/target.py").write_text("print('target')\n", encoding="utf-8")
    (tmp_path / "tests/invariant.py").write_text("print('invariant')\n", encoding="utf-8")
    (tmp_path / "tests/spillover.py").write_text("print('spillover')\n", encoding="utf-8")
    (tmp_path / "gold/required-atoms.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "gold/target-effects.yaml").write_text("target: true\n", encoding="utf-8")
    (tmp_path / "gold/protected-invariants.yaml").write_text("invariant: true\n", encoding="utf-8")
    (tmp_path / "gold/forbidden-spillover.yaml").write_text("spillover: false\n", encoding="utf-8")
    (tmp_path / "licenses/provenance.json").write_text("{}\n", encoding="utf-8")
    digest = "sha256:" + "1" * 64
    task_yaml = f"""task_id: task-001
category: policy
language: python
repository:
  source_url: https://github.com/example/project
  commit: {repository_commit}
  license: MIT
  source_status: verified
  content_digest: {digest}
human_approval: {approval}
executable: {'true' if executable else 'false'}
max_runtime_seconds: 5
checks:
  target:
    - check_id: target
      command: [python3, {target_command}]
  invariant:
    - check_id: invariant
      command: [python3, tests/invariant.py]
  spillover:
    - check_id: spillover
      command: [python3, tests/spillover.py]
"""
    (tmp_path / "task.yaml").write_text(task_yaml, encoding="utf-8")
    (tmp_path / "repository.lock").write_text(
        json.dumps({"content_digest": digest}) + "\n", encoding="utf-8"
    )
    return load_task(tmp_path)


def _task(tmp_path: Path) -> TaskSpec:
    return _write_task_package(tmp_path)


def _git_workspace(tmp_path: Path) -> tuple[Path, str]:
    workspace = tmp_path
    workspace.mkdir(parents=True, exist_ok=True)
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "capsulebench@example.invalid"],
        ["git", "config", "user.name", "CapsuleBench"],
        ["git", "remote", "add", "origin", "https://github.com/example/project"],
    ]
    for command in commands:
        subprocess.run(command, cwd=workspace, check=True, capture_output=True)
    (workspace / "README.md").write_text("checkout\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"],
        cwd=workspace,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return workspace, commit


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
    assert retry.raw_event_path != infra.raw_event_path


def test_task_failures_cannot_be_marked_as_retryable_infrastructure(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="infrastructure"):
        RunRecord.new(
            task_id="task-001",
            condition="B0",
            agent="codex",
            repetition=0,
            repository_commit="a" * 40,
            capsule_digests=[],
            prompt_digest="sha256:" + "2" * 64,
            raw_event_path="raw/task-001.jsonl",
            exit_code=1,
            infrastructure_failure=True,
            failure_code="TARGET_FAILED",
            task_outcome="failed",
        )


def test_infrastructure_failure_cannot_claim_a_successful_exit() -> None:
    with pytest.raises(ValueError, match="exit code"):
        RunRecord.new(
            task_id="task-001",
            condition="B0",
            agent="codex",
            repetition=0,
            repository_commit="a" * 40,
            capsule_digests=[],
            prompt_digest="sha256:" + "2" * 64,
            raw_event_path="raw/task-001.jsonl",
            exit_code=0,
            infrastructure_failure=True,
            failure_code="TIMEOUT",
        )


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


def test_available_preflight_requires_authenticated_receipt_and_frozen_binding(
    tmp_path: Path,
) -> None:
    class FakeAdapter:
        binary = sys.executable

        def preflight(self) -> object:
            return type(
                "Observed",
                (),
                {
                    "agent": "codex",
                    "version": "1.2.3",
                    "model": "codex-test",
                    "capabilities": (),
                },
            )()

    from experiments.preflight import validate_receipt

    key = b"k" * 32
    config = ExperimentConfig(
        study_id="signed",
        agent="codex",
        model="codex-test",
        version="1.2.3",
        binary=sys.executable,
        output_path=tmp_path / "runs.jsonl",
    )
    receipt = preflight_config(
        config,
        adapter=FakeAdapter(),
        signing_key=key,
        output_path=tmp_path / "signed.json",
    )
    assert receipt.available is True
    validate_receipt(receipt, config, signing_key=key)
    forged = receipt.model_copy(update={"model": "other", "digest": receipt.computed_digest()})
    with pytest.raises(PreflightError):
        validate_receipt(forged, config, signing_key=key)


def test_live_run_rejects_adapter_metadata_drift_after_preflight(tmp_path: Path) -> None:
    class DriftAdapter:
        binary = sys.executable
        agent_name = "codex"

        def preflight(self) -> object:
            return SimpleNamespace(
                agent="codex",
                version="1.2.3",
                model="codex-test",
                capabilities=(),
            )

        def run_task(self, **_: object) -> object:
            return SimpleNamespace(
                exit_code=0,
                stdout=b"raw-event",
                metadata=SimpleNamespace(
                    agent="codex", version="9.9.9", model="codex-test"
                ),
            )

    key = b"r" * 32
    workspace, commit = _git_workspace(tmp_path / "workspace")
    task = _write_task_package(tmp_path / "package", repository_commit=commit)
    receipt_path = tmp_path / "receipt.json"
    config = ExperimentConfig(
        study_id="drift",
        agent="codex",
        model="codex-test",
        version="1.2.3",
        binary=sys.executable,
        output_path=tmp_path / "runs.jsonl",
        live_agent=True,
        dry_run=False,
        preflight_receipt=receipt_path,
    )
    preflight_config(config, adapter=DriftAdapter(), signing_key=key)
    with pytest.raises(RunRefusal, match="result version"):
        run_once(
            task,
            config=config,
            adapter=DriftAdapter(),
            workspace=workspace,
            dry_run=False,
            preflight_key=key,
        )


def test_live_run_rejects_usage_counts_not_bound_to_raw_events(tmp_path: Path) -> None:
    class ForgedUsageAdapter:
        binary = sys.executable
        agent_name = "codex"

        def preflight(self) -> object:
            return SimpleNamespace(
                agent="codex",
                version="1.2.3",
                model="codex-test",
                capabilities=(),
            )

        def run_task(self, **_: object) -> object:
            return SimpleNamespace(
                exit_code=0,
                stdout=b"raw-event",
                metadata=SimpleNamespace(
                    agent="codex", version="1.2.3", model="codex-test"
                ),
                usage=SimpleNamespace(
                    input_tokens=1,
                    output_tokens=1,
                    raw_digest="sha256:" + "0" * 64,
                ),
            )

    key = b"u" * 32
    workspace, commit = _git_workspace(tmp_path / "workspace")
    task = _write_task_package(tmp_path / "package", repository_commit=commit)
    receipt_path = tmp_path / "receipt.json"
    config = ExperimentConfig(
        study_id="usage",
        agent="codex",
        model="codex-test",
        version="1.2.3",
        binary=sys.executable,
        output_path=tmp_path / "runs.jsonl",
        live_agent=True,
        dry_run=False,
        preflight_receipt=receipt_path,
    )
    preflight_config(config, adapter=ForgedUsageAdapter(), signing_key=key)
    with pytest.raises(RunRefusal, match="raw digest"):
        run_once(
            task,
            config=config,
            adapter=ForgedUsageAdapter(),
            workspace=workspace,
            dry_run=False,
            preflight_key=key,
        )


def test_screening_yaml_loads_arrays_without_freezing_agent_metadata() -> None:
    from experiments.models import load_config

    config = load_config("experiments/configs/m7-screening.yaml")
    assert config.model is None
    assert config.version is None
    assert config.conditions == ("B0", "B1", "B2", "B3", "B4", "CC")
    assert config.dry_run is True


def test_config_accepts_json_style_condition_arrays() -> None:
    config = ExperimentConfig(
        study_id="array-input",
        agent="unavailable",
        conditions=["B0", "CC"],  # type: ignore[arg-type]
        dry_run=True,
    )
    assert config.conditions == ("B0", "CC")


def test_run_plan_is_bound_to_declared_condition_matrix(tmp_path: Path) -> None:
    task = _task(tmp_path)
    config = ExperimentConfig(
        study_id="matrix",
        agent="codex",
        conditions=("CC",),
        repetitions=1,
        runtime_budget_tokens=128,
        output_path=tmp_path / "matrix.jsonl",
    )
    artifact = provider_for("B0").provide(task, Budget(128))
    with pytest.raises(RunRefusal, match="declared condition"):
        run_once(
            task,
            config=config,
            artifact=artifact,
            dry_run=True,
        )
    repetition_config = config.model_copy(update={"conditions": ("B0",)})
    with pytest.raises(RunRefusal, match="repetition"):
        run_once(task, config=repetition_config, repetition=1, dry_run=True)


def test_run_refuses_unvalidated_mapping_even_when_fields_look_approved(
    tmp_path: Path,
) -> None:
    forged = {
        "task_id": "task-001",
        "repository_commit": "a" * 40,
        "human_approval": "approved",
        "executable": True,
        "repository": {"source_status": "verified"},
    }
    with pytest.raises(RunRefusal, match="loader-owned"):
        run_once(forged, config=_config(tmp_path), dry_run=True)


def test_run_and_score_refuse_publicly_constructed_task_models(tmp_path: Path) -> None:
    loaded = _task(tmp_path)
    forged = TaskSpec.model_validate(loaded.model_dump(mode="python"))
    with pytest.raises(RunRefusal, match="loader-owned"):
        run_once(forged, config=_config(tmp_path), dry_run=True)
    with pytest.raises(ScoreError, match="loader-owned"):
        score_task(forged, cwd=tmp_path)


def test_loaded_task_is_revalidated_before_execution(tmp_path: Path) -> None:
    task = _task(tmp_path)
    task_yaml = (tmp_path / "task.yaml").read_text(encoding="utf-8")
    (tmp_path / "task.yaml").write_text(
        task_yaml.replace("executable: true", "executable: false"),
        encoding="utf-8",
    )
    with pytest.raises(RunRefusal, match="changed"):
        run_once(task, config=_config(tmp_path), dry_run=True)


def test_loaded_task_rejects_mutated_package_content(tmp_path: Path) -> None:
    task = _task(tmp_path)
    (tmp_path / "capsules/old/context.md").write_text("mutated\n", encoding="utf-8")
    with pytest.raises(RunRefusal, match="changed"):
        run_once(task, config=_config(tmp_path), dry_run=True)


def test_run_rejects_unattested_artifact_mappings(tmp_path: Path) -> None:
    task = _task(tmp_path)
    with pytest.raises(RunRefusal, match="artifact"):
        run_once(
            task,
            config=_config(tmp_path),
            artifact={"condition": "B0"},
            dry_run=True,
        )


def test_run_rejects_external_workspace(tmp_path: Path) -> None:
    package = tmp_path / "package"
    task = _task(package)
    external = tmp_path / "external"
    external.mkdir()
    with pytest.raises(RunRefusal, match="workspace"):
        run_once(
            task,
            config=_config(package),
            workspace=external,
            dry_run=True,
        )


def test_live_workspace_rejects_ignored_files(tmp_path: Path) -> None:
    workspace, commit = _git_workspace(tmp_path / "workspace")
    task = _write_task_package(tmp_path / "package", repository_commit=commit)
    (workspace / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "ignore-rule"],
        cwd=workspace,
        check=True,
    )
    # Update the task lock to the new immutable checkout commit.
    current = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    task_yaml = (tmp_path / "package" / "task.yaml").read_text(encoding="utf-8")
    (tmp_path / "package" / "task.yaml").write_text(
        task_yaml.replace(commit, current), encoding="utf-8"
    )
    task = load_task(tmp_path / "package")
    (workspace / "ignored.txt").write_text("external influence\n", encoding="utf-8")
    with pytest.raises(RunRefusal, match="clean"):
        run_once(
            task,
            config=_config(tmp_path / "package"),
            workspace=workspace,
            dry_run=False,
        )


def test_run_rejects_cross_task_artifact(tmp_path: Path) -> None:
    task_a = _task(tmp_path / "task-a")
    task_b = _task(tmp_path / "task-b")
    artifact = provider_for("B0").provide(task_b, Budget(128))
    with pytest.raises(RunRefusal, match="artifact .*binding"):
        run_once(
            task_a,
            config=_config(tmp_path / "task-a"),
            artifact=artifact,
            dry_run=True,
        )


def test_run_rejects_artifact_budget_mismatch(tmp_path: Path) -> None:
    task = _task(tmp_path)
    artifact = provider_for("B0").provide(task, Budget(1))
    with pytest.raises(RunRefusal, match="budget"):
        run_once(
            task,
            config=_config(tmp_path),
            artifact=artifact,
            dry_run=True,
        )


def test_scorer_rejects_approved_tasks_without_all_three_check_classes(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    raw = task.model_dump(mode="python")
    raw["checks"]["invariant"] = ()
    raw["checks"]["spillover"] = ()
    with pytest.raises(ValueError, match="target, invariant, and spillover"):
        TaskSpec.model_validate(raw)


def test_scorer_uses_declared_relative_tests_and_ignores_condition_labels(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    (tmp_path / "tests" / "target.py").write_text(
        "import sys\nprint('ok' if 'B0' not in sys.argv else 'bad')\n",
        encoding="utf-8",
    )
    task = load_task(tmp_path)
    result = score_task(
        task,
        condition="B0",
        command=["python3", "tests/target.py"],
        cwd=tmp_path,
        timeout_seconds=2,
        labels={"target": True, "invariant": False},
    )
    assert result.target_passed is True
    assert result.condition is None
    with pytest.raises(ScoreError):
        score_task(task, command=["python3", "../escape.py"], cwd=tmp_path)


def test_scorer_rejects_external_cwd(tmp_path: Path) -> None:
    task = _task(tmp_path / "package")
    external = tmp_path / "external"
    external.mkdir()
    with pytest.raises(ScoreError, match="match loader task package"):
        score_task(task, cwd=external)


def test_scorer_refuses_unvalidated_mapping_with_forged_checks(tmp_path: Path) -> None:
    forged = {
        "task_id": "task-001",
        "human_approval": "approved",
        "executable": True,
        "repository": {"source_status": "verified"},
        "tests": {
            "target": [["/usr/bin/true"]],
            "invariant": [["/usr/bin/true"]],
            "spillover": [["/usr/bin/true"]],
        },
    }
    with pytest.raises(ScoreError, match="loader-owned"):
        score_task(forged, cwd=tmp_path)


def test_scorer_rejects_unapproved_tasks(tmp_path: Path) -> None:
    task = _write_task_package(tmp_path, approval="pending", executable=False)
    with pytest.raises(ScoreError, match="approved"):
        score_task(task, cwd=tmp_path)


def test_scorer_rejects_declared_symlink_paths(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-test.py"
    outside.write_text("print('outside')\n", encoding="utf-8")
    link = tmp_path / "tests" / "link.py"
    task = _write_task_package(tmp_path, target_command="tests/link.py")
    link.symlink_to(outside)
    with pytest.raises(ScoreError, match="symlink"):
        score_task(task, cwd=tmp_path)


def test_explicit_scorer_command_must_match_declared_argv_exactly(tmp_path: Path) -> None:
    task = _task(tmp_path)
    with pytest.raises(ScoreError, match="declared"):
        score_task(
            task,
            command=["python3", "tests/target.py", "--extra"],
            cwd=tmp_path,
        )


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
    reopened = RunStore(tmp_path / "runs.jsonl")
    assert reopened.get(record.run_id) == record
    loaded = RunRecord.model_validate_json(
        json.dumps(json.loads((tmp_path / "runs.jsonl").read_text()))
    )
    assert loaded == record
