"""Actual stage security boundaries; Docker availability is never skipped."""

import io
import json
import re
import tarfile

import pytest

from contractcapsule.swap.docker_lifecycle import DockerLifecycle
from contractcapsule.swap.docker_runner import DockerRunner
from contractcapsule.swap.process_io import checked
from contractcapsule.swap.trees import FrozenTree, RunnerError, capture_tree, read_tar
from contractcapsule.validate.models import Artifact, Invocation
from contractcapsule.validate.run_models import digest_bytes
from tests.integration.test_twin_run import config


def stage(program, *, argv=(), settings=None, extras=(), inputs=None):
    data = program.encode()
    artifact = Artifact(
        test_id="entry",
        path="nested/main.py",
        kind="behavioral",
        digest=digest_bytes(data),
        data=data,
    )
    return DockerRunner(settings or config()).run_stage(
        "sha256:" + "a" * 64,
        Invocation(test_id="entry", artifact_ids=("entry",), argv=argv),
        (artifact, *extras),
        inputs or {},
    )


def test_readonly_program_and_no_undeclared_checker():
    sentinel = Artifact(
        test_id="checker",
        path="sentinel",
        kind="static",
        digest=digest_bytes(b"secret"),
        data=b"secret",
    )
    result = stage(
        """
from pathlib import Path
try:
    Path(__file__).write_text('replaced')
except OSError:
    print('readonly')
print(Path('/runner/sentinel').exists())
print(Path('/workspace/nested/main.py').exists())
""",
        extras=(sentinel,),
    )
    assert result.process.stdout == b"readonly\nFalse\nFalse\n"
    assert not result.blockers


def test_literal_argv_and_nonzero_exit_retained():
    argument = "$(touch /workspace/owned); `id` ' \""
    result = stage(
        "import sys,json; print(json.dumps(sys.argv[1:])); sys.exit(7)",
        argv=(argument,),
    )
    assert json.loads(result.process.stdout) == [argument]
    assert result.process.exit_code == 7
    assert result.process.terminated and result.tree is not None
    assert not result.blockers


@pytest.mark.parametrize(
    "program,flag",
    [
        ("while True: print('x' * 4096, flush=True)", "output_limited"),
        ("import time; time.sleep(30)", "timed_out"),
    ],
)
def test_flood_timeout_stopped_before_capture(program, flag):
    result = stage(program, settings=config(timeout_seconds=1, stdout_limit_bytes=256))
    assert getattr(result.process, flag)
    assert result.process.terminated
    assert re.fullmatch("[0-9a-f]{64}", result.process.container_id)
    assert result.process.finished_ns <= result.snapshot_ns
    assert len(result.process.stdout) <= 256
    assert result.blockers
    # Exact owned container is gone after verified stop and cleanup.
    ids = checked(["docker", "ps", "-aq", "--no-trunc"]).decode().splitlines()
    assert result.process.container_id not in ids


@pytest.mark.parametrize(
    "change",
    [
        {"image_digest": "sha256:" + "f" * 64},
        {"platform": "linux/amd64"},
    ],
)
def test_missing_or_mismatched_image_blocks(change):
    with pytest.raises(RunnerError):
        stage("print('must not start')", settings=config(**change))


@pytest.mark.parametrize(
    "program",
    [
        "import os; os.symlink('/etc/passwd', '/workspace/unsafe')",
        "import os; os.mkfifo('/workspace/unsafe')",
        "import os; open('/workspace/a','w').write('x'); os.link('/workspace/a','/workspace/b')",
    ],
)
def test_unsafe_output_is_not_materialized_on_host(program):
    result = stage(program)
    assert result.process.terminated
    assert result.tree is None and result.snapshot_ns is None
    assert result.blockers


@pytest.mark.parametrize(
    "program,change",
    [
        (
            "open('/workspace/full','wb').write(b'x' * 2097152)",
            {"output_tree_limit_bytes": 65536},
        ),
        (
            "from pathlib import Path\nfor i in range(100): Path('/workspace/'+str(i)).touch()",
            {"output_tree_file_limit": 16},
        ),
    ],
)
def test_real_workspace_quota_failure_never_success(program, change):
    result = stage(program, settings=config(**change))
    assert result.process.terminated
    assert result.tree is None
    assert result.blockers


def test_wrong_artifact_digest_and_arbitrary_mount_rejected():
    data = b"print('must not execute')"
    bad = Artifact(
        test_id="entry",
        path="main.py",
        kind="behavioral",
        digest="sha256:" + "0" * 64,
        data=data,
    )
    runner = DockerRunner(config())
    invocation = Invocation(test_id="entry", artifact_ids=("entry",), argv=())
    with pytest.raises(RunnerError):
        runner.run_stage("sha256:" + "a" * 64, invocation, (bad,), {})
    with pytest.raises(RunnerError):
        stage("print('must not execute')", inputs={"/etc/passwd": b"x"})


def test_readonly_tree_inputs_and_exact_modes(tmp_path):
    (tmp_path / "original").write_bytes(b"immutable")
    (tmp_path / "original").chmod(0o640)
    tmp_path.chmod(0o750)
    initial = capture_tree(tmp_path, config())
    result = stage(
        """
from pathlib import Path
try:
    Path('/inputs/initial/original').write_text('changed')
except OSError:
    print('readonly')
print(Path('/inputs/task.json').read_text())
""",
        inputs={"initial": initial, "task": b'{"task":"value"}'},
    )
    assert result.process.stdout == b'readonly\n{"task":"value"}\n'
    assert initial.files == (("original", b"immutable"),)


