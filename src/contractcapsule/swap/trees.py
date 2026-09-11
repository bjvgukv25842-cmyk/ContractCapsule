"""Complete, bounded immutable tree bytes; no symlinks or special files."""

import io
import stat
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from contractcapsule.validate.models import RunnerConfig
from contractcapsule.validate.run_models import Snapshot, TreeEntry, digest_bytes
from contractcapsule.validate.snapshots import validate_snapshot


class RunnerError(ValueError):
    """Fail-closed execution preparation/capture failure."""


@dataclass(frozen=True)
class FrozenTree:
    snapshot: Snapshot
    files: tuple[tuple[str, bytes], ...]

    def materialize(self, root: Path) -> None:
        root.mkdir(mode=0o755)
        contents = dict(self.files)
        for entry in self.snapshot.entries:
            target = root if entry.path == "." else root / entry.path
            if entry.kind == "directory":
                target.mkdir(exist_ok=True)
            else:
                target.write_bytes(contents[entry.path])
        for entry in reversed(self.snapshot.entries):
            (root / entry.path).chmod(entry.mode)


def read_tar(raw: bytes, limits: RunnerConfig, *, docker: bool = False) -> FrozenTree:
    entries: list[TreeEntry] = []
    files: list[tuple[str, bytes]] = []
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for member in archive:
            name = member.name.rstrip("/")
            if docker:
                name = name.partition("/")[2] or "."
            if not docker and name == "":
                name = "."
            _safe_name(name)
            if len(entries) >= limits.output_tree_file_limit:
                raise RunnerError("tree limit exceeded")
            total += member.size
            if total > limits.output_tree_limit_bytes:
                raise RunnerError("tree limit exceeded")
            entry, data = _member(archive, member, name)
            entries.append(entry)
            if data is not None:
                files.append((name, data))
    if not any(e.path == "." for e in entries):
        entries.append(TreeEntry(path=".", kind="directory", mode=0o755))
    snapshot = Snapshot(entries=tuple(sorted(entries, key=lambda e: e.path)))
    validate_snapshot(snapshot, limits)
    return FrozenTree(snapshot, tuple(sorted(files)))


def _safe_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise RunnerError("unsafe tree path")
    if name != "." and str(path) != name:
        raise RunnerError("unsafe tree path")


def _member(archive, member, name) -> tuple[TreeEntry, bytes | None]:
    if member.isdir():
        return TreeEntry(path=name, kind="directory", mode=member.mode), None
    if not member.isfile() or member.linkname:
        raise RunnerError("unsupported tree entry")
    stream = archive.extractfile(member)
    if stream is None:
        raise RunnerError("incomplete tree")
    data = stream.read(member.size + 1)
    if len(data) != member.size:
        raise RunnerError("incomplete tree")
    return TreeEntry(path=name, kind="file", mode=member.mode,
                     digest=digest_bytes(data), size=len(data)), data


def capture_tree(root: Path, limits: RunnerConfig) -> FrozenTree:
    entries: list[TreeEntry] = []
    files: list[tuple[str, bytes]] = []
    total = 0
    for path in (root, *sorted(root.rglob("*"))):
        info = path.lstat()
        name = path.relative_to(root).as_posix()
        _safe_name(name)
        if len(entries) >= limits.output_tree_file_limit:
            raise RunnerError("tree limit exceeded")
        if stat.S_ISDIR(info.st_mode):
            entries.append(TreeEntry(path=name, kind="directory", mode=stat.S_IMODE(info.st_mode)))
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RunnerError("unsupported tree entry")
        total += info.st_size
        if total > limits.output_tree_limit_bytes:
            raise RunnerError("tree limit exceeded")
        data = path.read_bytes()
        if len(data) != info.st_size:
            raise RunnerError("tree changed during capture")
        entries.append(TreeEntry(path=name, kind="file", mode=stat.S_IMODE(info.st_mode),
                                 digest=digest_bytes(data), size=len(data)))
        files.append((name, data))
    snapshot = Snapshot(entries=tuple(sorted(entries, key=lambda e: e.path)))
    validate_snapshot(snapshot, limits)
    return FrozenTree(snapshot, tuple(files))
