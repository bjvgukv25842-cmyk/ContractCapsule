"""Public diagnostic reports are data; only the stored authenticated bytes attest."""

from typing import Literal

from pydantic import model_validator

from contractcapsule.models.base import Digest, StrictFrozenModel, TimestampString
from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.models.view import StringSet, TokenAccounting
from contractcapsule.validate.journal import RecordRef


class IndependentReport(StrictFrozenModel):
    kind: Literal["integrity", "evidence", "compression"]
    valid: bool
    blockers: StringSet = ()
    validated_at: TimestampString | None
    scope_digest: Digest | None = None
    subject_digest: Digest | None = None
    tokens: TokenAccounting | None = None
    record: RecordRef | None = None

    @model_validator(mode="after")
    def _consistent(self):
        if self.valid != (not self.blockers):
            raise ValueError("inconsistent validation")
        if self.valid and (
            self.scope_digest is None
            or self.subject_digest is None
            or self.validated_at is None
        ):
            raise ValueError("valid reports require exact binding")
        return self

    def payload_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"record"}))


class IntegrityReport(IndependentReport):
    kind: Literal["integrity"] = "integrity"


class EvidenceReport(IndependentReport):
    kind: Literal["evidence"] = "evidence"


class CompressionReport(IndependentReport):
    kind: Literal["compression"] = "compression"
