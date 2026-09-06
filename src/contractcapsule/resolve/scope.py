"""Anchored POSIX scope matching with polynomial, nonrecursive glob evaluation."""

from contractcapsule.compile.errors import CompileError
from contractcapsule.models.base import is_safe_relative_path
from contractcapsule.models.view import TaskContext


def _segments(value: str, *, pattern: bool) -> tuple[str, ...]:
    if not isinstance(value, str) or not is_safe_relative_path(value):
        raise CompileError("INVALID_SCOPE")
    parts = tuple(value.split("/"))
    if any(char in value for char in "?[]"):
        raise CompileError("INVALID_SCOPE")
    if not pattern and "*" in value:
        raise CompileError("INVALID_SCOPE")
    if any("**" in part and part != "**" for part in parts):
        raise CompileError("INVALID_SCOPE")
    return parts


def _segment_matches(pattern: str, value: str) -> bool:
    previous = [True] + [False] * len(value)
    for character in pattern:
        current = [previous[0] and character == "*"]
        for index, literal in enumerate(value, 1):
            current.append(
                (previous[index] or current[index - 1])
                if character == "*"
                else previous[index - 1] and character == literal
            )
        previous = current
    return previous[-1]


def _matches(pattern: tuple[str, ...], path: tuple[str, ...]) -> bool:
    previous = [True] + [False] * len(path)
    for part in pattern:
        current = [previous[0] and part == "**"]
        for index, segment in enumerate(path, 1):
            current.append(
                (previous[index] or current[index - 1])
                if part == "**"
                else previous[index - 1] and _segment_matches(part, segment)
            )
        previous = current
    return previous[-1]


def path_matches(pattern: str, path: str) -> bool:
    return _matches(_segments(pattern, pattern=True), _segments(path, pattern=False))


def paths_match(patterns: tuple[str, ...], paths: tuple[str, ...]) -> bool:
    # Validate the complete scope before short-circuiting on any intersection.
    parsed_patterns = tuple(_segments(item, pattern=True) for item in patterns)
    parsed_paths = tuple(_segments(item, pattern=False) for item in paths)
    return any(
        _matches(pattern, path) for pattern in parsed_patterns for path in parsed_paths
    )


def atom_scope_matches(scope: tuple[str, ...], task: TaskContext) -> bool:
    dimensions: dict[str, list[str]] = {"repository": [], "path": [], "environment": []}
    if not scope:
        raise CompileError("INVALID_SCOPE")
    for selector in scope:
        if not isinstance(selector, str):
            raise CompileError("INVALID_SCOPE")
        dimension, separator, value = selector.partition(":")
        if not separator or dimension not in dimensions or not value:
            raise CompileError("INVALID_SCOPE")
        dimensions[dimension].append(value)
    path_scope = tuple(dimensions["path"])
    path_allowed = paths_match(path_scope, task.paths) if path_scope else True
    return (
        (not dimensions["repository"] or task.repository in dimensions["repository"])
        and (
            not dimensions["environment"]
            or task.environment in dimensions["environment"]
        )
        and path_allowed
    )
