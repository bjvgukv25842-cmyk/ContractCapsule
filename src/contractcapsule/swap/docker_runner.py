"""Host-only restricted stages; this service does not grant execution approval."""

from __future__ import annotations

import re
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from contractcapsule.swap.docker_lifecycle import DockerLifecycle
from contractcapsule.swap.process_io import Output, bounded
from contractcapsule.swap.staging import prepare_stage
from contractcapsule.swap.trees import FrozenTree, RunnerError, read_tar
from contractcapsule.validate.models import Artifact, Invocation, RunnerConfig
from contractcapsule.validate.run_models import ProcessCapture


@dataclass(frozen=True)
class StageResult:
    process: ProcessCapture
    tree: FrozenTree | None
    snapshot_ns: int | None
    blockers: tuple[str, ...] = ()
    retained_containers: tuple[str, ...] = ()
    retained_volumes: tuple[str, ...] = ()


# Import compatibility for the incomplete legacy twin module, not an approval API.
DockerResult = StageResult


class StageError(RunnerError):
    """Preparation failure with exact known resources needing reconciliation."""

    def __init__(self, message: str, lifecycle: DockerLifecycle) -> None:
        super().__init__(message)
        self.retained_containers = tuple(lifecycle.containers)
        self.retained_volumes = tuple(lifecycle.volumes)


class DockerRunner:
    def __init__(self, config: RunnerConfig) -> None:
        self.config = RunnerConfig.model_validate(config.model_dump())

    def execute(self, **kwargs: object) -> StageResult:
        """Reject the earlier unapproved program-string orchestration stub."""
        raise RunnerError("use verified host run_stage inputs")

    def run_stage(
        self,
        subject: str,
        invocation: Invocation,
        artifacts: tuple[Artifact, ...],
        inputs: Mapping[str, FrozenTree | bytes],
        workspace: FrozenTree | None = None,
    ) -> StageResult:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", subject):
            raise RunnerError("invalid stage identity")
        lifecycle = DockerLifecycle(self.config)
        result: StageResult | None = None
        failure: Exception | None = None
        with tempfile.TemporaryDirectory(prefix="ccs-m5-stage-") as directory:
            try:
                entry = prepare_stage(
                    Path(directory),
                    invocation,
                    artifacts,
                    inputs,
                    workspace,
                    self.config,
                )
                lifecycle.preflight()
                container = lifecycle.prepare(Path(directory), entry, invocation.argv)
                result = self._execute(subject, container, lifecycle)
            except (OSError, ValueError) as exc:
                failure = exc
            finally:
                cleanup = lifecycle.cleanup()
        if result is None:
            raise StageError(
                str(failure or "stage did not execute"), lifecycle
            ) from failure
        if cleanup:
            result = replace(
                result,
                tree=None,
                snapshot_ns=None,
                blockers=(*result.blockers, *cleanup),
                retained_containers=tuple(lifecycle.containers),
                retained_volumes=tuple(lifecycle.volumes),
            )
        return result

    def _execute(
        self, subject: str, container: str, lifecycle: DockerLifecycle
    ) -> StageResult:
        started = time.monotonic_ns()
        out = Output(b"", b"", None, False, False)
        stopped = False
        exit_code: int | None = None
        blockers: list[str] = []
        try:
            out = bounded(
                ["docker", "start", "-a", container],
                timeout=self.config.timeout_seconds,
                out_limit=self.config.stdout_limit_bytes,
                err_limit=self.config.stderr_limit_bytes,
            )
            if out.timed_out or out.limited:
                lifecycle.control("kill", container)
                blockers.append("timeout" if out.timed_out else "output limit")
            state = lifecycle.state(container)
            stopped = state["Running"] is False and state["Status"] == "exited"
            if not stopped:
                raise RunnerError("subject termination uncertain")
            exit_code = state["ExitCode"]
            if state["OOMKilled"] or state["Error"]:
                blockers.append("container resource or runtime failure")
        except (OSError, ValueError):
            blockers.append("container control or termination uncertain")
        finished = time.monotonic_ns()
        process = ProcessCapture(
            subject=subject,
            container_id=container,
            started_ns=started,
            finished_ns=finished,
            exit_code=exit_code,
            terminated=stopped,
            timed_out=out.timed_out,
            output_limited=out.limited,
            stdout=out.stdout,
            stderr=out.stderr,
        )
        tree, snapshot_ns = self._snapshot(lifecycle, process, blockers)
        return StageResult(process, tree, snapshot_ns, tuple(blockers))

    def _snapshot(
        self, lifecycle: DockerLifecycle, process: ProcessCapture, blockers: list[str]
    ) -> tuple[FrozenTree | None, int | None]:
        if not process.terminated:
            return None, None
        try:
            lifecycle.check_quota(process.stderr)
            size = self.config.output_tree_limit_bytes
            overhead = self.config.output_tree_file_limit * 4096 + 10240
            raw = lifecycle.control(
                "cp", f"{lifecycle.keeper}:/workspace/.", "-", out_limit=size + overhead
            )
            tree = read_tar(raw, self.config, docker=True)
            return tree, time.monotonic_ns()
        except (OSError, ValueError):
            blockers.append("workspace quota or capture failure")
            return None, None
