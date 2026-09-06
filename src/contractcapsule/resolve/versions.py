"""Strict SemVer comparison for the M4 runtime profile."""

import operator
import re

# semantic-version 2.10.0 ships neither py.typed nor stubs; keep untyped I/O here.
from semantic_version import Version  # type: ignore[import-untyped]

from contractcapsule.compile.errors import CompileError
from contractcapsule.models.base import SEMVER_PATTERN


def parse_interface(value: str) -> tuple[str, str]:
    match = re.fullmatch(r"([^\s/]+(?:/[^\s/]+)*)/v(0|[1-9][0-9]*)", value)
    if match is None:
        raise CompileError("INTERFACE_INCOMPATIBLE")
    return match[1], value


def _normalized(value: str) -> str:
    if re.fullmatch(r"(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?", value):
        value += ".0" * (2 - value.count("."))
    if re.fullmatch(SEMVER_PATTERN, value) is None:
        raise CompileError("INVALID_VERSION_CONSTRAINT")
    return value


def constraint_terms(constraint: str) -> tuple[tuple[str, str], ...]:
    """Validate every conjunction, including terms after an unsatisfied term."""
    terms: list[tuple[str, str]] = []
    for term in constraint.split(","):
        match = re.fullmatch(r"[ \t]*(==|!=|>=|<=|>|<)[ \t]*([^\s]+)[ \t]*", term)
        if match is None:
            raise CompileError("INVALID_VERSION_CONSTRAINT")
        terms.append((match[1], _normalized(match[2])))
    return tuple(terms)


def satisfies(version: str, constraint: str) -> bool:
    terms = constraint_terms(constraint)
    current = Version(_normalized(version)).truncate("prerelease")
    comparisons = {
        "==": operator.eq,
        "!=": operator.ne,
        ">": operator.gt,
        ">=": operator.ge,
        "<": operator.lt,
        "<=": operator.le,
    }
    return all(
        bool(comparisons[operation](current, Version(value).truncate("prerelease")))
        for operation, value in terms
    )
