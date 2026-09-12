"""Real Docker execution; these tests deliberately never skip unavailable Docker."""

from pathlib import Path

from contractcapsule.swap.docker_runner import DockerRunner
from contractcapsule.swap.trees import capture_tree
from contractcapsule.validate.models import Artifact, Invocation, RunnerConfig
from contractcapsule.validate.run_models import ProcessCapture, digest_bytes


def config(**changes):
    values = {
        "image_digest": "sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203",
        "platform": "linux/arm64",
        "profile": "ccs-m5-docker/1.0.0",
        "cpu_limit": 1,
        "memory_bytes": 134217728,
        "process_limit": 32,
        "timeout_seconds": 10,
        "stdout_limit_bytes": 4096,
        "stderr_limit_bytes": 4096,
        "output_tree_limit_bytes": 1048576,
        "output_tree_file_limit": 100,
    }
    values.update(changes)
    return RunnerConfig(**values)


def test_real_bounded_process_and_stopped_snapshot(tmp_path: Path):
    runner = DockerRunner(config())
    program = b"print('real python'); open('/workspace/value', 'w').write('changed')"
    (tmp_path / "value").write_bytes(b"initial")
    result = runner.run_stage(
        subject="sha256:" + "a" * 64,
        invocation=Invocation(test_id="executor", artifact_ids=("executor",), argv=()),
        artifacts=(
            Artifact(
                test_id="executor",
                path="task.py",
                kind="behavioral",
                digest=digest_bytes(program),
                data=program,
            ),
        ),
        inputs={},
        workspace=capture_tree(tmp_path, config()),
    )
    assert result.process.stdout == b"real python\n"
    assert result.process.terminated
    assert result.process.exit_code == 0
    assert isinstance(result.process, ProcessCapture)
    assert len(result.process.container_id) == 64
    assert result.snapshot_ns is not None and result.tree is not None
    assert result.process.started_ns < result.process.finished_ns <= result.snapshot_ns
    assert dict(result.tree.files)["value"] == b"changed"
    assert not result.blockers
