"""Bounded local Docker execution.

The runner deliberately treats Docker as an untrusted transport: every command
is an argv list, the image is addressed by digest, and output is collected
before the subject tree is handed to the trusted host.
"""
from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from contractcapsule.swap.process_io import bounded
from contractcapsule.swap.trees import RunnerError, capture_tree


@dataclass(frozen=True)
class ProcessResult:
    stdout: bytes
    stderr: bytes
    exit_code: int | None
    terminated: bool
    timed_out: bool = False
    output_limited: bool = False
    container_id: str = ""


@dataclass(frozen=True)
class DockerResult:
    process: ProcessResult
    tree: dict[str, bytes]
    snapshot: object


class DockerRunner:
    def __init__(self, config):
        self.config = config

    def _docker(self, *args: str, timeout: float | None = None):
        return bounded(["docker", *args], timeout=timeout or self.config.timeout_seconds,
                       out_limit=self.config.stdout_limit_bytes,
                       err_limit=self.config.stderr_limit_bytes)

    def execute(self, *, subject: str, program: str, files: dict[str, bytes]) -> DockerResult:
        if not subject.startswith("sha256:") or len(subject) != 71:
            raise RunnerError("invalid subject identity")
        with tempfile.TemporaryDirectory(prefix="ccs-m5-run-") as directory:
            root = Path(directory)
            (root / "runner").mkdir()
            workspace = root / "workspace"
            workspace.mkdir()
            for name, data in files.items():
                target = workspace / name
                if workspace not in target.parents or target == workspace:
                    raise RunnerError("unsafe input path")
                if target.is_symlink() or ".." in Path(name).parts:
                    raise RunnerError("unsafe input path")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(0o666)
            script = root / "runner" / "program.py"
            script.write_text(program, encoding="utf-8")
            volume = "ccs-m5-" + uuid.uuid4().hex
            seed = "ccs-m5-seed-" + uuid.uuid4().hex
            cidfile = root / "cid"
            self._docker("volume", "create", "--driver", "local", "--opt",
                         "type=tmpfs", "--opt", "device=tmpfs", "--opt",
                         f"o=size={self.config.output_tree_limit_bytes},nr_inodes={self.config.output_tree_file_limit},uid=65534,gid=65534,mode=0755",
                         volume)
            self._docker("run", "-d", "--name", seed, "--pull=never",
                         "--network=none", "--read-only", "--user", "65534:65534",
                         "--cap-drop=ALL", "--security-opt=no-new-privileges",
                         "-v", f"{volume}:/workspace:rw", "-v", f"{volume}:/runner:rw", self.config.image_digest,
                         "sleep", "300")
            for name, data in files.items():
                src = workspace / name
                self._docker("cp", str(src), f"{seed}:/workspace/{name}")
            self._docker("cp", str(script), f"{seed}:/runner/program.py")
            argv = [
                "run", "--pull=never", "--network=none", "--cidfile", str(cidfile),
                "--read-only", "--user=65534:65534", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--pids-limit",
                str(self.config.process_limit), "--cpus", str(self.config.cpu_limit),
                "--memory", str(self.config.memory_bytes), "--memory-swap",
                str(self.config.memory_bytes), "--platform", self.config.platform,
                "-v", f"{volume}:/workspace:rw", "-v", f"{volume}:/runner:ro", self.config.image_digest,
                "python", "-I", "/runner/program.py",
            ]
            out = self._docker(*argv)
            if out.exit_code == 125 or b"Cannot connect to the Docker daemon" in out.stderr:
                raise RunnerError("docker unavailable")
            try:
                container_id = cidfile.read_text(encoding="ascii").strip()
            except OSError as exc:
                raise RunnerError("container identity unavailable") from exc
            if not container_id:
                raise RunnerError("container identity unavailable")
            keeper = "ccs-m5-keeper-" + uuid.uuid4().hex
            self._docker("run", "-d", "--name", keeper, "--pull=never",
                         "--network=none", "--read-only", "--user", "65534:65534",
                         "--cap-drop=ALL", "-v", f"{volume}:/workspace:ro",
                         self.config.image_digest, "sleep", "300")
            exported = root / "exported"
            self._docker("cp", f"{keeper}:/workspace/.", str(exported))
            self._docker("rm", "-f", keeper)
            self._docker("rm", "-f", seed)
            self._docker("volume", "rm", volume)
            snapshot = capture_tree(exported, self.config)
            process = ProcessResult(
                stdout=out.stdout, stderr=out.stderr, exit_code=out.exit_code,
                terminated=out.exit_code is not None, timed_out=out.timed_out,
                output_limited=out.limited, container_id=container_id,
            )
            return DockerResult(
                process=process,
                tree={name: data for name, data in snapshot.files},
                snapshot=snapshot.snapshot,
            )
