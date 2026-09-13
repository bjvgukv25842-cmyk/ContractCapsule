"""Immutable attempt transport; only trusted journal/store verification authenticates."""

from typing import Literal

from contractcapsule.models.base import Digest, NonEmptyString, TimestampString
from contractcapsule.validate.approvals import Approval
from contractcapsule.validate.journal import RecordRef
from contractcapsule.validate.reports import (
    CompressionReport,
    EvidenceReport,
    IntegrityReport,
)
from contractcapsule.validate.run_models import (
    EvaluationContext,
    ProcessCapture,
    RepetitionReport,
    WireModel,
)


class AdmissionCheck(WireModel):
    checked_at: TimestampString
    policy_configuration: Digest
    approval_digest: Digest
    reports: tuple[IntegrityReport | EvidenceReport | CompressionReport, ...]


class StageRecord(WireModel):
    stage_id: NonEmptyString
    role: Literal["old", "new", "pair"]
    repetition: int
    process: ProcessCapture | None
    blockers: tuple[str, ...]
    retained_containers: tuple[str, ...] = ()
    retained_volumes: tuple[str, ...] = ()


class AttemptManifest(WireModel):
    operation_id: NonEmptyString
    scope: Digest
    binding_digest: Digest
    binding_payload: bytes
    approval_digest: Digest
    source_commit: NonEmptyString
    context: EvaluationContext | None
    repetitions: tuple[int, ...]
    repetition_record: RecordRef | None
    admissions: tuple[AdmissionCheck, ...]
    stages: tuple[StageRecord, ...]
    created_at: TimestampString
    state: Literal["COMPLETE", "FAILED", "UNCERTAIN"]
    blockers: tuple[str, ...]


class TwinOutcome(WireModel):
    manifest: AttemptManifest
    approval: Approval
    repetitions: RepetitionReport | None
    record: RecordRef

    @property
    def valid(self) -> bool:
        return (
            self.manifest.state == "COMPLETE"
            and self.repetitions is not None
            and self.repetitions.valid
        )


class TwinFailure(WireModel):
    operation_id: NonEmptyString
    code: NonEmptyString
