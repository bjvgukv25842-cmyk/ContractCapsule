"""Bounded, condition-blind execution of declared benchmark checks."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ScoreError(ValueError):
    """A declared scoring command is unsafe or cannot be interpreted."""


class ScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target_passed: bool | None = None
    invariant_passed: bool | None = None
    spillover_passed: bool | None = None
    target_checks: int = Field(default=0, ge=0)
    invariant_checks: int = Field(default=0, ge=0)
    spillover_checks: int = Field(default=0, ge=0)
    exit_codes: tuple[int, ...] = ()
    infrastructure_failure: bool = False
    failure_code: str | None = None
    stdout_digest: str | None = None
    stderr_digest: str | None = None
    elapsed_seconds: float = Field(default=0.0, ge=0)
    # Deliberately always None.  A scorer must not carry a system-condition
    # label into the measurement result or trust labels supplied by a task.
    condition: None = None


_UNSAFE_TOKEN = re.compile(r"[\x00\n\r;&|<>`$]")
_CONDITION_TOKEN = re.compile(r"(?<![A-Za-z0-9_])(?:B[0-4]|CC)(?![A-Za-z0-9_])")
_MAX_OUTPUT = 1024 * 1024


def _task_root(task: object, cwd: Path | str | None) -> Path:
    candidate = cwd
    if candidate is None:
        for name in ("package_root", "root", "task_root"):
            candidate = getattr(task, name, None)
            if candidate is None and isinstance(task, Mapping):
                candidate = task.get(name)
            if candidate is not None:
                break
    if candidate is None:
        raise ScoreError("task root/cwd is required")
    root = Path(candidate)
    if not root.is_absolute():
        root = root.resolve()
    if root.is_symlink() or not root.is_dir():
        raise ScoreError("task root must be a regular directory")
    return root.resolve()


def _safe_relative(value: str) -> bool:
    if not value or value.startswith("/") or "\\" in value or "\x00" in value:
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def _command(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        # Shell parsing is intentionally not supported.  A benchmark command
        # must be an explicit argv sequence in the task package.
        raise ScoreError("scoring commands must be argv arrays, not shell strings")
    if not isinstance(value, (tuple, list)) or not value:
        raise ScoreError("scoring command must be a non-empty argv array")
    result = tuple(value)
    if any(
        type(item) is not str
        or not item
        or _UNSAFE_TOKEN.search(item)
        or _CONDITION_TOKEN.search(item)
        for item in result
    ):
        raise ScoreError("scoring command contains an unsafe argument")
    if "-c" in result or "--command" in result:
        raise ScoreError("inline shell commands are forbidden")
    for index, item in enumerate(result):
        if index == 0:
            # An absolute executable is allowed only for the interpreter/tool
            # itself; all repository paths remain relative.
            if item.startswith("/") and not Path(item).is_file():
                raise ScoreError("scoring executable does not exist")
            continue
        if item.startswith("/"):
            raise ScoreError("scoring paths must be relative")
        if "/" in item and not _safe_relative(item):
            raise ScoreError("scoring path escapes task root")
    return result


def _check_attr(check: object, name: str, default: object = None) -> object:
    if isinstance(check, Mapping):
        return check.get(name, default)
    return getattr(check, name, default)


def _declared_checks(task: object) -> dict[str, tuple[object, ...]]:
    checks: object = _check_attr(task, "checks", None)
    if checks is None and isinstance(task, Mapping):
        checks = task.get("tests")
    result: dict[str, tuple[object, ...]] = {"target": (), "invariant": (), "spillover": ()}
    for category in result:
        values: object = _check_attr(checks, category, ()) if checks is not None else ()
        if values is None:
            values = ()
        if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
            raise ScoreError(f"declared {category} checks are not a sequence")
        result[category] = tuple(values)
    return result


def _check_command(check: object) -> tuple[str, ...]:
    raw = _check_attr(check, "command", check)
    return _command(raw)


def _declared_command_matches(requested: tuple[str, ...], checks: Mapping[str, tuple[object, ...]]) -> bool:
    """Confirm an explicit command is one of the task's declared checks."""

    for values in checks.values():
        for check in values:
            raw = _check_attr(check, "command", check)
            if isinstance(raw, str):
                if raw in requested[1:]:
                    return True
                continue
            try:
                if requested == _command(raw):
                    return True
            except ScoreError:
                continue
    return False


