"""Immutable execution transport. Construction alone conveys no authority."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BeforeValidator,
    Field,
    InstanceOf,
    field_validator,
    model_validator,
)

from contractcapsule.models.base import (
    Digest,
    NonEmptyString,
    Principal,
    StrictFrozenModel,
)
from contractcapsule.models.view import CapsuleRef, TaskContext, ViewBudget
from contractcapsule.storage.registry import PublishedCapsule


def exact_publication(value: object) -> object:
    if type(value) is not PublishedCapsule:
        raise ValueError("exact PublishedCapsule required")
    return value


def exact_principal(value: object) -> object:
    if type(value) is not Principal:
        raise ValueError("exact Principal required")
    return value


def unique(value: tuple[str, ...]) -> tuple[str, ...]:
    if len(value) != len(set(value)):
        raise ValueError("duplicate identifier")
    return value


class Invocation(StrictFrozenModel):
    test_id: NonEmptyString
    artifact_ids: Annotated[tuple[NonEmptyString, ...], Field(min_length=1)]
    argv: tuple[str, ...]

    @field_validator("artifact_ids")
    @classmethod
    def _unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return unique(value)

    @field_validator("argv")
    @classmethod
    def _safe_args(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any("\x00" in item for item in value):
            raise ValueError("NUL in argv")
        return value

    @model_validator(mode="after")
    def _entry_in_subset(self) -> Invocation:
        if self.test_id not in self.artifact_ids:
            raise ValueError("entry point absent from artifact subset")
        return self


class SubjectProbe(Invocation):
    probe_id: NonEmptyString
    input_state: Literal["initial", "current", "old_final", "new_final"]


class CheckBinding(Invocation):
    check_id: NonEmptyString
    role: Literal[
        "precondition",
        "static",
        "behavioral",
        "target",
        "invariant",
        "spillover",
        "differential",
    ]
    phase: Literal["pre", "post", "pair"]
    clause_path: NonEmptyString
    clause_sha256: Digest
    subject_probes: tuple[SubjectProbe, ...]
    old_expected: bool | None = None
    new_expected: bool | None = None
    pair_expected: bool | None = None

    @model_validator(mode="after")
    def _expectations(self) -> CheckBinding:
        present = self.model_fields_set & {
            "old_expected",
            "new_expected",
            "pair_expected",
        }
        expected = (
            {"pair_expected"}
            if self.phase == "pair"
            else {"old_expected", "new_expected"}
        )
        if present != expected or any(getattr(self, name) is None for name in expected):
            raise ValueError("phase-specific expectations required")
        return self


class RunnerConfig(StrictFrozenModel):
    image_digest: Digest
    platform: Literal["linux/arm64", "linux/amd64"]
    profile: Literal["ccs-m5-docker/1.0.0"]
    cpu_limit: Annotated[int | float, Field(gt=0, le=1)]
    memory_bytes: Annotated[int, Field(ge=1, le=1073741824)]
    process_limit: Annotated[int, Field(ge=1, le=128)]
    timeout_seconds: Annotated[int, Field(ge=1, le=300)]
    stdout_limit_bytes: Annotated[int, Field(ge=1, le=4194304)]
    stderr_limit_bytes: Annotated[int, Field(ge=1, le=4194304)]
    output_tree_limit_bytes: Annotated[int, Field(ge=1, le=67108864)]
    output_tree_file_limit: Annotated[int, Field(ge=1, le=10000)]

    @field_validator("cpu_limit", mode="before")
    @classmethod
    def _exact_number(cls, value: object) -> object:
        if type(value) not in {int, float}:
            raise ValueError("CPU limit must be a JSON number")
        return value


class ExecutionProfile(StrictFrozenModel):
    profile: Literal["ccs-m5-execution/1.0.0"]
    replaces_ref: CapsuleRef
    accepts_interfaces: tuple[NonEmptyString, ...]
    checks: Annotated[tuple[CheckBinding, ...], Field(min_length=1)]
    executor: Invocation
    runner: RunnerConfig
    repetitions: Annotated[int, Field(ge=1, le=3)]

    @field_validator("accepts_interfaces")
    @classmethod
    def _unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return unique(value)


class ReplacementRequest(StrictFrozenModel):
    operation_id: NonEmptyString
    principal: Annotated[InstanceOf[Principal], BeforeValidator(exact_principal)]
    old: Annotated[InstanceOf[PublishedCapsule], BeforeValidator(exact_publication)]
    new: Annotated[InstanceOf[PublishedCapsule], BeforeValidator(exact_publication)]
    task: TaskContext
    source_repository: NonEmptyString
    source_commit: Annotated[
        str, Field(pattern=r"^(?:sha1:[0-9a-f]{40}|sha256:[0-9a-f]{64})$")
    ]
    budget: ViewBudget
    model_id: NonEmptyString
    tokenizer_profile: NonEmptyString
    renderer_version: NonEmptyString

    @model_validator(mode="after")
    def _repository(self) -> ReplacementRequest:
        if self.task.repository != self.source_repository:
            raise ValueError("source repository differs from task")
        return self


class Artifact(StrictFrozenModel):
    test_id: NonEmptyString
    path: NonEmptyString
    kind: Literal["static", "evidence", "behavioral", "compression"]
    digest: Digest
    data: bytes = Field(repr=False)


class BoundExecution(StrictFrozenModel):
    """Verified snapshot transport, not an execution/activation credential."""

    request: ReplacementRequest
    profile: ExecutionProfile
    artifacts: tuple[Artifact, ...]
