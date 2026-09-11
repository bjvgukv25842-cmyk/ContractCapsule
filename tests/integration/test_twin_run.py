"""Real Docker execution; these tests deliberately never skip unavailable Docker."""

from pathlib import Path

from contractcapsule.swap.docker_runner import DockerRunner
from contractcapsule.validate.models import RunnerConfig


def config(**changes):
    values = dict(
        image_digest="sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203",
        platform="linux/arm64", profile="ccs-m5-docker/1.0.0", cpu_limit=1,
        memory_bytes=134217728, process_limit=32, timeout_seconds=10,
        stdout_limit_bytes=4096, stderr_limit_bytes=4096,
        output_tree_limit_bytes=1048576, output_tree_file_limit=100,
    )
    values.update(changes)
    return RunnerConfig(**values)


def test_real_bounded_process_and_stopped_snapshot(tmp_path: Path):
    runner = DockerRunner(config())
    result = runner.execute(
        subject="sha256:" + "a" * 64,
        program="print('real python'); open('/workspace/value', 'w').write('changed')",
        files={"value": b"initial"},
    )
    assert result.process.stdout == b"real python\n"
    assert result.process.terminated
    assert result.process.exit_code == 0
    assert result.tree["value"] == b"changed"