@pytest.mark.parametrize(
    "bad_name", ["./../escaped", "./a/../escaped", "././alias", "/absolute", "./a//b"]
)
def test_tar_traversal_and_alias_rejected(bad_name):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        root = tarfile.TarInfo(".")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        entry = tarfile.TarInfo(bad_name)
        entry.size = 1
        archive.addfile(entry, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        read_tar(stream.getvalue(), config(), docker=True)


def test_modified_frozen_tree_never_materialized(tmp_path):
    (tmp_path / "original").write_bytes(b"immutable")
    initial = capture_tree(tmp_path, config())
    invalid = FrozenTree(initial.snapshot, (("original", b"changed"),))
    with pytest.raises(RunnerError):
        stage("print('must not start')", inputs={"initial": invalid})


@pytest.mark.parametrize("failure_command", ["cp", "inspect"])
def test_control_failure_preserves_capture_and_cleans_exact_resources(
    monkeypatch, failure_command
):
    original = DockerLifecycle.control
    original_create = DockerLifecycle.create
    owned = []
    calls = 0

    def create(self, *args):
        result = original_create(self, *args)
        owned.append(result)
        return result

    def control(self, *args, **kwargs):
        nonlocal calls
        if args[0] == failure_command and (failure_command == "cp" or len(owned) == 3):
            calls += 1
            if calls == 1:
                raise RunnerError("injected daemon failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DockerLifecycle, "create", create)
    monkeypatch.setattr(DockerLifecycle, "control", control)
    result = stage("print('actual output')")
    assert result.process.stdout == b"actual output\n"
    assert result.tree is None and result.blockers
    assert result.process.terminated is (failure_command == "cp")
    remaining = checked(["docker", "ps", "-aq", "--no-trunc"]).decode().splitlines()
    assert not set(owned).intersection(remaining)


def test_cleanup_failure_is_uncertain_and_retains_exact_refs(monkeypatch):
    original = DockerLifecycle.control

    def control(self, *args, **kwargs):
        if args[0] == "rm":
            raise RunnerError("injected remove failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DockerLifecycle, "control", control)
    result = stage("print('actual output')")
    assert result.tree is None and result.snapshot_ns is None
    assert result.retained_containers and result.retained_volumes
    assert result.process.stdout == b"actual output\n"
    # Only this test's exact retained resources, using actual checked Docker controls.
    for container in reversed(result.retained_containers):
        checked(["docker", "rm", "-f", container])
    for volume in result.retained_volumes:
        checked(["docker", "volume", "rm", volume])


def test_all_stages_restrict_privileges_and_fresh_identity(monkeypatch):
    original = DockerLifecycle.create
    configurations = []

    def create(self, *args):
        cid = original(self, *args)
        configurations.append(json.loads(self.control("inspect", cid))[0])
        return cid

    monkeypatch.setattr(DockerLifecycle, "create", create)
    first = stage("print('one')")
    second = stage("print('two')")
    assert first.process.container_id != second.process.container_id
    assert len({c["Id"] for c in configurations}) == 6
    for container in configurations:
        host = container["HostConfig"]
        assert host["ReadonlyRootfs"] and host["NetworkMode"] == "none"
        assert host["Memory"] == host["MemorySwap"] == 134217728
        assert host["PidsLimit"] == 32 and host["NanoCpus"] == 1000000000
        assert host["CapDrop"] == ["ALL"] and "no-new-privileges" in host["SecurityOpt"]
        assert container["Config"]["User"] == "65534:65534"
        assert not host["Privileged"] and host["PidMode"] != "host"
        assert not any(
            m["Destination"] == "/runner" and m["RW"] for m in container["Mounts"]
        )


def test_malformed_transport_fails_closed():
    with pytest.raises(RunnerError):
        DockerRunner(config()).run_stage("sha256:" + "a" * 64, {"test_id": "x"}, (), {})


def test_truncated_tar_never_certified():
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        root = tarfile.TarInfo(".")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        entry = tarfile.TarInfo("./a")
        entry.size = 1024
        archive.addfile(entry, io.BytesIO(b"x" * 1024))
    with pytest.raises(RunnerError):
        read_tar(stream.getvalue()[:1200], config(), docker=True)


def test_workspace_directory_and_permission_changes_captured(tmp_path):
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "old").write_bytes(b"seed")
    seed = capture_tree(tmp_path, config())
    program = b"import os; os.unlink('/workspace/folder/old'); os.chmod('/workspace/folder',0o700); os.chmod('/workspace',0o711); open('/workspace/new','w').write('new')"
    result = DockerRunner(config()).run_stage(
        "sha256:" + "a" * 64,
        Invocation(test_id="entry", artifact_ids=("entry",), argv=()),
        (Artifact(test_id="entry", path="main.py", kind="behavioral", digest=digest_bytes(program), data=program),),
        {}, workspace=seed,
    )
    assert result.tree is not None
    assert dict(result.tree.files) == {"new": b"new"}
    assert {entry.path: entry.mode for entry in result.tree.snapshot.entries} == {".": 0o711, "folder": 0o700, "new": 0o644}


def test_actual_process_ceiling_observed():
    result = stage("""
import subprocess
children = []
try:
    for i in range(100):
        children.append(subprocess.Popen(['sleep','30']))
finally:
    for child in children:
        child.kill()
        child.wait()
""", settings=config(process_limit=8))
    assert b"Resource temporarily unavailable" in result.process.stderr
    assert result.process.terminated and result.tree is None and result.blockers


def test_caught_quota_still_full_blocks_success():
    result = stage("""
try:
    open('/workspace/full','wb').write(b'x' * 2097152)
except OSError:
    pass
""", settings=config(output_tree_limit_bytes=65536))
    assert result.process.exit_code == 0
    assert result.tree is None and result.blockers
