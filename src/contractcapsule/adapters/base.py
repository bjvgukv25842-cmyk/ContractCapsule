"""Bounded, non-interactive process contracts for coding-agent adapters.

Adapters are deliberately a thin process boundary.  They do not resolve
capsules, grant permissions, or activate replacements; they only pass a
validated compiled view to an explicitly selected executable and return safe
metadata plus hashes for operational output.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Protocol

from pydantic import Field, field_validator

from contractcapsule.models.base import Digest, NonEmptyString, StrictFrozenModel
from contractcapsule.models.view import CompiledView

MAX_STDOUT_BYTES = 1024 * 1024
MAX_EVENT_BYTES = 8 * 1024 * 1024
MAX_TIMEOUT_SECONDS = 300.0
ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
_VERSION_PATTERN = re.compile(r"(?<![0-9])\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]+)?")
_MODEL_PATTERN = re.compile(
    r"(?:model|engine)\s*[:=]\s*([A-Za-z0-9_.:/-]+)", re.IGNORECASE
)


class AdapterError(RuntimeError):
    """Public, non-disclosing adapter failure.

    Only a stable machine-readable code is retained.  Operational output,
    prompts, executable paths, and environment values never enter the error
    message.
    """

    def __init__(self, code: str) -> None:
        if type(code) is not str or re.fullmatch(r"[A-Z][A-Z0-9_.-]*", code) is None:
            raise ValueError("adapter error requires a stable uppercase code")
        self.code = code
        super().__init__(code)


class AgentMetadata(StrictFrozenModel):
    agent: NonEmptyString
    version: NonEmptyString
    model: NonEmptyString
    capabilities: tuple[NonEmptyString, ...] = ()

    @field_validator("capabilities")
    @classmethod
    def _stable_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("capabilities must not contain duplicates")
        return tuple(sorted(value))


class AgentTask(StrictFrozenModel):
    task_id: NonEmptyString
    prompt: NonEmptyString
    cwd: Path
    timeout_seconds: float = Field(gt=0, le=MAX_TIMEOUT_SECONDS)

    @field_validator("cwd", mode="before")
    @classmethod
    def _absolute_cwd(cls, value: object) -> object:
        if not isinstance(value, Path) or not value.is_absolute():
            raise ValueError("task cwd must be an absolute Path")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _finite_timeout(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("task timeout must be finite")
        return value


class UsageRecord(StrictFrozenModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    raw_digest: Digest


class AgentRun(StrictFrozenModel):
    metadata: AgentMetadata
    exit_code: int = Field(ge=0)
    stdout: bytes
    stderr_digest: Digest
    usage: UsageRecord | None = None


class AgentAdapter(Protocol):
    def preflight(self) -> AgentMetadata: ...

    def run(self, task: AgentTask, view: CompiledView, workspace: Path) -> AgentRun: ...

    def parse_usage(self, raw_events: Path) -> UsageRecord: ...


@dataclass(frozen=True, slots=True)
class _ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _safe_environment() -> dict[str, str]:
    """Construct a minimal environment instead of inheriting secrets."""

    return {key: value for key in ENV_ALLOWLIST if (value := os.environ.get(key)) is not None}


def _run_bounded(
    argv: Sequence[str], *, cwd: Path, timeout_seconds: float
) -> _ProcessResult:
    if not argv or any(type(item) is not str or not item for item in argv):
        raise AdapterError("ADAPTER_ARGUMENTS_INVALID")
    if not isinstance(cwd, Path) or not cwd.is_absolute() or not cwd.is_dir():
        raise AdapterError("ADAPTER_WORKSPACE_INVALID")
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
            env=_safe_environment(),
        )
    except FileNotFoundError as exc:
        raise AdapterError("ADAPTER_BINARY_NOT_FOUND") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdapterError("ADAPTER_TIMEOUT") from exc
    except (OSError, ValueError) as exc:
        raise AdapterError("ADAPTER_EXECUTION_FAILED") from exc
    return _ProcessResult(completed.returncode, completed.stdout, completed.stderr)


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _json_lines(raw: bytes) -> tuple[dict[str, Any], ...]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_EVENT_BYTES:
        raise AdapterError("ADAPTER_OUTPUT_INVALID")
    try:
        text = raw.decode("utf-8")
        records: list[dict[str, Any]] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            value = json.loads(line, object_pairs_hook=_json_pairs)
            if type(value) is not dict:
                raise ValueError("event must be an object")
            records.append(value)
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise AdapterError("ADAPTER_OUTPUT_INVALID") from exc
    if not records:
        raise AdapterError("ADAPTER_OUTPUT_INVALID")
    return tuple(records)


def _string_field(record: Mapping[str, Any], name: str) -> str | None:
    value = record.get(name)
    if value is None:
        return None
    if type(value) is not str or not value:
        raise AdapterError("ADAPTER_METADATA_INVALID")
    return value


def _metadata_record(record: Mapping[str, Any], expected_agent: str) -> AgentMetadata | None:
    candidate: Mapping[str, Any] = record
    nested = record.get("metadata")
    if nested is not None:
        if not isinstance(nested, Mapping):
            raise AdapterError("ADAPTER_METADATA_INVALID")
        candidate = nested
    elif isinstance(record.get("data"), Mapping):
        candidate = record["data"]
    fields = {"agent", "version", "model", "capabilities"}
    if not fields.intersection(candidate) and not {
        "agent_name",
        "agent_version",
        "model_id",
    }.intersection(candidate):
        return None
    agent = (
        _string_field(candidate, "agent")
        or _string_field(candidate, "agent_name")
        or expected_agent
    )
    version = _string_field(candidate, "version") or _string_field(
        candidate, "agent_version"
    )
    model = _string_field(candidate, "model") or _string_field(candidate, "model_id")
    if version is None or model is None or agent != expected_agent:
        raise AdapterError("ADAPTER_METADATA_INVALID")
    capabilities_value = candidate.get("capabilities", ())
    if not isinstance(capabilities_value, (list, tuple)) or any(
        type(item) is not str or not item for item in capabilities_value
    ):
        raise AdapterError("ADAPTER_METADATA_INVALID")
    try:
        return AgentMetadata(
            agent=agent,
            version=version,
            model=model,
            capabilities=tuple(capabilities_value),
        )
    except ValueError as exc:
        raise AdapterError("ADAPTER_METADATA_INVALID") from exc


def _usage_values(record: Mapping[str, Any]) -> tuple[int | None, int | None]:
    nested = record.get("usage")
    if nested is not None and not isinstance(nested, Mapping):
        raise AdapterError("ADAPTER_USAGE_INVALID")
    input_value: Any = None
    output_value: Any = None
    if isinstance(nested, Mapping):
        input_value = nested.get("input_tokens", nested.get("inputTokens"))
        output_value = nested.get("output_tokens", nested.get("outputTokens"))
    direct_input = record.get("input_tokens", record.get("inputTokens"))
    direct_output = record.get("output_tokens", record.get("outputTokens"))
    if input_value is not None and direct_input is not None:
        raise AdapterError("ADAPTER_USAGE_INVALID")
    if output_value is not None and direct_output is not None:
        raise AdapterError("ADAPTER_USAGE_INVALID")
    input_value = input_value if input_value is not None else direct_input
    output_value = output_value if output_value is not None else direct_output
    for value in (input_value, output_value):
        if value is not None and (type(value) is not int or value < 0):
            raise AdapterError("ADAPTER_USAGE_INVALID")
    return input_value, output_value


def _parse_events(
    raw: bytes, *, expected_agent: str, require_metadata: bool
) -> tuple[AgentMetadata | None, UsageRecord | None]:
    records = _json_lines(raw)
    metadata: AgentMetadata | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    usage_seen = False
    for record in records:
        current = _metadata_record(record, expected_agent)
        if current is not None:
            if metadata is not None and (
                current.agent != metadata.agent
                or current.version != metadata.version
                or current.model != metadata.model
            ):
                raise AdapterError("ADAPTER_METADATA_INVALID")
            metadata = current if metadata is None else AgentMetadata(
                agent=metadata.agent,
                version=metadata.version,
                model=metadata.model,
                capabilities=tuple(
                    sorted({*metadata.capabilities, *current.capabilities})
                ),
            )
        current_input, current_output = _usage_values(record)
        if current_input is not None:
            if input_tokens is not None:
                raise AdapterError("ADAPTER_USAGE_INVALID")
            input_tokens = current_input
            usage_seen = True
        if current_output is not None:
            if output_tokens is not None:
                raise AdapterError("ADAPTER_USAGE_INVALID")
            output_tokens = current_output
            usage_seen = True
    if require_metadata and metadata is None:
        raise AdapterError("ADAPTER_METADATA_INVALID")
    usage = (
        UsageRecord(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw_digest=_digest(raw),
        )
        if usage_seen
        else None
    )
    return metadata, usage


def _plain_metadata(raw: bytes, expected_agent: str) -> AgentMetadata:
    try:
        text = raw.decode("utf-8", errors="strict").strip()
    except UnicodeError as exc:
        raise AdapterError("ADAPTER_METADATA_INVALID") from exc
    version_match = _VERSION_PATTERN.search(text)
    model_match = _MODEL_PATTERN.search(text)
    if version_match is None or model_match is None:
        raise AdapterError("ADAPTER_METADATA_INVALID")
    try:
        return AgentMetadata(
            agent=expected_agent,
            version=version_match.group(0),
            model=model_match.group(1),
            capabilities=(),
        )
    except ValueError as exc:
        raise AdapterError("ADAPTER_METADATA_INVALID") from exc


def _compose_prompt(task: AgentTask, view: CompiledView) -> str:
    if type(view) is not CompiledView or not view.validation.valid:
        raise AdapterError("ADAPTER_VIEW_INVALID")
    if not isinstance(view.content, str):
        raise AdapterError("ADAPTER_VIEW_INVALID")
    return f"{view.content}\n\n{task.prompt}" if view.content else task.prompt


class ProcessAgentAdapter(ABC):
    """Shared implementation used by the concrete Codex and Claude seams."""

    agent_name: ClassVar[str]

    def __init__(self, binary: str, timeout_seconds: float = MAX_TIMEOUT_SECONDS) -> None:
        if type(binary) is not str or not binary:
            raise ValueError("adapter binary must be a nonempty string")
        if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds):
            raise ValueError("adapter timeout must be finite")
        if timeout_seconds <= 0 or timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError("adapter timeout outside bounded range")
        self.binary = binary
        self.timeout_seconds = float(timeout_seconds)

    @abstractmethod
    def _run_argv(self, prompt: str) -> tuple[str, ...]:
        raise NotImplementedError

    def _preflight_argv(self) -> tuple[str, ...]:
        return (self.binary, "--version")

    def _execute(self, argv: Sequence[str], *, cwd: Path, timeout: float) -> _ProcessResult:
        result = _run_bounded(argv, cwd=cwd, timeout_seconds=timeout)
        if result.returncode != 0:
            raise AdapterError("ADAPTER_EXIT_NONZERO")
        return result

    def preflight(self) -> AgentMetadata:
        result = self._execute(
            self._preflight_argv(), cwd=Path.cwd().resolve(), timeout=self.timeout_seconds
        )
        try:
            metadata, _ = _parse_events(
                result.stdout, expected_agent=self.agent_name, require_metadata=True
            )
        except AdapterError as error:
            if error.code != "ADAPTER_OUTPUT_INVALID":
                raise
            metadata = None
        if metadata is not None:
            return metadata
        return _plain_metadata(result.stdout, self.agent_name)

    def run(self, task: AgentTask, view: CompiledView, workspace: Path) -> AgentRun:
        if type(task) is not AgentTask:
            raise AdapterError("ADAPTER_TASK_INVALID")
        if not isinstance(workspace, Path) or not workspace.is_absolute() or not workspace.is_dir():
            raise AdapterError("ADAPTER_WORKSPACE_INVALID")
        try:
            task_root = task.cwd.resolve(strict=True)
            run_root = workspace.resolve(strict=True)
        except OSError as exc:
            raise AdapterError("ADAPTER_WORKSPACE_INVALID") from exc
        if not task_root.is_dir() or not run_root.is_dir():
            raise AdapterError("ADAPTER_WORKSPACE_INVALID")
        try:
            run_root.relative_to(task_root)
        except ValueError as exc:
            raise AdapterError("ADAPTER_WORKSPACE_INVALID") from exc
        prompt = _compose_prompt(task, view)
        preflight = self.preflight()
        result = self._execute(
            self._run_argv(prompt),
            cwd=run_root,
            timeout=min(self.timeout_seconds, task.timeout_seconds),
        )
        metadata, usage = _parse_events(
            result.stdout, expected_agent=self.agent_name, require_metadata=True
        )
        if metadata is None or (
            metadata.version != preflight.version or metadata.model != preflight.model
        ):
            raise AdapterError("ADAPTER_METADATA_INVALID")
        return AgentRun(
            metadata=metadata,
            exit_code=result.returncode,
            stdout=result.stdout[:MAX_STDOUT_BYTES],
            stderr_digest=_digest(result.stderr),
            usage=usage,
        )

    def parse_usage(self, raw_events: Path) -> UsageRecord:
        if not isinstance(raw_events, Path) or not raw_events.is_absolute():
            raise AdapterError("ADAPTER_USAGE_PATH_INVALID")
        try:
            raw = raw_events.read_bytes()
        except OSError as exc:
            raise AdapterError("ADAPTER_USAGE_READ_FAILED") from exc
        try:
            _, usage = _parse_events(
                raw, expected_agent=self.agent_name, require_metadata=False
            )
        except AdapterError as error:
            if error.code in {"ADAPTER_OUTPUT_INVALID", "ADAPTER_METADATA_INVALID"}:
                raise AdapterError("ADAPTER_USAGE_INVALID") from error
            raise
        if usage is None:
            usage = UsageRecord(input_tokens=None, output_tokens=None, raw_digest=_digest(raw))
        return usage


__all__ = [
    "ENV_ALLOWLIST",
    "MAX_EVENT_BYTES",
    "MAX_STDOUT_BYTES",
    "AdapterError",
    "AgentAdapter",
    "AgentMetadata",
    "AgentRun",
    "AgentTask",
    "ProcessAgentAdapter",
    "UsageRecord",
]
