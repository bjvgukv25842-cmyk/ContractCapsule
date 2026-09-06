"""Offline Git object reads and source-map/anchor integrity for runtime evidence."""

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from contractcapsule.build.atomize import (
    _config_spans,
    _markdown_spans,
    _python_spans,
    _text_spans,
)
from contractcapsule.build.ingest import (
    _normalize_git_remote,
    _parser_kind,
    _strict_absolute,
)
from contractcapsule.compile.errors import CompileError
from contractcapsule.models.core import GitImmutableEvidence


def _git(root: Path, *arguments: str) -> bytes:
    # Never inherit object redirection, injected config, or partial-clone transport.
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        GIT_NO_LAZY_FETCH="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
    )
    if "GIT_TRACE" in os.environ:
        environment["GIT_TRACE"] = os.environ["GIT_TRACE"]
    return subprocess.check_output(
        [
            "git",
            "--no-lazy-fetch",
            "--no-replace-objects",
            "-c",
            "protocol.allow=never",
            "-C",
            str(root),
            *arguments,
        ],
        env=environment,
        stderr=subprocess.PIPE,
        timeout=30,
    )


def read_git_evidence(root: Path, record: GitImmutableEvidence) -> bytes:
    try:
        root = _strict_absolute(root)
        configured = _git(root, "config", "--get", "remote.origin.url").decode().strip()
        if _normalize_git_remote(configured) != _normalize_git_remote(
            record.repository
        ):
            raise CompileError("EVIDENCE_UNAVAILABLE")
        revision = record.revision.split(":", 1)[1]
        _git(root, "cat-file", "-e", revision + "^{commit}")
        return _git(root, "cat-file", "blob", revision + ":" + record.path)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        raise CompileError("EVIDENCE_UNAVAILABLE") from None


def validate_git_locator(record: GitImmutableEvidence, text: str) -> None:
    locator = record.locator
    if "x-source-map" in record.extensions:
        source_map = record.extensions["x-source-map"]
        expected = {
            "binding_id": record.evidence_id,
            "mode": record.mode,
            "repository": record.repository,
            "revision": record.revision,
            "path": record.path,
            "content_digest": record.content_digest,
            **locator.model_dump(),
        }
        if not isinstance(source_map, Mapping) or any(
            source_map.get(k) != v for k, v in expected.items()
        ):
            raise CompileError("EVIDENCE_INTEGRITY")
    kind = _parser_kind(Path(record.path))
    if kind == "markdown":
        spans = _markdown_spans(text)
    elif kind == "code" and record.path.endswith(".py"):
        spans = _python_spans(text)
    elif kind in {"json", "yaml"}:
        spans = _config_spans(text, kind)
    else:
        spans = _text_spans(text)
    if not any(
        span.symbol_or_heading == locator.symbol_or_heading
        and locator.start_line <= span.start_line <= span.end_line <= locator.end_line
        for span in spans
    ):
        raise CompileError("EVIDENCE_INTEGRITY")
