"""Idempotent experiment execution boundary.

Live agent calls are deliberately opt-in.  A dry run only builds a stable
execution plan; it never invokes a binary or writes a task outcome.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from baselines.providers import ContextArtifact, is_provider_artifact
from benchmark.loader import BenchmarkLoadError, require_loaded_task
from experiments.models import (
    ExperimentConfig,
    PreflightReceipt,
    RunRecord,
    RunStore,
    UsageRecord,
    load_config,
)
from experiments.preflight import PreflightError, validate_receipt


class RunRefusal(RuntimeError):
    """Execution was refused before an agent could run."""


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RunPlan:
    run_id: str
    task_id: str
    condition: str
    agent: str
    executed: bool = False
    reason: str = "dry-run"


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _repository_commit(task: object) -> str:
    direct = _field(task, "repository_commit", None)
    if isinstance(direct, str) and direct:
        return direct
    repository = _field(task, "repository", None)
    commit = _field(repository, "commit", None)
    if isinstance(commit, str) and commit:
        return commit
    raise RunRefusal("immutable repository commit is required")


def _task_id(task: object) -> str:
    value = _field(task, "task_id", None)
    if not isinstance(value, str) or not value:
        raise RunRefusal("task_id is required")
    return value


def _assert_executable_task(task: object) -> None:
    approval = _field(task, "human_approval", _field(task, "approval_status", None))
    approval_value = getattr(approval, "value", approval)
    executable = _field(task, "executable", False)
    repository = _field(task, "repository", None)
    source_status = _field(repository, "source_status", None)
    if approval_value != "approved" or executable is not True or source_status != "verified":
        raise RunRefusal("task is not human-approved and executable")


def _artifact_data(artifact: object | None) -> tuple[tuple[str, ...], str | None, str | None]:
    if artifact is None:
        return (), None, None
    condition = _field(artifact, "condition", None)
    metadata = _field(artifact, "metadata", {})
    capsule_digests: list[str] = []
    manifest_digest: object = None
    if isinstance(metadata, Mapping):
        candidate = metadata.get("capsule_digests", metadata.get("capsules", ()))
        if isinstance(candidate, (list, tuple)):
            capsule_digests = [item for item in candidate if isinstance(item, str)]
        manifest_digest = metadata.get(
            "view_manifest_digest", metadata.get("manifest_digest")
        )
    if manifest_digest is not None and (
        not isinstance(manifest_digest, str) or _DIGEST.fullmatch(manifest_digest) is None
    ):
        raise RunRefusal("view manifest digest is invalid")
    normalized_condition = getattr(condition, "value", condition)
    return (
        tuple(capsule_digests),
        manifest_digest if isinstance(manifest_digest, str) else None,
        normalized_condition if isinstance(normalized_condition, str) else None,
    )


def _trusted_task_root(task: object) -> Path:
    root = getattr(task, "_loader_root", None)
    if not isinstance(root, Path):
        raise RunRefusal("loader task package root is unavailable")
    try:
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise RunRefusal("loader task package root is unavailable") from error
    if not resolved.is_dir() or resolved.is_symlink():
        raise RunRefusal("loader task package root is unavailable")
    return resolved


def _git_output(workspace: Path, *arguments: str) -> bytes:
    env = {
        key: value
        for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
        if (value := os.environ.get(key)) is not None
    }
    env["GIT_OPTIONAL_LOCKS"] = "0"
    command = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "-C",
        str(workspace),
        *arguments,
    ]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            env=env,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RunRefusal("workspace Git validation failed") from error
    if len(completed.stdout) > 1024 * 1024 or len(completed.stderr) > 1024 * 1024:
        raise RunRefusal("workspace Git validation output exceeded limit")
    if completed.returncode != 0:
        raise RunRefusal("workspace Git validation failed")
    return completed.stdout.strip()


def _validate_workspace(
    task: object, workspace: Path | str, task_root: Path
) -> Path:
    raw = Path(workspace)
    if raw.is_symlink():
        raise RunRefusal("workspace must not be a symlink")
    try:
        root = raw.resolve(strict=True)
    except OSError as error:
        raise RunRefusal("workspace must be a directory") from error
    if not root.is_dir():
        raise RunRefusal("workspace must be a directory")
    if (
        root == task_root
        or root.is_relative_to(task_root)
        or task_root.is_relative_to(root)
    ):
        raise RunRefusal("workspace must be separate from immutable task package")
    try:
        top_level = Path(_git_output(root, "rev-parse", "--show-toplevel").decode())
        head = _git_output(root, "rev-parse", "--verify", "HEAD").decode("ascii")
        origin = _git_output(root, "config", "--get", "remote.origin.url").decode()
        status = _git_output(
            root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored=matching",
            "--ignore-submodules=none",
        )
    except UnicodeError as error:
        raise RunRefusal("workspace Git metadata is invalid") from error
    if top_level.resolve() != root:
        raise RunRefusal("workspace must be the Git checkout root")
    if head != _repository_commit(task):
        raise RunRefusal("workspace commit does not match task repository lock")
    repository = _field(task, "repository", None)
    source_url = _field(repository, "source_url", None)
    if not isinstance(source_url, str) or origin != source_url:
        raise RunRefusal("workspace origin does not match task repository lock")
    if status:
        raise RunRefusal("workspace must be clean before each independent run")
    return root


def _validate_artifact_binding(
    task: object,
    artifact: ContextArtifact | None,
    config: ExperimentConfig,
    trusted_root: Path,
) -> None:
    if artifact is None:
        return
    if getattr(artifact, "_provider_task_id", None) != _task_id(task):
        raise RunRefusal("artifact task binding does not match task")
    expected_commit = _repository_commit(task)
    if getattr(artifact, "_provider_repository_commit", None) != expected_commit:
        raise RunRefusal("artifact repository binding does not match task")
    raw_root = getattr(artifact, "_provider_package_root", None)
    if not isinstance(raw_root, str):
        raise RunRefusal("artifact package binding is unavailable")
    try:
        artifact_root = Path(raw_root).resolve(strict=True)
    except OSError as error:
        raise RunRefusal("artifact package binding is unavailable") from error
    if artifact_root != trusted_root:
        raise RunRefusal("artifact package binding does not match task")
    expected_package_digest = getattr(task, "_loader_package_digest", None)
    if not isinstance(expected_package_digest, str):
        raise RunRefusal("loader task package digest is unavailable")
    if getattr(artifact, "_provider_package_digest", None) != expected_package_digest:
        raise RunRefusal("artifact package digest does not match task")
    if artifact.budget.max_tokens != config.runtime_budget_tokens:
        raise RunRefusal("artifact budget does not match experiment budget")


def _prompt_digest(task: object, artifact: object | None) -> str:
    prompt = _field(task, "prompt", "")
    if not isinstance(prompt, str):
        prompt = str(prompt)
    payload = prompt
    if artifact is not None:
        content = _field(artifact, "payload", _field(artifact, "content", ""))
        if isinstance(content, str):
            payload += "\n" + content
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_raw(path: Path, value: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value if isinstance(value, bytes) else value.encode("utf-8")
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise RunRefusal("raw event path must be a regular file")
        if path.read_bytes() != data:
            raise RunRefusal("raw event path cannot be overwritten")
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise RunRefusal("raw event path cannot be overwritten") from error
    except OSError as error:
        raise RunRefusal("unable to persist raw events") from error


def _adapter_call(adapter: object, task: object, artifact: object | None, workspace: Path) -> object:
    run_task = getattr(adapter, "run_task", None)
    if callable(run_task):
        return run_task(task=task, artifact=artifact, workspace=workspace)
    run = getattr(adapter, "run", None)
    if not callable(run):
        raise RunRefusal("adapter does not expose a run method")
    # Adapters used by the M7 harness may expose either a keyword-friendly
    # runner or the CCS ProcessAgentAdapter positional seam.
    try:
        return run(task, artifact, workspace)
    except TypeError:
        return run(task=task, artifact=artifact, workspace=workspace)


def _adapter_observation(result: object) -> tuple[int, bytes, str | None, UsageRecord, dict[str, Any]]:
    exit_code = _field(result, "exit_code", 0)
    if type(exit_code) is not int or exit_code < 0:
        raise RunRefusal("adapter returned an invalid exit code")
    stdout = _field(result, "stdout", b"")
    if isinstance(stdout, str):
        stdout = stdout.encode("utf-8")
    if not isinstance(stdout, bytes):
        stdout = b""
    metadata_obj = _field(result, "metadata", None)
    metadata: dict[str, Any] = {
        "agent": _field(metadata_obj, "agent", None),
        "version": _field(metadata_obj, "version", None),
        "model": _field(metadata_obj, "model", None),
        "available": metadata_obj is not None,
    }
    usage_obj = _field(result, "usage", None)
    if isinstance(usage_obj, UsageRecord):
        usage = usage_obj
    else:
        input_tokens = _field(usage_obj, "input_tokens", None)
        output_tokens = _field(usage_obj, "output_tokens", None)
        raw_digest = _field(usage_obj, "raw_digest", None)
        if input_tokens is not None and (
            type(input_tokens) is not int or input_tokens < 0
        ):
            raise RunRefusal("adapter returned invalid usage")
        if output_tokens is not None and (
            type(output_tokens) is not int or output_tokens < 0
        ):
            raise RunRefusal("adapter returned invalid usage")
        if raw_digest is not None and not isinstance(raw_digest, str):
            raise RunRefusal("adapter returned invalid usage")
        usage = UsageRecord(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw_digest=raw_digest,
        )
    stderr_digest = _field(result, "stderr_digest", None)
    if stderr_digest is not None and not isinstance(stderr_digest, str):
        stderr_digest = None
    return exit_code, stdout, stderr_digest, usage, metadata


def _validate_adapter_identity(adapter: object, receipt: PreflightReceipt) -> None:
    """Bind the executable object used for the run to the signed preflight."""

    binary = getattr(adapter, "binary", None)
    if receipt.binary is not None and binary != receipt.binary:
        raise RunRefusal("adapter binary does not match preflight receipt")
    expected_agent = getattr(adapter, "agent_name", None)
    if expected_agent is not None and expected_agent != receipt.agent:
        raise RunRefusal("adapter agent does not match preflight receipt")
    preflight = getattr(adapter, "preflight", None)
    if not callable(preflight):
        raise RunRefusal("adapter preflight probe is required")
    try:
        observed = preflight()
    except Exception as error:
        raise RunRefusal("adapter preflight probe failed") from error
    for field in ("agent", "version", "model"):
        value = getattr(observed, field, None)
        expected = getattr(receipt, field)
        if not isinstance(value, str) or value != expected:
            raise RunRefusal(f"adapter {field} does not match preflight receipt")


def _validate_result_binding(metadata: Mapping[str, Any], receipt: PreflightReceipt) -> None:
    if metadata.get("available") is not True:
        raise RunRefusal("adapter result metadata is unavailable")
    for field in ("agent", "version", "model"):
        value = metadata.get(field)
        expected = getattr(receipt, field)
        if not isinstance(value, str) or value != expected:
            raise RunRefusal(f"adapter result {field} does not match preflight receipt")


def _validate_usage(usage: UsageRecord, stdout: bytes) -> None:
    """Usage counts are accepted only when bound to persisted raw events."""

    raw_digest = usage.raw_digest
    has_counts = usage.input_tokens is not None or usage.output_tokens is not None
    if has_counts and raw_digest is None:
        raise RunRefusal("adapter usage counts lack a raw event digest")
    if raw_digest is not None:
        expected = "sha256:" + hashlib.sha256(stdout).hexdigest()
        if raw_digest != expected:
            raise RunRefusal("adapter usage raw digest does not match raw events")


def run_once(
    task: object,
    *,
    config: ExperimentConfig | Path | str | dict[str, Any],
    store: RunStore | None = None,
    artifact: object | None = None,
    preflight_receipt: object | None = None,
    adapter: object | None = None,
    workspace: Path | str | None = None,
    repetition: int = 0,
    dry_run: bool | None = None,
    preflight_key: bytes | None = None,
) -> RunRecord | RunPlan:
    parsed = load_config(config)
    try:
        task = require_loaded_task(task)
    except BenchmarkLoadError as error:
        raise RunRefusal(str(error)) from error
    if artifact is not None and not is_provider_artifact(artifact):
        raise RunRefusal("artifact must be produced by a context provider")
    if artifact is not None and type(artifact) is not ContextArtifact:
        raise RunRefusal("artifact must be a ContextArtifact")
    trusted_root = _trusted_task_root(task)
    validated_workspace: Path | None = None
    if workspace is not None:
        if not isinstance(workspace, (str, Path)):
            raise RunRefusal("workspace must be a path")
        validated_workspace = _validate_workspace(task, workspace, trusted_root)
    _validate_artifact_binding(task, artifact, parsed, trusted_root)
    task_id = _task_id(task)
    _assert_executable_task(task)
    condition = _field(artifact, "condition", _field(task, "condition", "B0"))
    condition = getattr(condition, "value", condition)
    if not isinstance(condition, str) or condition not in parsed.conditions:
        raise RunRefusal("declared condition is not in experiment matrix")
    if type(repetition) is not int or repetition < 0 or repetition >= parsed.repetitions:
        raise RunRefusal("repetition is outside experiment matrix")
    if condition not in {"B0", "B1", "B2", "B3", "B4", "CC"}:
        raise RunRefusal("unknown condition")
    commit = _repository_commit(task)
    capsule_digests, artifact_digest, _ = _artifact_data(artifact)
    if condition == "CC" and artifact_digest is None:
        raise RunRefusal("CC run requires a view manifest digest")
    prompt_digest = _prompt_digest(task, artifact)
    identity_record = RunRecord.new(
        task_id=task_id,
        condition=condition,
        agent=parsed.agent,
        repetition=repetition,
        repository_commit=commit,
        capsule_digests=capsule_digests,
        prompt_digest=prompt_digest,
        view_manifest_digest=artifact_digest,
        raw_event_path="raw/pending.jsonl",
        exit_code=0,
        infrastructure_failure=False,
        config_digest=parsed.digest,
    )
    selected_store = store or RunStore(parsed.output_path)
    existing = selected_store.get(identity_record.run_id)
    if existing is not None:
        return existing
    is_dry = parsed.dry_run if dry_run is None else dry_run
    if is_dry:
        return RunPlan(identity_record.run_id, task_id, condition, parsed.agent)
    receipt_value = preflight_receipt or parsed.preflight_receipt
    if receipt_value is not None and not isinstance(receipt_value, (PreflightReceipt, Path, str)):
        raise RunRefusal("invalid preflight receipt")
    try:
        receipt = validate_receipt(
            receipt_value,
            parsed,
            require_available=True,
            signing_key=preflight_key,
        )
    except PreflightError as error:
        raise RunRefusal(str(error)) from error
    if not parsed.live_agent:
        raise RunRefusal("live-agent execution is disabled")
    if adapter is None:
        raise RunRefusal("adapter is required for live execution")
    _validate_adapter_identity(adapter, receipt)
    if validated_workspace is None:
        raise RunRefusal("an attested clean workspace is required for live execution")
    run_root = validated_workspace
    started = _timestamp()
    raw_path = selected_store.path.parent.resolve() / "raw" / f"{identity_record.run_id}.jsonl"
    raw_record_path = (Path("raw") / f"{identity_record.run_id}.jsonl").as_posix()
    try:
        result = _adapter_call(adapter, task, artifact, run_root)
        exit_code, stdout, _stderr_digest, usage, metadata = _adapter_observation(result)
        _validate_result_binding(metadata, receipt)
        _validate_usage(usage, stdout)
        infrastructure_failure = False
        failure_code = None if exit_code == 0 else "AGENT_TASK_FAILED"
        outcome = "passed" if exit_code == 0 else "failed"
    except RunRefusal:
        raise
    except Exception as error:  # noqa: BLE001 - adapter failures are infrastructure outcomes
        exit_code, stdout, _, usage, metadata = 1, b"", None, UsageRecord(), {
            "agent": parsed.agent,
            "version": None,
            "model": None,
            "available": False,
        }
        infrastructure_failure = True
        failure_code = getattr(error, "code", None) or "ADAPTER_EXECUTION_FAILED"
        outcome = "unknown"
    _write_raw(raw_path, stdout)
    record = RunRecord.new(
        task_id=task_id,
        condition=condition,
        agent=parsed.agent,
        repetition=repetition,
        repository_commit=commit,
        capsule_digests=capsule_digests,
        prompt_digest=prompt_digest,
        view_manifest_digest=artifact_digest,
        raw_event_path=raw_record_path,
        exit_code=exit_code,
        infrastructure_failure=infrastructure_failure,
        usage=usage,
        failure_code=failure_code,
        task_outcome=outcome,  # type: ignore[arg-type]
        adapter_metadata=metadata,
        config_digest=parsed.digest,
        preflight_digest=receipt.digest,
        started_at=started,
        finished_at=_timestamp(),
    )
    return selected_store.append(record)


__all__ = ["RunPlan", "RunRefusal", "run_once"]
