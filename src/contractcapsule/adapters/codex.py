"""Codex non-interactive adapter."""

from __future__ import annotations

from typing import ClassVar

from contractcapsule.adapters.base import MAX_TIMEOUT_SECONDS, ProcessAgentAdapter


class CodexAdapter(ProcessAgentAdapter):
    agent_name: ClassVar[str] = "codex"

    def __init__(self, binary: str = "codex", timeout_seconds: float = MAX_TIMEOUT_SECONDS) -> None:
        super().__init__(binary, timeout_seconds)

    def _run_argv(self, prompt: str) -> tuple[str, ...]:
        return (self.binary, "exec", "--ephemeral", "--json", "--", prompt)


__all__ = ["CodexAdapter"]
