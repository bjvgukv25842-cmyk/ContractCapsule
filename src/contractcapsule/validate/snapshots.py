"""Complete host-captured tree validation and source-relative change sets."""

from pathlib import PurePosixPath

from contractcapsule.models.base import is_safe_relative_path
from contractcapsule.resolve.scope import path_matches
from contractcapsule.validate.journal import RecordError
from contractcapsule.validate.models import RunnerConfig
from contractcapsule.validate.run_models import Snapshot


def validate_snapshot(snapshot: Snapshot, limits: RunnerConfig) -> None:
    entries = {e.path: e for e in snapshot.entries}
    paths = tuple(e.path for e in snapshot.entries)
    if (
        len(entries) != len(paths)
        or paths != tuple(sorted(paths))
        or "." not in entries
        or entries["."].kind != "directory"
        or len(entries) > limits.output_tree_file_limit
        or sum(e.size for e in entries.values()) > limits.output_tree_limit_bytes
    ):
        raise RecordError("record rejected")
    for entry in entries.values():
        if entry.kind == "directory" and (entry.digest is not None or entry.size != 0):
            raise RecordError("record rejected")
        if entry.kind == "file" and entry.digest is None:
            raise RecordError("record rejected")
        if entry.path == ".":
            continue
        if not is_safe_relative_path(entry.path) or any(
            c in entry.path for c in "*?[]"
        ):
            raise RecordError("record rejected")
        parent = entries.get(str(PurePosixPath(entry.path).parent))
        if parent is None or parent.kind != "directory":
            raise RecordError("record rejected")


def tree_delta(before: Snapshot, after: Snapshot) -> tuple[str, ...]:
    old = {e.path: e for e in before.entries}
    new = {e.path: e for e in after.entries}
    return tuple(sorted(p for p in old.keys() | new.keys() if old.get(p) != new.get(p)))


def scope_violations(
    paths: tuple[str, ...], allowed: tuple[str, ...], forbidden: tuple[str, ...]
) -> bool:
    return any(
        p == "."
        or not any(path_matches(g, p) for g in allowed)
        or any(path_matches(g, p) for g in forbidden)
        for p in paths
    )
