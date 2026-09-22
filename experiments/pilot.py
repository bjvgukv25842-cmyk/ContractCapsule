"""Fail-closed planning and readiness checks for the M8 pilot.

This module deliberately stops before an adapter call.  A pilot plan is useful
only when its benchmark, protocol, and agent identities are frozen; a plan
that is not ready produces blockers, never synthetic observations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from benchmark.loader import BenchmarkLoadError, load_manifest
from experiments.preflight import PreflightError, binary_digest, load_receipt

PILOT_CONDITIONS = ("B0", "B2", "B4", "CC")
PILOT_REPETITIONS = 2
PILOT_TASK_COUNT = 6
PILOT_SCHEDULE_SIZE = PILOT_TASK_COUNT * len(PILOT_CONDITIONS) * PILOT_REPETITIONS
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class PilotConfigError(ValueError):
    """A pilot configuration cannot be interpreted safely."""


class PilotGateError(RuntimeError):
    """The M8 readiness gate refused to authorize execution."""


class _PilotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PilotConfig(_PilotModel):
    """The immutable shape of the preregistered M8 pilot."""

    study_id: str = Field(min_length=1, max_length=120)
    agent: Literal["codex"] = "codex"
    task_ids: tuple[str, ...]
    task_strata: dict[str, str]
    conditions: tuple[str, ...] = PILOT_CONDITIONS
    repetitions: int = Field(default=PILOT_REPETITIONS, ge=1, le=2)
    runtime_budget_tokens: int = Field(gt=0, le=10_000_000)
    timeout_seconds: float = Field(gt=0, le=3600)
    model: str | None = None
    version: str | None = None
    binary: str | None = None
    manifest_path: Path = Path("benchmark/benchmark-manifest.json")
    protocol_path: Path = Path("research/protocol.md")
    output_path: Path = Path("results/pilot/runs.jsonl")
    raw_output_dir: Path = Path("results/pilot/raw")
    readiness_report_path: Path = Path("results/pilot/readiness.json")
    preflight_receipt: Path | None = None
    expected_manifest_digest: str | None = None
    expected_protocol_digest: str | None = None
    g2_authorization: str | None = None
    dry_run: bool = True
    live_agent: bool = False

    @field_validator(
        "manifest_path",
        "protocol_path",
        "output_path",
        "raw_output_dir",
        "readiness_report_path",
        "preflight_receipt",
        mode="before",
    )
    @classmethod
    def _path_fields(cls, value: object) -> Path | None:
        if value is None:
            return None
        if isinstance(value, (str, Path)):
            return Path(value)
        raise TypeError("path fields must be strings or paths")

    @field_validator("task_ids", mode="before")
    @classmethod
    def _task_ids_tuple(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, list):
            value = tuple(value)
        if not isinstance(value, tuple):
            raise TypeError("task_ids must be a tuple or list")
        if len(value) != PILOT_TASK_COUNT or len(set(value)) != len(value):
            raise ValueError("task_ids must contain six unique tasks")
        if any(type(item) is not str or not item.strip() for item in value):
            raise ValueError("task_ids must contain non-empty strings")
        return value

    @field_validator("task_strata", mode="before")
    @classmethod
    def _task_strata_mapping(cls, value: object) -> dict[str, str]:
        if not isinstance(value, Mapping):
            raise TypeError("task_strata must be an object")
        result = dict(value)
        if len(result) != PILOT_TASK_COUNT:
            raise ValueError("task_strata must explicitly cover six tasks")
        if any(
            type(key) is not str
            or not key.strip()
            or type(item) is not str
            or not item.strip()
            for key, item in result.items()
        ):
            raise ValueError("task_strata keys and values must be non-empty strings")
        return result

    @field_validator("conditions", mode="before")
    @classmethod
    def _conditions_tuple(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, list):
            value = tuple(value)
        if not isinstance(value, tuple):
            raise TypeError("conditions must be a tuple or list")
        if tuple(value) != PILOT_CONDITIONS:
            raise ValueError("M8 conditions must be exactly B0, B2, B4, CC")
        return value

    @field_validator("expected_manifest_digest", "expected_protocol_digest")
    @classmethod
    def _digest_shape(cls, value: str | None) -> str | None:
        if value is not None and _DIGEST.fullmatch(value) is None:
            raise ValueError("expected digest must be sha256")
        return value

    @model_validator(mode="after")
    def _cross_fields(self) -> PilotConfig:
        if set(self.task_strata) != set(self.task_ids):
            raise ValueError("task_strata must match task_ids exactly")
        if self.repetitions != PILOT_REPETITIONS:
            raise ValueError("M8 pilot requires two repetitions")
        return self

    @property
    def scheduled_runs(self) -> int:
        return len(self.task_ids) * len(self.conditions) * self.repetitions

    @property
    def digest(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


class PilotRunSpec(_PilotModel):
    """One deterministic task-condition-repetition cell."""

    ordinal: int = Field(ge=0)
    task_id: str
    condition: Literal["B0", "B2", "B4", "CC"]
    repetition: int = Field(ge=0, lt=PILOT_REPETITIONS)
    run_key: str


class PilotGateReport(_PilotModel):
    """Auditable result of the pre-run M8 survival gate."""

    ready: bool
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    task_ids: tuple[str, ...]
    scheduled_runs: int
    config_digest: str
    manifest_digest: str | None = None
    protocol_digest: str | None = None


class _UniqueLoader(yaml.SafeLoader):
    pass


def _yaml_mapping(
    loader: _UniqueLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise PilotConfigError("duplicate YAML key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping)


def _tuplify(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuplify(item) for item in value)
    if isinstance(value, dict):
        return {key: _tuplify(item) for key, item in value.items()}
    return value


def load_pilot_config(path: Path | str) -> PilotConfig:
    """Load a strict pilot config without resolving or mutating its inputs."""

    config_path = Path(path)
    if config_path.is_symlink() or not config_path.is_file():
        raise PilotConfigError("pilot config must be a regular file")
    try:
        raw = yaml.load(config_path.read_text(encoding="utf-8"), Loader=_UniqueLoader)
    except (OSError, UnicodeError, yaml.YAMLError, PilotConfigError) as error:
        raise PilotConfigError("pilot config syntax is invalid") from error
    if not isinstance(raw, Mapping):
        raise PilotConfigError("pilot config root must be an object")
    try:
        return PilotConfig.model_validate(_tuplify(dict(raw)))
    except Exception as error:
        raise PilotConfigError("pilot config schema is invalid") from error


def _file_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise OSError("input must be a regular file")
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _validate_preflight_receipt(config: PilotConfig, blockers: list[str]) -> None:
    """Check receipt integrity and identity before a pilot can be enabled."""

    receipt_path = config.preflight_receipt
    if receipt_path is None:
        _append_unique(blockers, "preflight_receipt_missing")
        return
    try:
        receipt_missing = not receipt_path.is_file() or receipt_path.is_symlink()
    except OSError:
        receipt_missing = True
    if receipt_missing:
        _append_unique(blockers, "preflight_receipt_missing")
        return
    try:
        receipt = load_receipt(receipt_path)
    except (PreflightError, OSError, ValueError):
        _append_unique(blockers, "preflight_receipt_invalid")
        return
    if not receipt.available:
        _append_unique(blockers, "preflight_unavailable")
    if not receipt.model or not receipt.version or not receipt.binary:
        _append_unique(blockers, "preflight_metadata_incomplete")
    if receipt.agent != config.agent:
        _append_unique(blockers, "preflight_agent_mismatch")
    if config.model is not None and receipt.model != config.model:
        _append_unique(blockers, "preflight_model_mismatch")
    if config.version is not None and receipt.version != config.version:
        _append_unique(blockers, "preflight_version_mismatch")
    if config.binary is not None and receipt.binary != config.binary:
        _append_unique(blockers, "preflight_binary_mismatch")
    if receipt.signature is None:
        _append_unique(blockers, "preflight_signature_missing")
    current_binary_digest = binary_digest(config.binary)
    if (
        receipt.binary_digest is None
        or current_binary_digest is None
        or receipt.binary_digest != current_binary_digest
    ):
        _append_unique(blockers, "preflight_binary_drift")


def validate_pilot_inputs(
    config: PilotConfig,
    manifest_path: Path | str | None = None,
    protocol_path: Path | str | None = None,
) -> PilotGateReport:
    """Validate all author-controlled prerequisites before any agent call."""

    if type(config) is not PilotConfig:
        raise PilotGateError("pilot gate requires a PilotConfig")
    blockers: list[str] = []
    warnings: list[str] = []
    manifest_file = Path(manifest_path or config.manifest_path)
    protocol_file = Path(protocol_path or config.protocol_path)
    manifest_digest: str | None = None
    protocol_digest: str | None = None
    manifest = None

    try:
        manifest_digest = _file_digest(manifest_file)
    except OSError:
        _append_unique(blockers, "manifest_unavailable")
    try:
        protocol_digest = _file_digest(protocol_file)
    except OSError:
        _append_unique(blockers, "protocol_unavailable")

    if config.expected_manifest_digest is None:
        _append_unique(blockers, "manifest_digest_missing")
    elif manifest_digest != config.expected_manifest_digest:
        _append_unique(blockers, "manifest_digest_mismatch")
    if config.expected_protocol_digest is None:
        _append_unique(blockers, "protocol_digest_missing")
    elif protocol_digest != config.expected_protocol_digest:
        _append_unique(blockers, "protocol_digest_mismatch")

    try:
        manifest = load_manifest(manifest_file)
    except (BenchmarkLoadError, OSError) as error:
        del error
        _append_unique(blockers, "manifest_load_failed")

    if manifest is not None:
        if manifest.status != "frozen":
            _append_unique(blockers, "benchmark_not_frozen")
        if len(manifest.tasks) != 24:
            _append_unique(blockers, "benchmark_cardinality")
        if manifest.manifest_digest is None:
            _append_unique(blockers, "manifest_digest_missing")
        if len({task.language for task in manifest.tasks}) < 3:
            _append_unique(blockers, "language_ecosystems_insufficient")
        if len({task.repository.source_url for task in manifest.tasks}) < 8:
            _append_unique(blockers, "repository_coverage_insufficient")
        selected = {task.task_id: task for task in manifest.tasks}
        for task_id in config.task_ids:
            task = selected.get(task_id)
            if task is None:
                _append_unique(blockers, "task_missing")
                continue
            if (
                task.human_approval.value != "approved"
                or task.executable is not True
                or task.repository.source_status != "verified"
            ):
                _append_unique(blockers, "task_not_approved")
            if (
                task.repository.commit is None
                or task.repository.content_digest is None
                or task.repository.license == "pending-verification"
            ):
                _append_unique(blockers, "task_source_lock_missing")
            if not task.checks.target or not task.checks.invariant or not task.checks.spillover:
                _append_unique(blockers, "task_gold_checks_missing")
            if task.old_capsule_digest is None or task.new_capsule_digest is None:
                _append_unique(blockers, "task_capsule_digest_missing")

    adjudication = manifest_file.parent / "adjudication.jsonl"
    if not adjudication.is_file() or adjudication.is_symlink():
        _append_unique(blockers, "adjudication_missing")
    else:
        try:
            if adjudication.stat().st_size == 0:
                _append_unique(blockers, "adjudication_invalid")
        except OSError:
            _append_unique(blockers, "adjudication_invalid")
    if config.g2_authorization is None or not config.g2_authorization.strip():
        _append_unique(blockers, "g2_authorization_missing")
    if not config.model or not config.version or not config.binary:
        _append_unique(blockers, "agent_metadata_not_frozen")
    _validate_preflight_receipt(config, blockers)
    if config.dry_run or not config.live_agent:
        _append_unique(blockers, "pilot_not_enabled")
    if config.output_path.exists():
        _append_unique(blockers, "pilot_output_exists")
    if config.scheduled_runs != PILOT_SCHEDULE_SIZE:
        _append_unique(blockers, "schedule_cardinality")

    return PilotGateReport(
        ready=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        task_ids=config.task_ids,
        scheduled_runs=config.scheduled_runs,
        config_digest=config.digest,
        manifest_digest=manifest_digest,
        protocol_digest=protocol_digest,
    )


def build_pilot_schedule(config: PilotConfig) -> tuple[PilotRunSpec, ...]:
    """Build a stable 48-cell schedule without touching the filesystem."""

    if type(config) is not PilotConfig:
        raise PilotGateError("pilot schedule requires a PilotConfig")
    schedule: list[PilotRunSpec] = []
    ordinal = 0
    for task_id in sorted(config.task_ids):
        for condition in PILOT_CONDITIONS:
            for repetition in range(config.repetitions):
                identity = f"{config.study_id}\0{task_id}\0{condition}\0{repetition}"
                run_key = "pilot-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
                schedule.append(
                    PilotRunSpec(
                        ordinal=ordinal,
                        task_id=task_id,
                        condition=condition,  # type: ignore[arg-type]
                        repetition=repetition,
                        run_key=run_key,
                    )
                )
                ordinal += 1
    return tuple(schedule)


def _write_report(path: Path, report: PilotGateReport) -> None:
    if path.exists() or path.is_symlink():
        raise PilotGateError("readiness report cannot be overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = None
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise PilotGateError("readiness report cannot be overwritten") from error
    except OSError as error:
        raise PilotGateError("readiness report could not be created") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check M8 pilot readiness")
    parser.add_argument("--config", default="experiments/configs/m8-pilot.yaml")
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--protocol", default=None)
    parser.add_argument("--report", default=None)
    parser.add_argument("--check", action="store_true", help="check readiness")
    args = parser.parse_args(argv)
    try:
        config = load_pilot_config(args.config)
        report = validate_pilot_inputs(config, args.manifest, args.protocol)
        target = Path(args.report) if args.report is not None else config.readiness_report_path
        _write_report(target, report)
    except (PilotConfigError, PilotGateError) as error:
        parser.error(str(error))
    print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "PILOT_CONDITIONS",
    "PILOT_REPETITIONS",
    "PILOT_SCHEDULE_SIZE",
    "PilotConfig",
    "PilotConfigError",
    "PilotGateError",
    "PilotGateReport",
    "PilotRunSpec",
    "build_pilot_schedule",
    "load_pilot_config",
    "validate_pilot_inputs",
]