def _check_cwd(check: object, root: Path) -> Path:
    raw = _check_attr(check, "cwd", ".")
    if not isinstance(raw, str) or not _safe_relative(raw) and raw != ".":
        raise ScoreError("declared check cwd must be relative")
    candidate = root if raw == "." else (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ScoreError("declared check cwd escapes task root") from error
    if not candidate.is_dir() or candidate.is_symlink():
        raise ScoreError("declared check cwd is unavailable")
    return candidate


def _run(command: tuple[str, ...], cwd: Path, timeout: float) -> tuple[int, bytes, bytes, bool, str | None]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            shell=False,
            env={key: value for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") if (value := os.environ.get(key)) is not None},
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        stdout = bytes(error.stdout or b"")[:_MAX_OUTPUT]
        stderr = bytes(error.stderr or b"")[:_MAX_OUTPUT]
        return 124, stdout, stderr, True, "TIMEOUT"
    except (OSError, ValueError):
        return 127, b"", b"", True, "EXECUTION_FAILED"
    return completed.returncode, completed.stdout[:_MAX_OUTPUT], completed.stderr[:_MAX_OUTPUT], False, None


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def score_task(
    task: object,
    *,
    condition: str | None = None,
    command: Sequence[str] | None = None,
    cwd: Path | str | None = None,
    task_root: Path | str | None = None,
    workspace: Path | str | None = None,
    timeout_seconds: float | None = None,
    labels: Mapping[str, object] | None = None,
) -> ScoreResult:
    """Run only package-declared checks and derive scores from exit status.

    ``condition`` and ``labels`` are accepted for caller compatibility but are
    intentionally ignored.  This makes it impossible for a condition-provided
    label to masquerade as an observed target or invariant result.
    """

    del condition, labels
    root = _task_root(task, cwd or task_root or workspace)
    declared = _declared_checks(task)
    if command is not None:
        requested = _command(command)
        if not any(declared.values()) or not _declared_command_matches(requested, declared):
            raise ScoreError("scoring command is not declared by the task")
        declared = {"target": (command,), "invariant": (), "spillover": ()}
    if not any(declared.values()):
        raise ScoreError("task declares no executable checks")
    raw_default_timeout: object = timeout_seconds
    if raw_default_timeout is None:
        raw_default_timeout = _check_attr(task, "max_runtime_seconds", 120.0)
    if not isinstance(raw_default_timeout, (int, float)) or isinstance(raw_default_timeout, bool) or raw_default_timeout <= 0:
        raise ScoreError("timeout must be positive")
    default_timeout = float(raw_default_timeout)

    passed: dict[str, list[bool]] = {"target": [], "invariant": [], "spillover": []}
    codes: list[int] = []
    output = bytearray()
    errors = bytearray()
    infra = False
    failure_code: str | None = None
    started = time.monotonic()
    for category, checks in declared.items():
        for check in checks:
            argv = _check_command(check)
            check_root = _check_cwd(check, root)
            raw_check_timeout = _check_attr(check, "timeout_seconds", default_timeout)
            if not isinstance(raw_check_timeout, (int, float)) or isinstance(raw_check_timeout, bool) or raw_check_timeout <= 0:
                raise ScoreError("declared check timeout must be positive")
            check_timeout = float(raw_check_timeout)
            code, stdout, stderr, failed_infra, code_name = _run(
                argv, check_root, min(default_timeout, check_timeout)
            )
            codes.append(code)
            output.extend(stdout)
            errors.extend(stderr)
            if failed_infra:
                infra = True
                failure_code = code_name
                passed[category].append(False)
            else:
                passed[category].append(code == 0)
    result = ScoreResult(
        target_passed=(all(passed["target"]) if passed["target"] else None),
        invariant_passed=(all(passed["invariant"]) if passed["invariant"] else None),
        spillover_passed=(all(passed["spillover"]) if passed["spillover"] else None),
        target_checks=len(passed["target"]),
        invariant_checks=len(passed["invariant"]),
        spillover_checks=len(passed["spillover"]),
        exit_codes=tuple(codes),
        infrastructure_failure=infra,
        failure_code=failure_code,
        stdout_digest=_digest(bytes(output)) if output else None,
        stderr_digest=_digest(bytes(errors)) if errors else None,
        elapsed_seconds=max(0.0, time.monotonic() - started),
    )
    return result


__all__ = ["ScoreError", "ScoreResult", "score_task"]
