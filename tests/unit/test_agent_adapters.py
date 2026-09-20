"""Contract tests for the bounded Codex and Claude process adapters."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from contractcapsule.adapters.base import (
    MAX_EVENT_BYTES,
    MAX_STDOUT_BYTES,
    AdapterError,
    AgentMetadata,
    AgentTask,
    UsageRecord,
)
from contractcapsule.adapters.claude import ClaudeAdapter
from contractcapsule.adapters.codex import CodexAdapter
from contractcapsule.models.view import CompiledView, ValidationReport, ViewManifest


def _view(content: str = "compiled context") -> CompiledView:
    report = ValidationReport(valid=True)
    manifest = ViewManifest.model_construct(validation=report)
    return CompiledView.model_construct(
        content=content, manifest=manifest, validation=report, evidence_handles=()
    )


def _fake(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + dedent(body), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _events_script(path: Path, *, agent: str = "codex", model: str = "gpt-test") -> Path:
    return _fake(
        path,
        f"""
        import json
        import os
        import sys

        if sys.argv[1:] == ["--version"]:
            print(json.dumps({{"agent": {agent!r}, "version": "1.2.3", "model": {model!r}, "capabilities": ["jsonl"]}}))
        else:
            print(json.dumps({{"agent": {agent!r}, "version": "1.2.3", "model": {model!r}, "argv": sys.argv[1:], "secret": os.getenv("CCS_ADAPTER_TEST_SECRET")}}))
            print(json.dumps({{"usage": {{"input_tokens": 7, "output_tokens": 3}}}}))
        """,
    )


def test_models_are_strict_frozen_and_bound_to_absolute_paths(tmp_path: Path) -> None:
    metadata = AgentMetadata(
        agent="codex", version="1.2.3", model="gpt-test", capabilities=("jsonl",)
    )
    assert metadata.capabilities == ("jsonl",)
    with pytest.raises((ValidationError, TypeError)):
        AgentMetadata(agent="", version="1.2.3", model="gpt-test")
    with pytest.raises((ValidationError, TypeError)):
        AgentTask(task_id="task", prompt="p", cwd=Path("relative"), timeout_seconds=1)
    with pytest.raises((ValidationError, TypeError)):
        UsageRecord(input_tokens=-1, output_tokens=0, raw_digest="sha256:" + "a" * 64)
    with pytest.raises(ValidationError):
        metadata.agent = "other"
    assert AgentTask(
        task_id="task", prompt="p", cwd=tmp_path, timeout_seconds=1
    ).cwd.is_absolute()


def test_codex_uses_exact_argv_and_parses_metadata_and_usage(tmp_path: Path) -> None:
    binary = _events_script(tmp_path / "codex-fake")
    adapter = CodexAdapter(binary=str(binary), timeout_seconds=5)
    task = AgentTask(task_id="task", prompt="solve", cwd=tmp_path, timeout_seconds=5)

    result = adapter.run(task, _view(), tmp_path)

    first = json.loads(result.stdout.splitlines()[0])
    assert first["argv"] == ["exec", "--ephemeral", "--json", "--", "compiled context\n\nsolve"]
    assert result.metadata == AgentMetadata(
        agent="codex", version="1.2.3", model="gpt-test", capabilities=()
    )
    assert result.usage is not None
    assert result.usage.input_tokens == 7
    assert result.usage.output_tokens == 3
    assert result.stderr_digest.startswith("sha256:")


def test_claude_uses_exact_argv(tmp_path: Path) -> None:
    binary = _events_script(tmp_path / "claude-fake", agent="claude", model="claude-test")
    adapter = ClaudeAdapter(binary=str(binary), timeout_seconds=5)
    task = AgentTask(task_id="task", prompt="solve", cwd=tmp_path, timeout_seconds=5)

    result = adapter.run(task, _view("context"), tmp_path)

    first = json.loads(result.stdout.splitlines()[0])
    assert first["argv"] == [
        "--bare",
        "-p",
        "context\n\nsolve",
        "--output-format",
        "json",
    ]
    assert result.metadata.agent == "claude"


def test_preflight_requires_stable_version_and_model(tmp_path: Path) -> None:
    binary = _fake(
        tmp_path / "missing-model",
        """
        import json
        print(json.dumps({"agent": "codex", "version": "1.2.3"}))
        """,
    )
    with pytest.raises(AdapterError) as error:
        CodexAdapter(binary=str(binary)).preflight()
    assert error.value.code == "ADAPTER_METADATA_INVALID"


def test_malformed_json_is_normalized_without_raw_output(tmp_path: Path) -> None:
    binary = _fake(
        tmp_path / "malformed",
        """
        import sys
        if sys.argv[1:] == ["--version"]:
            print('{"agent":"codex","version":"1.2.3","model":"gpt-test"}')
        else:
            print('not-json-with-secret=do-not-leak')
        """,
    )
    task = AgentTask(task_id="task", prompt="solve", cwd=tmp_path, timeout_seconds=5)
    with pytest.raises(AdapterError) as error:
        CodexAdapter(binary=str(binary)).run(task, _view(), tmp_path)
    assert error.value.code == "ADAPTER_OUTPUT_INVALID"
    assert "do-not-leak" not in str(error.value)


def test_nonzero_exit_is_redacted(tmp_path: Path) -> None:
    binary = _fake(
        tmp_path / "failed",
        """
        import sys
        print("stderr-secret", file=sys.stderr)
        raise SystemExit(23)
        """,
    )
    with pytest.raises(AdapterError) as error:
        CodexAdapter(binary=str(binary)).preflight()
    assert error.value.code == "ADAPTER_EXIT_NONZERO"
    assert "stderr-secret" not in str(error.value)


def test_missing_binary_and_timeout_are_bounded(tmp_path: Path) -> None:
    with pytest.raises(AdapterError) as missing:
        CodexAdapter(binary=str(tmp_path / "does-not-exist")).preflight()
    assert missing.value.code == "ADAPTER_BINARY_NOT_FOUND"

    binary = _fake(
        tmp_path / "slow",
        """
        import time
        time.sleep(2)
        """,
    )
    with pytest.raises(AdapterError) as timed_out:
        CodexAdapter(binary=str(binary), timeout_seconds=0.1).preflight()
    assert timed_out.value.code == "ADAPTER_TIMEOUT"


def test_output_is_truncated_but_metadata_is_parsed(tmp_path: Path) -> None:
    binary = _fake(
        tmp_path / "large",
        f"""
        import json
        import sys
        if sys.argv[1:] == ["--version"]:
            print(json.dumps({{"agent":"codex","version":"1.2.3","model":"gpt-test"}}))
        else:
            print(json.dumps({{"agent":"codex","version":"1.2.3","model":"gpt-test"}}))
            print(json.dumps({{"text": "x" * ({MAX_STDOUT_BYTES} + 100)}}))
        """,
    )
    task = AgentTask(task_id="task", prompt="solve", cwd=tmp_path, timeout_seconds=5)
    result = CodexAdapter(binary=str(binary)).run(task, _view(), tmp_path)
    assert len(result.stdout) <= MAX_STDOUT_BYTES


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_process_output_limit_is_enforced_during_read(
    tmp_path: Path, stream: str
) -> None:
    binary = _fake(
        tmp_path / f"oversized-{stream}",
        f"""
        import json
        import sys
        if sys.argv[1:] == ["--version"]:
            print(json.dumps({{"agent": "codex", "version": "1.2.3", "model": "gpt-test"}}))
            print("x" * ({MAX_EVENT_BYTES} + 1), file=sys.{stream})
        """,
    )
    with pytest.raises(AdapterError) as error:
        CodexAdapter(binary=str(binary), timeout_seconds=5).preflight()
    assert error.value.code == "ADAPTER_OUTPUT_LIMIT"


def test_duplicate_and_negative_usage_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(
        '{"usage":{"input_tokens":1}}\n{"usage":{"input_tokens":2}}\n',
        encoding="utf-8",
    )
    negative = tmp_path / "negative.jsonl"
    negative.write_text('{"usage":{"output_tokens":-1}}\n', encoding="utf-8")
    adapter = CodexAdapter(binary="codex")
    with pytest.raises(AdapterError) as duplicate_error:
        adapter.parse_usage(duplicate)
    assert duplicate_error.value.code == "ADAPTER_USAGE_INVALID"
    with pytest.raises(AdapterError) as negative_error:
        adapter.parse_usage(negative)
    assert negative_error.value.code == "ADAPTER_USAGE_INVALID"


def test_secret_environment_values_are_not_inherited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCS_ADAPTER_TEST_SECRET", "super-secret")
    binary = _events_script(tmp_path / "env-check")
    task = AgentTask(task_id="task", prompt="solve", cwd=tmp_path, timeout_seconds=5)
    result = CodexAdapter(binary=str(binary)).run(task, _view(), tmp_path)
    assert json.loads(result.stdout.splitlines()[0])["secret"] is None


def test_workspace_must_be_inside_task_cwd(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"outside-{os.getpid()}"
    outside.mkdir()
    binary = _events_script(tmp_path / "codex-fake")
    task = AgentTask(task_id="task", prompt="solve", cwd=tmp_path, timeout_seconds=5)
    with pytest.raises(AdapterError) as error:
        CodexAdapter(binary=str(binary)).run(task, _view(), outside)
    assert error.value.code == "ADAPTER_WORKSPACE_INVALID"
