"""Strict, condition-blind CapsuleBench metadata models.

Task records describe screened inputs only.  Human approval and immutable
source locks are explicit fields so a generated candidate cannot be mistaken
for benchmark ground truth.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, PrivateAttr, field_validator, model_validator

from contractcapsule.models.base import (
    Digest,
    NonEmptyString,
    StrictFrozenModel,
    is_safe_relative_path,
)

TaskId = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)+$")]
Category = Literal["policy", "api", "architecture", "procedure"]
Approval = Literal["pending", "approved", "excluded"]
SourceStatus = Literal["verified", "unverified", "unavailable"]
_CONDITION_TOKEN = re.compile(r"(?<![A-Za-z0-9_])(?:B[0-4]|CC)(?![A-Za-z0-9_])")


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    EXCLUDED = "excluded"


class RepositoryLock(StrictFrozenModel):
    source_url: Annotated[str, Field(pattern=r"^https://[^\s]+$")]
    commit: str | None = None
    license: NonEmptyString
    source_status: SourceStatus
    content_digest: Digest | None = None

    @field_validator("commit")
    @classmethod
    def _commit_shape(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is None:
            raise ValueError("repository commit must be a lowercase immutable hash")
        return value

    @model_validator(mode="after")
    def _lock_status(self) -> RepositoryLock:
        if self.source_status == "verified" and (self.commit is None or self.content_digest is None):
            raise ValueError("verified repository locks require commit and digest")
        if self.source_status != "verified" and self.commit is not None:
            raise ValueError("unverified repository locks must not claim a commit")
        return self


class CheckSpec(StrictFrozenModel):
    check_id: NonEmptyString
    command: tuple[NonEmptyString, ...]
    cwd: str = "."
    timeout_seconds: float = Field(default=120.0, gt=0, le=900)
    shell: Literal[False] = False

    @field_validator("command")
    @classmethod
    def _safe_command(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any("\x00" in item for item in value):
            raise ValueError("check command must be non-empty and NUL-free")
        if any(_CONDITION_TOKEN.search(item) for item in value):
            raise ValueError("condition labels must not enter gold checks")
        for item in value:
            if item.startswith(("/", "\\")) or "\\" in item or any(
                part == ".." for part in item.split("/")
            ):
                raise ValueError("check command paths must remain repository-relative")
        return value

    @field_validator("cwd")
    @classmethod
    def _safe_cwd(cls, value: str) -> str:
        if value == ".":
            return value
        parts = value.split("/")
        if not value or value.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("check cwd must be repository-relative")
        return value


class GoldChecks(StrictFrozenModel):
    target: tuple[CheckSpec, ...] = ()
    invariant: tuple[CheckSpec, ...] = ()
    spillover: tuple[CheckSpec, ...] = ()

    @model_validator(mode="after")
    def _nonempty_for_approved(self) -> GoldChecks:
        return self


class TaskSpec(StrictFrozenModel):
    # Loader provenance is deliberately private: it is not part of the task
    # identity, but execution/scoring must reject caller-forged schema models.
    _loader_attestation: object | None = PrivateAttr(default=None)
    _loader_root: Path | None = PrivateAttr(default=None)
    _loader_package_digest: str | None = PrivateAttr(default=None)

    task_id: TaskId
    category: Category
    language: NonEmptyString
    repository: RepositoryLock
    human_approval: ApprovalStatus = ApprovalStatus.PENDING
    executable: bool = False
    max_runtime_seconds: float = Field(gt=0, le=900)
    checks: GoldChecks = GoldChecks()
    p0_paths: tuple[NonEmptyString, ...] = ()
    old_capsule_digest: Digest | None = None
    new_capsule_digest: Digest | None = None
    candidate_reason: NonEmptyString = "awaiting human source and truth review"

    @field_validator("human_approval", mode="before")
    @classmethod
    def _approval_enum(cls, value: object) -> ApprovalStatus:
        if isinstance(value, ApprovalStatus):
            return value
        if type(value) is str:
            try:
                return ApprovalStatus(value)
            except ValueError:
                pass
        raise ValueError("human_approval must be pending, approved, or excluded")

    @field_validator("p0_paths", mode="before")
    @classmethod
    def _p0_paths_tuple(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, list):
            value = tuple(value)
        if not isinstance(value, tuple):
            raise TypeError("p0_paths must be a tuple or list")
        if len(set(value)) != len(value):
            raise ValueError("p0_paths must be unique")
        if any(type(item) is not str or not is_safe_relative_path(item) for item in value):
            raise ValueError("p0_paths must remain repository-relative")
        return value

    @model_validator(mode="after")
    def _approval_boundary(self) -> TaskSpec:
        if self.human_approval is not ApprovalStatus.APPROVED and self.executable:
            raise ValueError("only human-approved tasks may be executable")
        if self.human_approval is ApprovalStatus.APPROVED:
            if self.repository.source_status != "verified":
                raise ValueError("approved tasks require a verified repository")
            if not self.checks.target or not self.checks.invariant or not self.checks.spillover:
                raise ValueError("approved tasks require target, invariant, and spillover checks")
        return self


class BenchmarkManifest(StrictFrozenModel):
    spec_version: Literal["CCS-2.1"] = "CCS-2.1"
    benchmark_version: NonEmptyString = "CapsuleBench-1.0-screening"
    status: Literal["screening", "frozen"] = "screening"
    max_view_tokens: int = Field(gt=0, le=2**31 - 1)
    tasks: tuple[TaskSpec, ...]
    manifest_digest: Digest | None = None

    @model_validator(mode="after")
    def _unique_tasks(self) -> BenchmarkManifest:
        ids = [task.task_id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark task IDs must be unique")
        if self.status == "frozen" and len(self.tasks) != 24:
            raise ValueError("frozen CapsuleBench v1.0 requires 24 tasks")
        if self.status == "frozen":
            if self.manifest_digest is None:
                raise ValueError("frozen benchmark requires a manifest digest")
            for task in self.tasks:
                if (
                    task.human_approval is not ApprovalStatus.APPROVED
                    or task.repository.source_status != "verified"
                    or task.repository.commit is None
                    or task.repository.content_digest is None
                    or not task.executable
                    or not task.checks.target
                    or not task.checks.invariant
                    or not task.checks.spillover
                ):
                    raise ValueError("frozen benchmark tasks require human-approved executable locks")
        return self
