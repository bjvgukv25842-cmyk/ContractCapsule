"""Claude Code non-interactive adapter."""

from __future__ import annotations

from typing import ClassVar

from contractcapsule.adapters.base import MAX_TIMEOUT_SECONDS, ProcessAgentAdapter


class ClaudeAdapter(ProcessAgentAdapter):
    agent_name: ClassVar[str] = "claude"

    def __init__(self, binary: str = "claude", timeout_seconds: float = MAX_TIMEOUT_SECONDS) -> None:
        super().__init__(binary, timeout_seconds)

    def _run_argv(self, prompt: str) -> tuple[str, ...]:
        return (self.binary, "--bare", "-p", prompt, "--output-format", "json")


__all__ = ["ClaudeAdapter"]
