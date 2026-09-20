"""Strict, replayable models for M7 experiment runs.

The models deliberately keep agent metadata optional.  An unavailable binary
must be represented as unavailable rather than replaced with a guessed model
or version, and a run record is append-only once emitted.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")


class ExperimentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _tuplify(value: Any) -> Any:
    """Normalize JSON/YAML arrays before strict tuple validation."""

    if isinstance(value, list):
        return tuple(_tuplify(item) for item in value)
    if isinstance(value, dict):
        return {key: _tuplify(item) for key, item in value.items()}
    return value


class UsageRecord(ExperimentModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    raw_digest: str | None = None

    @field_validator("raw_digest")
    @classmethod
    def _valid_digest(cls, value: str | None) -> str | None:
        if value is not None and _DIGEST.fullmatch(value) is None:
            raise ValueError("raw_digest must be a sha256 digest")
        return value


class ExperimentConfig(ExperimentModel):
    """Validated study configuration.

    Fields are intentionally conservative.  Unknown keys are rejected both
    when constructing the model and when loading YAML/JSON, preventing a
    misspelled budget or execution flag from silently changing a study.
    """

    study_id: str = Field(min_length=1, max_length=120)
    agent: str = Field(min_length=1, max_length=120)
    model: str | None = Field(default=None, max_length=240)
    version: str | None = Field(default=None, max_length=240)
    conditions: tuple[str, ...] = ("B0", "B1", "B2", "B3", "B4", "CC")
    repetitions: int = Field(default=1, ge=1, le=100)
    runtime_budget_tokens: int = Field(default=1, ge=1, le=10_000_000)
    timeout_seconds: float = Field(default=900.0, gt=0, le=3600)
    output_path: Path = Path("results/raw/runs.jsonl")
    raw_output_dir: Path | None = None
    manifest_path: Path | None = None
    binary: str | None = Field(default=None, max_length=512)
    dry_run: bool = True
    live_agent: bool = False
    preflight_receipt: Path | None = None
    adapter: str | None = None

    @field_validator("study_id", "agent")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("configuration strings must not be blank")
        return value

    @field_validator("conditions", mode="before")
    @classmethod
    def _conditions(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, list):
            value = tuple(value)
        if not isinstance(value, tuple):
            raise TypeError("conditions must be a tuple or list")
        if not value or len(set(value)) != len(value):
            raise ValueError("conditions must be non-empty and unique")
        allowed = {"B0", "B1", "B2", "B3", "B4", "CC"}
        if any(item not in allowed for item in value):
            raise ValueError("unknown experiment condition")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _finite_timeout(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("timeout_seconds must be finite")
        return value

    @field_validator("output_path", "raw_output_dir", "manifest_path", "preflight_receipt", mode="before")
    @classmethod
    def _path_value(cls, value: object) -> object:
        if value is None or isinstance(value, Path):
            return value
        if isinstance(value, str) and value and "\x00" not in value:
            return Path(value)
        raise ValueError("path must be a string or Path")

    @model_validator(mode="after")
    def _execution_boundary(self) -> ExperimentConfig:
        if self.live_agent and self.dry_run:
            raise ValueError("live_agent cannot be enabled in dry-run mode")
        if self.live_agent and self.preflight_receipt is None:
            raise ValueError("live_agent requires preflight_receipt")
        return self

    @property
    def digest(self) -> str:
        payload = self.model_dump(mode="json")
        return _digest(_canonical(payload))


class PreflightReceipt(ExperimentModel):
    """Immutable evidence that an adapter preflight was attempted."""

    schema_version: Literal["M7-1"] = "M7-1"
    created_at: str = Field(default_factory=_now)
    config_digest: str
    agent: str
    version: str | None = None
    model: str | None = None
    binary: str | None = None
    capabilities: tuple[str, ...] = ()
    available: bool = False
    error_code: str | None = None
    signature: str | None = None
    digest: str | None = None

    @field_validator("capabilities", mode="before")
    @classmethod
    def _capability_tuple(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, list):
            value = tuple(value)
        if not isinstance(value, tuple):
            raise TypeError("capabilities must be a tuple or list")
        return value

    @field_validator("config_digest", "digest")
    @classmethod
    def _receipt_digest(cls, value: str | None) -> str | None:
        if value is not None and _DIGEST.fullmatch(value) is None:
            raise ValueError("receipt digest must be sha256")
        return value

    @model_validator(mode="after")
    def _availability(self) -> PreflightReceipt:
        if self.available and (not self.version or not self.model):
            raise ValueError("available receipt requires observed version and model")
        if self.available and self.error_code is not None:
            raise ValueError("available receipt cannot carry an error")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude={"digest", "signature"})
        return payload

    def computed_digest(self) -> str:
        return _digest(_canonical(self.unsigned_payload()))


class RunRecord(ExperimentModel):
    """One immutable logical attempt and its observed outcome."""

    run_id: str
    attempt_id: str = ""
    retry_of: str | None = None
    attempt_number: int = Field(default=0, ge=0)
    task_id: str
    condition: str
    agent: str
    repetition: int = Field(ge=0)
    repository_commit: str
    capsule_digests: tuple[str, ...] = ()
    prompt_digest: str
    view_manifest_digest: str | None = None
    raw_event_path: str
    exit_code: int = Field(ge=0)
    usage: UsageRecord = UsageRecord()
    infrastructure_failure: bool
    failure_code: str | None = None
    task_outcome: Literal["passed", "failed", "unknown"] = "unknown"
    adapter_metadata: Mapping[str, Any] = {}
    config_digest: str | None = None
    preflight_digest: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    @field_validator("capsule_digests", mode="before")
    @classmethod
    def _capsule_tuple(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, list):
            value = tuple(value)
        if not isinstance(value, tuple):
            raise TypeError("capsule_digests must be a tuple or list")
        return value

    @field_validator("run_id", "attempt_id", "task_id", "condition", "agent")
    @classmethod
    def _ids(cls, value: str) -> str:
        if not isinstance(value, str) or _ID.fullmatch(value) is None:
            raise ValueError("run identifiers must be bounded nonempty strings")
        return value

    @field_validator("raw_event_path")
    @classmethod
    def _raw_path(cls, value: str) -> str:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ValueError("raw_event_path must be a nonempty path")
        path = Path(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("raw_event_path must be normalized")
        return value

    @field_validator("repository_commit")
    @classmethod
    def _commit(cls, value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is None:
            raise ValueError("repository_commit must be an immutable hash")
        return value

    @field_validator("prompt_digest", "view_manifest_digest", "config_digest", "preflight_digest")
    @classmethod
    def _optional_digest(cls, value: str | None) -> str | None:
        if value is not None and _DIGEST.fullmatch(value) is None:
            raise ValueError("digest field must be sha256")
        return value

    @field_validator("capsule_digests")
    @classmethod
    def _capsule_digests(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_DIGEST.fullmatch(item) is None for item in value):
            raise ValueError("capsule digests must be sha256")
        return value

    @model_validator(mode="after")
    def _retry_link(self) -> RunRecord:
        if not self.attempt_id:
            object.__setattr__(
                self,
                "attempt_id",
                "attempt-" + hashlib.sha256(self.run_id.encode()).hexdigest(),
            )
        if self.attempt_number == 0 and self.retry_of is not None:
            raise ValueError("initial attempt cannot have retry_of")
        if self.attempt_number > 0 and self.retry_of is None:
            raise ValueError("retry attempts require retry_of")
        if (
            self.infrastructure_failure is False
            and self.failure_code is not None
            and self.failure_code.startswith(("INFRA_", "ADAPTER_", "PREFLIGHT_"))
        ):
            # A task failure may carry a task-specific code, but never an
            # infrastructure-coded prefix.
            raise ValueError("infrastructure code on a task outcome")
        return self

    @classmethod
    def new(
        cls,
        *,
        task_id: str,
        condition: str,
        agent: str,
        repetition: int,
        repository_commit: str,
        capsule_digests: list[str] | tuple[str, ...],
        prompt_digest: str,
        raw_event_path: str,
        exit_code: int,
        infrastructure_failure: bool,
        view_manifest_digest: str | None = None,
        usage: UsageRecord | None = None,
        failure_code: str | None = None,
        task_outcome: Literal["passed", "failed", "unknown"] = "unknown",
        adapter_metadata: Mapping[str, Any] | None = None,
        config_digest: str | None = None,
        preflight_digest: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> RunRecord:
        identity = {
            "task_id": task_id,
            "condition": condition,
            "agent": agent,
            "repetition": repetition,
            "repository_commit": repository_commit,
            "capsule_digests": list(capsule_digests),
            "prompt_digest": prompt_digest,
            "view_manifest_digest": view_manifest_digest,
            "config_digest": config_digest,
        }
        run_id = "run-" + hashlib.sha256(_canonical(identity)).hexdigest()
        attempt_id = "attempt-" + hashlib.sha256(run_id.encode()).hexdigest()
        return cls(
            run_id=run_id,
            attempt_id=attempt_id,
            task_id=task_id,
            condition=condition,
            agent=agent,
            repetition=repetition,
            repository_commit=repository_commit,
            capsule_digests=tuple(capsule_digests),
            prompt_digest=prompt_digest,
            view_manifest_digest=view_manifest_digest,
            raw_event_path=raw_event_path,
            exit_code=exit_code,
            usage=usage or UsageRecord(),
            infrastructure_failure=infrastructure_failure,
            failure_code=failure_code,
            task_outcome=task_outcome,
            adapter_metadata=dict(adapter_metadata or {}),
            config_digest=config_digest,
            preflight_digest=preflight_digest,
            started_at=started_at,
            finished_at=finished_at,
        )

    def retry_attempt(self) -> RunRecord:
        if not self.infrastructure_failure:
            raise ValueError("only infrastructure failures may be retried")
        number = self.attempt_number + 1
        new_id = "run-" + hashlib.sha256(f"{self.run_id}:{number}".encode()).hexdigest()
        attempt_id = "attempt-" + hashlib.sha256(f"{self.attempt_id}:{number}".encode()).hexdigest()
        return self.model_copy(
            update={
                "run_id": new_id,
                "attempt_id": attempt_id,
                "retry_of": self.run_id,
                "attempt_number": number,
                "raw_event_path": f"raw/{new_id}.jsonl",
            }
        )


class RunStore:
    """Append-only JSONL store with idempotent duplicate writes."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._records: dict[str, RunRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("run store must be a regular file")
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as error:
            raise ValueError("unable to read run store") from error
        for line in lines:
            if not line.strip():
                raise ValueError("blank JSONL run record")
            try:
                value = json.loads(line, object_pairs_hook=_unique_pairs)
                record = RunRecord.model_validate(_tuplify(value))
            except Exception as error:
                raise ValueError("invalid run record") from error
            if record.run_id in self._records:
                raise ValueError("duplicate run_id in run store")
            self._records[record.run_id] = record

    @property
    def records(self) -> tuple[RunRecord, ...]:
        return tuple(self._records.values())

    def get(self, run_id: str) -> RunRecord | None:
        return self._records.get(run_id)

    def append(self, record: RunRecord) -> RunRecord:
        if not isinstance(record, RunRecord):
            raise TypeError("run store accepts RunRecord values")
        existing = self._records.get(record.run_id)
        if existing is not None:
            if existing == record:
                return existing
            raise ValueError("existing run_id cannot be overwritten")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        try:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise ValueError("unable to append run record") from error
        self._records[record.run_id] = record
        return record

    def retry_eligible(self, run_id: str) -> bool:
        record = self._records.get(run_id)
        return bool(record is not None and record.infrastructure_failure)

    # Explicit aliases keep the storage boundary discoverable for replay
    # scripts without introducing a second write path.
    def append_record(self, record: RunRecord) -> RunRecord:
        return self.append(record)

    def can_retry(self, run_id: str) -> bool:
        return self.retry_eligible(run_id)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class ConfigError(ValueError):
    """A config file failed strict parsing."""


class _UniqueLoader(yaml.SafeLoader):
    pass


def _yaml_mapping(loader: _UniqueLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ConfigError("duplicate YAML key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping)


def load_config(source: Path | str | Mapping[str, Any] | ExperimentConfig) -> ExperimentConfig:
    if isinstance(source, ExperimentConfig):
        return source
    if isinstance(source, Mapping):
        raw = dict(source)
    else:
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ConfigError("unable to read config") from error
        try:
            if path.suffix.lower() == ".json":
                raw = json.loads(text, object_pairs_hook=_unique_pairs)
            else:
                raw = yaml.load(text, Loader=_UniqueLoader)
        except (json.JSONDecodeError, yaml.YAMLError, ValueError) as error:
            raise ConfigError("invalid config syntax") from error
        if not isinstance(raw, Mapping):
            raise ConfigError("config root must be an object")
        raw = dict(raw)
    try:
        return ExperimentConfig.model_validate(_tuplify(raw))
    except Exception as error:
        raise ConfigError("config schema validation failed") from error


__all__ = [
    "ConfigError",
    "ExperimentConfig",
    "PreflightReceipt",
    "RunRecord",
    "RunStore",
    "UsageRecord",
    "load_config",
]
