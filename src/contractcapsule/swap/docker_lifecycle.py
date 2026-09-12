"""Bounded checked Docker controls and exact owned-resource cleanup."""

import json
import re
import uuid
from pathlib import Path
from typing import Any

from contractcapsule.swap.process_io import bounded
from contractcapsule.swap.trees import RunnerError
from contractcapsule.validate.models import RunnerConfig

INITIALIZER = """import os, shutil
shutil.copytree('/seed', '/workspace', dirs_exist_ok=True, copy_function=shutil.copyfile)
for root, dirs, files in os.walk('/seed', topdown=False):
    for name in files + dirs:
        source = os.path.join(root, name)
        os.chmod('/workspace' + source[len('/seed'):], os.stat(source).st_mode & 0o7777)
os.chmod('/workspace', os.stat('/seed').st_mode & 0o7777)
"""
QUOTA = "import os,json; s=os.statvfs('/workspace'); print(json.dumps([s.f_bavail,s.f_favail]))"


class DockerLifecycle:
    def __init__(self, config: RunnerConfig) -> None:
        self.config = config
        self.containers: list[str] = []
        self.volumes: list[str] = []
        self.keeper = ""

    def control(self, *args: str, out_limit: int = 1048576) -> bytes:
        output = bounded(
            ["docker", *args], timeout=15, out_limit=out_limit, err_limit=1048576
        )
        if output.exit_code != 0 or output.timed_out or output.limited:
            raise RunnerError(f"Docker control failed: {args[0]}")
        return output.stdout

    def preflight(self) -> None:
        try:
            payload = json.loads(self.control("image", "inspect", self.config.image_digest))
            if type(payload) is not list or len(payload) != 1 or type(payload[0]) is not dict:
                raise ValueError("malformed image inspection")
            image = payload[0]
            image_id, operating_system = image["Id"], image["Os"]
            architecture = image["Architecture"]
            if not all(type(value) is str for value in (image_id, operating_system, architecture)):
                raise ValueError("malformed image identity")
            platform = operating_system + "/" + architecture
            if image_id != self.config.image_digest or platform != self.config.platform:
                raise RunnerError("image identity/platform mismatch")
        except RunnerError:
            raise
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise RunnerError("malformed image inspection") from exc

    def flags(self) -> list[str]:
        return [
            "--pull=never",
            "--network=none",
            "--read-only",
            "--user=65534:65534",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit",
            str(self.config.process_limit),
            "--cpus",
            str(self.config.cpu_limit),
            "--memory",
            str(self.config.memory_bytes),
            "--memory-swap",
            str(self.config.memory_bytes),
            "--platform",
            self.config.platform,
            "--log-driver=none",
            "--ipc=none",
            "--workdir=/workspace",
        ]

    def create(self, mounts: list[str], command: list[str]) -> str:
        # Keep the exact random name if creation succeeds but the response is lost.
        name = "ccs-m5-stage-" + uuid.uuid4().hex
        self.containers.append(name)
        raw = (
            self.control(
                "create",
                "--name",
                name,
                *self.flags(),
                *mounts,
                self.config.image_digest,
                *command,
            )
            .decode()
            .strip()
        )
        if not re.fullmatch(r"[0-9a-f]{64}", raw):
            raise RunnerError("container identity missing")
        self.containers[-1] = raw
        return raw

    def prepare(self, root: Path, entry: str, argv: tuple[str, ...]) -> str:
        volume = "ccs-m5-" + uuid.uuid4().hex
        self.volumes.append(volume)
        options = (
            f"size={self.config.output_tree_limit_bytes},"
            f"nr_inodes={self.config.output_tree_file_limit},"
            "uid=65534,gid=65534,mode=0755"
        )
        self.control(
            "volume",
            "create",
            "--driver",
            "local",
            "--opt",
            "type=tmpfs",
            "--opt",
            "device=tmpfs",
            "--opt",
            f"o={options}",
            volume,
        )
        writable = ["--mount", f"type=volume,src={volume},dst=/workspace,volume-nocopy"]
        readonly = [
            "--mount",
            f"type=volume,src={volume},dst=/workspace,readonly,volume-nocopy",
        ]
        self.keeper = self.create(readonly, ["sleep", "infinity"])
        self.control("start", self.keeper)
        initializer = self.create(
            writable + self.bind(root / "seed", "/seed"),
            ["python", "-I", "-c", INITIALIZER],
        )
        self.control("start", "-a", initializer)
        state = self.state(initializer)
        if state["Running"] or state["Status"] != "exited" or state["ExitCode"] != 0:
            raise RunnerError("workspace initialization failed")
        return self.create(
            writable
            + self.bind(root / "runner", "/runner")
            + self.bind(root / "inputs", "/inputs"),
            ["python", "-I", "/runner/" + entry, *argv],
        )

    @staticmethod
    def bind(source: Path, destination: str) -> list[str]:
        return ["--mount", f"type=bind,src={source},dst={destination},readonly"]

    def state(self, container: str) -> dict[str, Any]:
        try:
            payload = json.loads(self.control("inspect", container))
            if type(payload) is not list or len(payload) != 1 or type(payload[0]) is not dict:
                raise ValueError("malformed container state")
            result = payload[0]
            state = result["State"]
            if type(state) is not dict or result["Id"] != container:
                raise ValueError("malformed container state")
            required = {"Running", "Status", "ExitCode", "OOMKilled", "Error"}
            if set(state) < required or type(state["Running"]) is not bool or type(state["Status"]) is not str or type(state["ExitCode"]) is not int or type(state["OOMKilled"]) is not bool or type(state["Error"]) is not str:
                raise ValueError("malformed container state")
            return state
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise RunnerError("malformed container state") from exc

    def check_quota(self, stderr: bytes) -> None:
        free = json.loads(
            self.control("exec", self.keeper, "python", "-I", "-c", QUOTA)
        )
        if (
            len(free) != 2
            or min(free) <= 0
            or b"No space left on device" in stderr
            or b"Resource temporarily unavailable" in stderr
        ):
            raise RunnerError("workspace/process resource ceiling observed")

    def cleanup(self) -> tuple[str, ...]:
        errors = []
        for container in tuple(reversed(self.containers)):
            try:
                self.control("rm", "-f", container)
                self.containers.remove(container)
            except (OSError, ValueError):
                errors.append("container cleanup uncertain")
        if self.containers:
            return tuple(errors)
        for volume in tuple(self.volumes):
            try:
                attachments = self.control("ps", "-aq", "--filter", f"volume={volume}")
                if attachments.strip():
                    raise RunnerError("workspace still attached")
                self.control("volume", "rm", volume)
                self.volumes.remove(volume)
            except (OSError, ValueError):
                errors.append("volume cleanup uncertain")
        return tuple(errors)
