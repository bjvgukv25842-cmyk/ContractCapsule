"""Read-only, object-addressed source snapshots for M5 twin runs."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from contractcapsule.swap.trees import FrozenTree, RunnerError
from contractcapsule.validate.models import RunnerConfig
from contractcapsule.validate.run_models import Snapshot, TreeEntry, digest_bytes


def git_tree(
    root: Path, revision: str, config: RunnerConfig, repository: str | None = None
) -> FrozenTree:
    """Materialize a complete regular-file Git tree without touching the worktree.

    Every command is local, object addressed, and run with replacement objects
    disabled.  Symlinks, submodules and executable Git tree modes are rejected.
    """
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
        raise RunnerError("source repository root unavailable")
    if not isinstance(revision, str) or not re.fullmatch(r"sha(?:1:[0-9a-f]{40}|256:[0-9a-f]{64})", revision):
        raise RunnerError("invalid source revision")
    raw = revision.split(":", 1)[1]
    if repository is not None:
        try:
            configured = subprocess.check_output(
                ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RunnerError("source repository identity unavailable") from exc
        if _normalize_remote(configured) != _normalize_remote(repository):
            raise RunnerError("source repository identity mismatch")
    try:
        subprocess.run(
            ["git", "--no-replace-objects", "-C", str(root), "cat-file", "-e", raw + "^{commit}"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        listing = subprocess.check_output(
            ["git", "--no-replace-objects", "-C", str(root), "ls-tree", "-r", "-z", raw],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RunnerError("immutable Git source cannot be read locally") from exc
    files: list[tuple[str, bytes]] = []
    entries = [TreeEntry(path=".", kind="directory", mode=0o755)]
    for record in listing.split(b"\0"):
        if not record:
            continue
        try:
            header, path_bytes = record.split(b"\t", 1)
            mode_b, kind, object_id = header.split()
            path = path_bytes.decode("utf-8")
            mode = int(mode_b, 8)
        except (ValueError, UnicodeDecodeError) as exc:
            raise RunnerError("malformed Git tree") from exc
        if kind != b"blob" or mode not in {0o100644, 0o100755}:
            raise RunnerError("unsupported Git tree entry")
        try:
            data = subprocess.check_output(
                ["git", "--no-replace-objects", "-C", str(root), "cat-file", "blob", object_id.decode()],
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RunnerError("Git blob cannot be read locally") from exc
        relative = path.replace("\\", "/")
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            raise RunnerError("unsafe Git path")
        files.append((relative, data))
        entries.append(
            TreeEntry(path=relative, kind="file", mode=0o755 if mode == 0o100755 else 0o644,
                      digest=digest_bytes(data), size=len(data))
        )
        for parent in Path(relative).parents:
            name = parent.as_posix()
            if name != "." and not any(item.path == name for item in entries):
                entries.append(TreeEntry(path=name, kind="directory", mode=0o755))
    tree = FrozenTree(Snapshot(entries=tuple(sorted(entries, key=lambda item: item.path))), tuple(sorted(files)))
    from contractcapsule.swap.trees import validate_tree

    validate_tree(tree, config)
    return tree


def _normalize_remote(value: str) -> str:
    remote = value.strip()
    if remote.startswith("git@") and ":" in remote:
        identity, path = remote.split(":", 1)
        remote = f"https://{identity.removeprefix('git@')}/{path}"
    elif remote.startswith("ssh://"):
        parsed = urlsplit(remote)
        if parsed.hostname is None:
            raise RunnerError("invalid source repository")
        remote = f"https://{parsed.hostname.lower()}{parsed.path}"
    return remote.removesuffix(".git").removesuffix("/").lower()
