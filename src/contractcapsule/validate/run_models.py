"""Host observation transport and deterministic identities; none grants authority."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from contractcapsule.models.base import Digest, NonEmptyString, StrictFrozenModel
from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.validate.contracts import execution_subject
from contractcapsule.validate.journal import RecordRef
from contractcapsule.validate.models import BoundExecution

type RunRole = Literal["old", "new"]
type StageRole = Literal["old", "new", "pair"]
Natural = Annotated[int, Field(ge=0)]


def digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def identity(value: object) -> str:
    return digest_bytes(canonical_json_bytes(value))


class WireModel(StrictFrozenModel):
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    def payload_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"record"}))


class TreeEntry(WireModel):
    path: NonEmptyString
    kind: Literal["file", "directory"]
    mode: Annotated[int, Field(ge=0, le=0o7777)]
    digest: Digest | None = None
    size: Natural = 0


class Snapshot(WireModel):
    entries: tuple[TreeEntry, ...]

    def digest_value(self) -> str:
        return digest_bytes(self.payload_bytes())


class EvaluationContext(WireModel):
    """Trusted controller inputs, established before recording any run.

    Initial tree must be independently captured from the locked source commit;
    view digests cover complete verified views/locks, approval_digest the verified
    execution approval envelope. The evaluator never certifies their origin.
    """

    initial: Snapshot
    old_view_digest: Digest
    new_view_digest: Digest
    approval_digest: Digest
    synthetic: bool


def evaluation_scope(bound: BoundExecution) -> str:
    request = bound.request
    return identity(
        {
            "tenant": request.task.tenant,
            "principal": request.principal.principal_id,
            "repository": request.source_repository,
            "environment": request.task.environment,
        }
    )


def run_subject(
    bound: BoundExecution, context: EvaluationContext, role: StageRole, repetition: int
) -> str:
    return identity(
        {
            "domain": "ccs-m5-run/1",
            "execution": execution_subject(bound),
            "context": context.model_dump(mode="json"),
            "role": role,
            "repetition": repetition,
        }
    )


def stage_subject(
    bound: BoundExecution,
    context: EvaluationContext,
    role: StageRole,
    repetition: int,
    stage_id: str,
    inputs: tuple[str, ...],
    probes: tuple[ProcessCapture, ...] = (),
) -> str:
    return identity(
        {
            "domain": "ccs-m5-stage/1",
            "run": run_subject(bound, context, role, repetition),
            "stage_id": stage_id,
            "inputs": inputs,
            "probes": [p.model_dump(mode="json") for p in probes],
        }
    )


class ProcessCapture(WireModel):
    subject: Digest
    container_id: NonEmptyString
    started_ns: Natural
    finished_ns: Natural
    exit_code: int | None
    terminated: bool
    timed_out: bool
    output_limited: bool
    stdout: bytes = Field(repr=False)
    stderr: bytes = Field(repr=False)


class CheckCapture(WireModel):
    check_id: NonEmptyString
    process: ProcessCapture
    probes: tuple[ProcessCapture, ...]


class RunEvidence(WireModel):
    role: RunRole
    repetition: Natural
    final: Snapshot | None
    snapshot_ns: Natural | None
    executor: ProcessCapture | None
    checks: tuple[CheckCapture, ...]


class CompletedRunEvidence(RunEvidence):
    """Internal evaluator shape; incomplete attempts remain stored as RunEvidence."""

    final: Snapshot
    snapshot_ns: Natural
    executor: ProcessCapture


class PairEvidence(WireModel):
    repetition: Natural
    old_record: RecordRef
    new_record: RecordRef
    checks: tuple[CheckCapture, ...]


class AgentRun(WireModel):
    role: RunRole
    repetition: Natural
    record: RecordRef
    pair_record: RecordRef | None = None


class Count(WireModel):
    numerator: Natural
    denominator: Natural


class CheckTrace(WireModel):
    check_id: NonEmptyString
    role: NonEmptyString
    observation: bool | None
    expected: bool
    valid: bool


class ContractReport(WireModel):
    kind: Literal["contract"] = "contract"
    valid: bool
    blockers: tuple[str, ...]
    run: AgentRun
    ter: Count
    pip: Count
    bsr: Count
    traces: tuple[CheckTrace, ...]
    record: RecordRef | None = None


class DifferentialReport(WireModel):
    kind: Literal["differential"] = "differential"
    valid: bool
    blockers: tuple[str, ...]
    old: AgentRun
    new: AgentRun
    old_report: ContractReport
    new_report: ContractReport
    traces: tuple[CheckTrace, ...]
    initial_to_old: tuple[str, ...] = ()
    initial_to_new: tuple[str, ...] = ()
    old_to_new: tuple[str, ...] = ()
    record: RecordRef | None = None


class RepetitionReport(WireModel):
    kind: Literal["repetitions"] = "repetitions"
    valid: bool
    blockers: tuple[str, ...]
    pairs: tuple[DifferentialReport, ...]
    record: RecordRef | None = None
