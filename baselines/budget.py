"""Deterministic, fail-closed accounting for CapsuleBench context artifacts.

The benchmark compares representations, so a provider must never silently
truncate a view to make it fit.  This module owns the shared budget contract:
the same neutral tokenizer is used for every condition and tokenizer or
encoding failures are comparison blockers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from contractcapsule.compile.budget import LocalTokenCounter


class BudgetError(ValueError):
    """A malformed or unverifiable runtime-view budget."""


class BudgetOverflow(BudgetError):
    """A context artifact exceeded its declared comparison budget."""


class TokenizerFailure(BudgetError):
    """The locked neutral tokenizer could not account for a payload."""


@dataclass(frozen=True, slots=True, init=False)
class Budget:
    """A common maximum runtime-view budget measured in neutral tokens.

    ``max_bytes`` is optional and is used as an additional UTF-8 bound.  The
    token limit remains the comparison budget; the byte bound protects the
    artifact serialization boundary from malformed or unexpectedly large
    strings.
    """

    max_tokens: int
    max_bytes: int | None = None

    def __init__(
        self,
        max_tokens: int | None = None,
        max_bytes: int | None = None,
        *,
        tokens: int | None = None,
    ) -> None:
        if max_tokens is None:
            max_tokens = tokens
        elif tokens is not None and tokens != max_tokens:
            raise BudgetError("conflicting token budget values")
        if max_tokens is None:
            raise BudgetError("budget requires a maximum token count")
        object.__setattr__(self, "max_tokens", max_tokens)
        object.__setattr__(self, "max_bytes", max_bytes)
        self.__post_init__()

    def __post_init__(self) -> None:
        if type(self.max_tokens) is not int or self.max_tokens < 0:
            raise BudgetError("budget must be a non-negative integer")
        if self.max_bytes is not None and (
            type(self.max_bytes) is not int or self.max_bytes < 0
        ):
            raise BudgetError("byte budget must be a non-negative integer")

    @property
    def tokens(self) -> int:
        """Alias used by experiment configuration records."""

        return self.max_tokens

    @property
    def available(self) -> int:
        return self.max_tokens

    @property
    def limit(self) -> int:
        return self.max_tokens

    def __int__(self) -> int:
        return self.max_tokens

    def __index__(self) -> int:
        return self.max_tokens

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Budget):
            return (
                self.max_tokens == other.max_tokens
                and self.max_bytes == other.max_bytes
            )
        if type(other) is int:
            return self.max_tokens == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.max_tokens, self.max_bytes))


# Explicit aliases make the public boundary easy to discover without adding
# multiple budget implementations.
RuntimeBudget = Budget
ContextBudget = Budget


def _strict_int(value: object, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise BudgetError(f"{field} must be a non-negative integer")
    return value


def normalize_budget(value: object) -> Budget:
    """Normalize integer/config/model budgets without coercion.

    Existing CCS ``ViewBudget`` objects expose ``available``; that value is
    intentionally preferred over ``model_input_tokens`` because reserved
    system/tool/headroom tokens are not part of a runtime view.
    """

    if isinstance(value, Budget):
        return value
    if type(value) is int:
        return Budget(value)

    raw: object = None
    max_bytes: object = None
    if isinstance(value, Mapping):
        for key in ("max_tokens", "tokens", "available", "budget", "model_input_tokens"):
            if key in value:
                raw = value[key]
                break
        max_bytes = value.get("max_bytes")
    else:
        for key in ("max_tokens", "tokens", "available", "budget", "model_input_tokens"):
            if hasattr(value, key):
                raw = getattr(value, key)
                break
        if hasattr(value, "max_bytes"):
            max_bytes = value.max_bytes  # type: ignore[attr-defined]

    if raw is None:
        raise BudgetError("budget requires a maximum token count")
    tokens = _strict_int(raw, field="budget")
    bytes_limit = None if max_bytes is None else _strict_int(max_bytes, field="byte budget")
    return Budget(tokens, bytes_limit)


@lru_cache(maxsize=1)
def _neutral_counter() -> LocalTokenCounter:
    """Load the repository-locked neutral tokenizer exactly once."""

    try:
        return LocalTokenCounter(model_id="capsulebench-neutral")
    except Exception as error:
        raise TokenizerFailure("tokenizer_unavailable") from error


def count_tokens(text: str) -> int:
    """Count ordinary text with the locked neutral tokenizer.

    No fallback tokenizer is permitted: comparing conditions with different
    accounting would invalidate budget parity.
    """

    if type(text) is not str:
        raise TokenizerFailure("invalid_token_input")
    try:
        text.encode("utf-8", errors="strict")
        result = _neutral_counter().count(text)
    except TokenizerFailure:
        raise
    except Exception as error:
        raise TokenizerFailure("tokenizer_unavailable") from error
    if type(result) is not int or result < 0:
        raise TokenizerFailure("tokenizer_unavailable")
    return result


def payload_bytes(text: str) -> int:
    if type(text) is not str:
        raise BudgetError("payload must be text")
    try:
        return len(text.encode("utf-8", errors="strict"))
    except UnicodeError as error:
        raise BudgetError("payload encoding failed") from error


def enforce_budget(
    text: str,
    budget: object,
    *,
    p0: bool = False,
) -> tuple[Budget, int, int]:
    """Account ``text`` and reject overflow before an artifact is returned."""

    normalized = normalize_budget(budget)
    byte_count = payload_bytes(text)
    token_count = count_tokens(text)
    if token_count > normalized.max_tokens or (
        normalized.max_bytes is not None and byte_count > normalized.max_bytes
    ):
        code = "p0_budget_overflow" if p0 else "budget_overflow"
        raise BudgetOverflow(code)
    return normalized, token_count, byte_count


def budget_digest(value: object) -> str:
    """Return a stable digest for a declared budget, excluding condition data."""

    budget = normalize_budget(value)
    payload = json.dumps(
        {"max_tokens": budget.max_tokens, "max_bytes": budget.max_bytes},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def assert_budget_parity(artifacts: object, budget: object) -> None:
    """Require every artifact to declare and satisfy one exact common budget."""

    expected = normalize_budget(budget)
    if (
        isinstance(artifacts, Iterable)
        and not isinstance(artifacts, (str, bytes, Mapping))
    ):
        try:
            artifact_list: tuple[Any, ...] = tuple(artifacts)
        except TypeError as error:
            raise BudgetError("artifacts must be a sequence") from error
    else:
        raise BudgetError("artifacts must be a sequence")
    if not artifact_list:
        raise BudgetError("at least one artifact is required")

    seen_conditions: set[object] = set()
    for artifact in artifact_list:
        try:
            declared = normalize_budget(artifact.budget)
            tokens = artifact.token_count
            bytes_used = artifact.byte_count
            condition = artifact.condition
        except (AttributeError, TypeError, ValueError) as error:
            raise BudgetError("invalid context artifact") from error
        if declared != expected:
            raise BudgetError("budget mismatch across context artifacts")
        if type(tokens) is not int or tokens < 0 or tokens > expected.max_tokens:
            raise BudgetOverflow("budget_overflow")
        if type(bytes_used) is not int or bytes_used < 0:
            raise BudgetError("invalid artifact byte accounting")
        if expected.max_bytes is not None and bytes_used > expected.max_bytes:
            raise BudgetOverflow("budget_overflow")
        if condition in seen_conditions:
            raise BudgetError("duplicate condition artifact")
        seen_conditions.add(condition)


__all__ = [
    "Budget",
    "BudgetError",
    "BudgetOverflow",
    "ContextBudget",
    "RuntimeBudget",
    "TokenizerFailure",
    "assert_budget_parity",
    "budget_digest",
    "count_tokens",
    "enforce_budget",
    "normalize_budget",
    "payload_bytes",
]
