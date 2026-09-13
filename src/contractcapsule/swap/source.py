"""Bounded local Git-object snapshots; repository identity is host configuration."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterator
from pathlib import Path

from contractcapsule.models.base import is_safe_relative_path
from contractcapsule.swap.process_io import checked
from contractcapsule.swap.trees import FrozenTree, RunnerError, validate_tree
from contractcapsule.validate.models import RunnerConfig
from contractcapsule.validate.run_models import Snapshot, TreeEntry, digest_bytes


def _git(root: Path, *args: str, limit: int = 65536) -> bytes:
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment.update(
        GIT_NO_LAZY_FETCH="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
    )
    return checked(
        [
            "git",
            "--no-lazy-fetch",
            "--no-replace-objects",
            "-c",
            "protocol.allow=never",
            "-C",
            str(root),
            *args,
        ],
        env=environment,
        timeout=30,
        out_limit=limit,
        err_limit=65536,
    )


def _object(root: Path, kind: str, object_id: str, limit: int) -> bytes:
    data = _git(root, "cat-file", kind, object_id, limit=limit)
    algorithm = "sha1" if len(object_id) == 40 else "sha256"
    encoded = f"{kind} {len(data)}\0".encode() + data
    if hashlib.new(algorithm, encoded).hexdigest() != object_id:
        raise RunnerError("Git object digest mismatch")
    return data


def _entries(data: bytes, oid_size: int) -> Iterator[tuple[str, int, str, bool]]:
    offset = 0
    while offset < len(data):
        try:
            end = data.index(b"\0", offset)
            mode, raw_name = data[offset:end].split(b" ", 1)
            name = raw_name.decode("utf-8")
            number = int(mode, 8)
            if number not in {0o40000, 0o100644, 0o100755}:
                raise ValueError
            if not is_safe_relative_path(name) or "/" in name or "\\" in name:
                raise ValueError
            raw_oid = data[end + 1:end + 1 + oid_size]
            if len(raw_oid) != oid_size:
                raise ValueError
            offset = end + 1 + oid_size
            yield name, (0o755 if number == 0o40000 else number & 0o777), raw_oid.hex(), number == 0o40000
        except (ValueError, UnicodeError):
            raise RunnerError("unsupported or unsafe Git tree entry") from None


def _walk(root: Path, tree_id: str, config: RunnerConfig) -> FrozenTree:
    entries = [TreeEntry(path=".", kind="directory", mode=0o755)]
    files: list[tuple[str, bytes]] = []
    pending = [("", tree_id)]
    remaining = config.output_tree_limit_bytes
    metadata = config.output_tree_file_limit * 8192
    while pending:
        prefix, object_id = pending.pop()
        data = _object(root, "tree", object_id, metadata)
        metadata -= len(data)
        for name, mode, oid, directory in _entries(data, len(tree_id) // 2):
            path = prefix + name
            if len(entries) >= config.output_tree_file_limit:
                raise RunnerError("source entry limit")
            if directory:
                entries.append(TreeEntry(path=path, mode=mode, kind="directory"))
                pending.append((path + "/", oid))
            else:
                blob = _object(root, "blob", oid, remaining)
                remaining -= len(blob)
                files.append((path, blob))
                entries.append(TreeEntry(path=path, mode=mode, kind="file", digest=digest_bytes(blob), size=len(blob)))
    result = FrozenTree(Snapshot(entries=tuple(sorted(entries, key=lambda e: e.path))), tuple(sorted(files)))
    validate_tree(result, config)
    return result


def git_tree(
    root: Path, revision: str, config: RunnerConfig, repository: str | None = None
) -> FrozenTree:
    """Read exact commit bytes, ignoring dirty files, filters and replacement refs.

    Caller resolves repository through its exact trusted mapping; a mutable
    remote URL is neither an identity authority nor a network fallback.
    """
    if (
        not isinstance(root, Path)
        or not root.is_absolute()
        or not root.is_dir()
        or root.is_symlink()
    ):
        raise RunnerError("source repository root unavailable")
    if not isinstance(revision, str) or not re.fullmatch(
        r"sha(?:1:[0-9a-f]{40}|256:[0-9a-f]{64})", revision
    ):
        raise RunnerError("invalid source revision")
    raw = revision.split(":", 1)[1]
    commit = _object(root, "commit", raw, 1024 * 1024)
    first_line = commit.split(b"\n", 1)[0]
    if not re.fullmatch(b"tree [0-9a-f]{" + str(len(raw)).encode() + b"}", first_line):
        raise RunnerError("invalid Git commit tree")
    return _walk(root, first_line[5:].decode("ascii"), config)
