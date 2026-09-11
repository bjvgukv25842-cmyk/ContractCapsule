"""Small host orchestrator for paired reference executions.

It intentionally contains no activation or retry policy.  A pair is executed
with two fresh runner invocations and any infrastructure error aborts the pair.
"""
from __future__ import annotations

from dataclasses import dataclass

from contractcapsule.swap.docker_runner import DockerResult, DockerRunner
from contractcapsule.swap.trees import RunnerError


@dataclass(frozen=True)
class TwinResult:
    old: DockerResult
    new: DockerResult


class TwinRunner:
    def __init__(self, config):
        self.config = config

    def run_pair(
        self,
        *,
        subject: str,
        old_program: str,
        new_program: str,
        files: dict[str, bytes],
    ) -> TwinResult:
        old = DockerRunner(self.config).execute(
            subject=subject, program=old_program, files=dict(files)
        )
        try:
            new = DockerRunner(self.config).execute(
                subject=subject, program=new_program, files=dict(files)
            )
        except Exception as exc:
            raise RunnerError("paired execution incomplete") from exc
        if old.process.container_id == new.process.container_id:
            raise RunnerError("paired container identities must differ")
        return TwinResult(old=old, new=new)
