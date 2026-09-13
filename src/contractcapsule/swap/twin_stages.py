"""Actual per-repetition stages; no subject-provided output is a host verdict."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import cast

from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.models.view import CompiledView
from contractcapsule.swap.docker_runner import DockerRunner, StageError, StageResult
from contractcapsule.swap.trees import FrozenTree, RunnerError
from contractcapsule.swap.twin_models import StageRecord
from contractcapsule.validate.behavior import BehaviorService, HostRunRecorder
from contractcapsule.validate.models import BoundExecution, CheckBinding, Invocation
from contractcapsule.validate.run_models import (
    AgentRun,
    CheckCapture,
    DifferentialReport,
    EvaluationContext,
    PairEvidence,
    ProcessCapture,
    RunEvidence,
    RunRole,
    StageRole,
    identity,
    stage_subject,
)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate observation key")
        result[key] = value
    return result


def observed(capture: CheckCapture) -> bool | None:
    p = capture.process
    if p.exit_code != 0 or not p.terminated or p.timed_out or p.output_limited:
        return None
    try:
        value = json.loads(p.stdout, object_pairs_hook=_unique)
        if (
            type(value) is dict
            and set(value) == {"check_id", "observation"}
            and value["check_id"] == capture.check_id
            and type(value["observation"]) is bool
        ):
            return value["observation"]
    except (ValueError, UnicodeError):
        pass
    return None


@dataclass
class PairRunner:
    bound: BoundExecution
    context: EvaluationContext
    source: FrozenTree
    views: tuple[CompiledView, CompiledView]
    runner: DockerRunner
    recorder: HostRunRecorder
    behavior: BehaviorService
    fresh: Callable[[], None]
    stages: list[StageRecord] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    uncertain: bool = False

    def stage(
        self,
        role: StageRole,
        repetition: int,
        invocation: Invocation,
        stage_id: str,
        digests: tuple[str, ...],
        inputs: Mapping[str, FrozenTree | bytes],
        *,
        workspace: FrozenTree | None = None,
        probes: tuple[ProcessCapture, ...] = (),
    ) -> StageResult:
        self.fresh()
        subject = stage_subject(
            self.bound, self.context, role, repetition, stage_id, digests, probes
        )
        try:
            result = self.runner.run_stage(
                subject, invocation, self.bound.artifacts, inputs, workspace
            )
        except StageError as exc:
            self.uncertain |= bool(exc.retained_containers)
            self.stages.append(
                StageRecord(
                    stage_id=stage_id,
                    role=role,
                    repetition=repetition,
                    process=None,
                    blockers=("STAGE_UNAVAILABLE",),
                    retained_containers=exc.retained_containers,
                    retained_volumes=exc.retained_volumes,
                )
            )
            raise RunnerError("STAGE_UNAVAILABLE") from exc
        self.uncertain |= not result.process.terminated or bool(
            result.retained_containers
        )
        self.stages.append(
            StageRecord(
                stage_id=stage_id,
                role=role,
                repetition=repetition,
                process=result.process,
                blockers=result.blockers,
                retained_containers=result.retained_containers,
                retained_volumes=result.retained_volumes,
            )
        )
        self.blockers.extend(result.blockers)
        return result

    def checks(
        self,
        role: StageRole,
        index: int,
        phase: str,
        trees: dict[str, FrozenTree],
        digests: tuple[str, ...],
        captures: list[CheckCapture],
    ) -> None:
        for check in self.bound.profile.checks:
            if check.phase == phase:
                captures.append(self.check(role, index, check, trees, digests))

    def check(
        self,
        role: StageRole,
        index: int,
        check: CheckBinding,
        trees: dict[str, FrozenTree],
        digests: tuple[str, ...],
    ) -> CheckCapture:
        probes = []
        for probe in check.subject_probes:
            tree = trees[probe.input_state]
            result = self.stage(
                role,
                index,
                probe,
                probe.probe_id,
                (tree.snapshot.digest_value(),),
                {"current": tree},
                workspace=tree,
            )
            probes.append(result.process)
            if result.blockers or not result.process.terminated:
                raise RunnerError("PROBE_FAILED")
        inputs: dict[str, FrozenTree | bytes] = dict(trees)
        if role != "pair":
            inputs["view"] = canonical_json_bytes(
                self.views[role == "new"].model_dump(mode="json")
            )
        inputs["observations"] = canonical_json_bytes(
            [p.model_dump(mode="json") for p in probes]
        )
        result = self.stage(
            role, index, check, check.check_id, digests, inputs, probes=tuple(probes)
        )
        return CheckCapture(
            check_id=check.check_id, process=result.process, probes=tuple(probes)
        )

    def role(
        self, role: RunRole, index: int, checks: list[CheckCapture], execute: bool
    ) -> tuple[AgentRun, FrozenTree | None]:
        result: StageResult | None = None
        try:
            if execute:
                inputs = {
                    "task": canonical_json_bytes(
                        self.bound.request.task.model_dump(mode="json")
                    ),
                    "view": canonical_json_bytes(
                        self.views[role == "new"].model_dump(mode="json")
                    ),
                }
                result = self.stage(
                    role,
                    index,
                    self.bound.profile.executor,
                    "executor",
                    (self.context.initial.digest_value(),),
                    inputs,
                    workspace=self.source,
                )
                if result.tree is not None and not self.uncertain:
                    self.checks(
                        role,
                        index,
                        "post",
                        {"initial": self.source, "current": result.tree},
                        (
                            self.context.initial.digest_value(),
                            result.tree.snapshot.digest_value(),
                        ),
                        checks,
                    )
        except Exception:  # noqa: BLE001 - preserve actual partial stages before stopping.
            self.blockers.append("ROLE_ABORTED")
        evidence = RunEvidence(
            role=role,
            repetition=index,
            final=result.tree.snapshot if result and result.tree else None,
            snapshot_ns=result.snapshot_ns if result else None,
            executor=result.process if result else None,
            checks=tuple(checks),
        )
        return self.recorder.record_run(evidence), result.tree if result else None

    def pair(self, index: int) -> DifferentialReport:
        old_checks: list[CheckCapture] = []
        new_checks: list[CheckCapture] = []
        execute = False
        try:
            for role, pre_captures in (("old", old_checks), ("new", new_checks)):
                self.checks(
                    cast(RunRole, role),
                    index,
                    "pre",
                    {"initial": self.source, "current": self.source},
                    (self.context.initial.digest_value(),),
                    pre_captures,
                )
            execute = (
                all(observed(c) is True for c in (*old_checks, *new_checks))
                and not self.blockers
            )
        except Exception:  # noqa: BLE001 - missing stages stay missing.
            self.blockers.append("PRECONDITION_UNAVAILABLE")
        if not execute:
            self.blockers.append("PRECONDITION_FAILED")
        old, old_tree = self.role("old", index, old_checks, execute)
        new, new_tree = self.role(
            "new", index, new_checks, execute and not self.uncertain
        )
        captures: list[CheckCapture] = []
        if (
            old_tree is not None
            and new_tree is not None
            and self._post_complete(old_checks, new_checks)
            and not self.uncertain
        ):
            digests = (
                self.context.initial.digest_value(),
                old_tree.snapshot.digest_value(),
                new_tree.snapshot.digest_value(),
                identity(old.record.model_dump(mode="json")),
                identity(new.record.model_dump(mode="json")),
            )
            try:
                self.checks(
                    "pair",
                    index,
                    "pair",
                    {
                        "initial": self.source,
                        "old_final": old_tree,
                        "new_final": new_tree,
                    },
                    digests,
                    captures,
                )
            except Exception:  # noqa: BLE001 - exact partial paired checks are retained.
                self.blockers.append("PAIR_ABORTED")
        evidence = PairEvidence(
            repetition=index,
            old_record=old.record,
            new_record=new.record,
            checks=tuple(captures),
        )
        old, new = self.recorder.record_pair(old, new, evidence)
        return self.behavior.compare_runs(
            old, new, self.bound.request.new.capsule.replacement_contract
        )

    def _post_complete(self, *groups: list[CheckCapture]) -> bool:
        required = {c.check_id for c in self.bound.profile.checks if c.phase != "pair"}
        return all(
            {c.check_id for c in group} == required
            and all(observed(c) is not None for c in group)
            for group in groups
        )
