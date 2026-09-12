"""Authenticated, immutable outputs of the M5 twin runner."""

from __future__ import annotations

from typing import Literal

from contractcapsule.models.base import (
    Digest,
    NonEmptyString,
    StrictFrozenModel,
    TimestampString,
)
from contractcapsule.validate.approvals import Approval
from contractcapsule.validate.journal import RecordRef
from contractcapsule.validate.run_models import EvaluationContext, RepetitionReport


class AttemptManifest(StrictFrozenModel):
    operation_id: NonEmptyString
    binding_digest: Digest
    approval_digest: Digest
    source_commit: NonEmptyString
    context: EvaluationContext
    repetitions: tuple[int, ...]
    repetition_record: RecordRef
    created_at: TimestampString
    state: Literal["COMPLETE", "FAILED", "UNCERTAIN"]

    def payload_bytes(self) -> bytes:
        from contractcapsule.models.canonical import canonical_json_bytes

        return canonical_json_bytes(self.model_dump(mode="json"))


class TwinOutcome(StrictFrozenModel):
    manifest: AttemptManifest
    approval: Approval
    repetitions: RepetitionReport

    @property
    def valid(self) -> bool:
        return self.manifest.state == "COMPLETE" and self.repetitions.valid


class TwinFailure(StrictFrozenModel):
    operation_id: NonEmptyString
    code: NonEmptyString
    manifest: AttemptManifest | None = None
