"""Fail-closed loaders for CapsuleBench manifests and task packages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.constructor import ConstructorError

from benchmark.schema import BenchmarkManifest, TaskSpec

# Process-local capability.  A public ``TaskSpec.model_validate`` call cannot
# manufacture this token; callers must come through ``load_task``.
_LOADER_ATTESTATION = object()
_RUNTIME_DIRS = frozenset({"__pycache__", ".pytest_cache"})


class BenchmarkLoadError(ValueError):
    """A task or manifest cannot be trusted for benchmark use."""


class _UniqueSafeLoader(yaml.SafeLoader):
    pass


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _construct_mapping(loader: _UniqueSafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError("while constructing a mapping", node.start_mark, f"duplicate key: {key}", key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            value = yaml.load(handle, Loader=_UniqueSafeLoader)
    except ConstructorError as error:
        if "duplicate key" in str(error).lower():
            raise BenchmarkLoadError("duplicate YAML key") from None
        raise BenchmarkLoadError("unable to load YAML") from None
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise BenchmarkLoadError(f"unable to load YAML: {path.name}") from error
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise BenchmarkLoadError("YAML root must be an object")
    return value


def _tuplify(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuplify(item) for item in value)
    if isinstance(value, dict):
        return {key: _tuplify(item) for key, item in value.items()}
    return value


def _validate_digest(value: str) -> str:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise BenchmarkLoadError("invalid digest")
    try:
        int(value[7:], 16)
    except ValueError as error:
        raise BenchmarkLoadError("invalid digest") from error
    return value


def _contained_file(root: Path, relative: str) -> Path:
    if not relative or relative.startswith("/") or "\\" in relative:
        raise BenchmarkLoadError("path must be repository-relative")
    raw_candidate = root / relative
    if raw_candidate.is_symlink():
        raise BenchmarkLoadError("symlinked task files are not allowed")
    candidate = raw_candidate.resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise BenchmarkLoadError("path escapes task package") from error
    return candidate


def _reject_symlink_components(path: Path) -> Path:
    """Reject a package path whose parent components redirect elsewhere."""

    absolute = path if path.is_absolute() else Path.cwd() / path
    probe = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        probe /= part
        if probe.is_symlink():
            # macOS exposes /tmp and /var as stable aliases into /private.
            # They are OS namespace aliases, not caller-controlled redirects.
            resolved = probe.resolve(strict=False)
            if not (
                probe in {Path("/tmp"), Path("/var")}
                and resolved.parent == Path("/private")
            ):
                raise BenchmarkLoadError(
                    "symlinked task package components are not allowed"
                )
    return absolute


def _package_digest(root: Path) -> str:
    """Hash authoritative package files in a deterministic order."""

    entries: list[Path] = []
    for entry in root.rglob("*"):
        relative = entry.relative_to(root)
        if entry.is_symlink():
            raise BenchmarkLoadError("symlinked task package entries are not allowed")
        if any(part in _RUNTIME_DIRS for part in relative.parts):
            continue
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise BenchmarkLoadError("task package contains a non-regular entry")
        entries.append(relative)
    digest = hashlib.sha256()
    for relative in sorted(entries, key=lambda item: item.as_posix()):
        data = (root / relative).read_bytes()
        encoded_path = relative.as_posix().encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return "sha256:" + digest.hexdigest()


def _package_entry(root: Path, relative: str, *, directory: bool) -> Path:
    """Resolve a required package entry without following symlink components."""

    raw = Path(relative)
    probe = root
    for part in raw.parts:
        probe = probe / part
        if probe.is_symlink():
            raise BenchmarkLoadError("symlinked task package entries are not allowed")
    candidate = _contained_file(root, relative)
    if directory and not candidate.is_dir():
        raise BenchmarkLoadError(f"required task package directory is missing: {relative}")
    if not directory and not candidate.is_file():
        raise BenchmarkLoadError(f"required task package file is missing: {relative}")
    return candidate


def _has_regular_files(path: Path) -> bool:
    return any(
        item.is_file() and not item.is_symlink()
        for item in path.rglob("*")
    )


def _require_complete_package(root: Path) -> None:
    """Approved tasks must contain the complete frozen CapsuleBench layout."""

    for relative in (
        "capsules/old",
        "capsules/new",
        "gold",
        "tests",
        "tests/target",
        "tests/invariant",
        "tests/spillover",
        "licenses",
    ):
        directory = _package_entry(root, relative, directory=True)
        if relative.startswith(("capsules/", "tests/", "gold", "licenses")) and not _has_regular_files(
            directory
        ):
            raise BenchmarkLoadError(
                f"required task package directory is empty: {relative}"
            )
    for relative in (
        "prompt.md",
        "gold/required-atoms.json",
        "gold/target-effects.yaml",
        "gold/protected-invariants.yaml",
        "gold/forbidden-spillover.yaml",
        "licenses/provenance.json",
    ):
        entry = _package_entry(root, relative, directory=False)
        if not entry.read_bytes():
            raise BenchmarkLoadError(f"required task package file is empty: {relative}")


def load_task(task_dir: Path) -> TaskSpec:
    """Load one task package without following paths outside its root."""

    root = _reject_symlink_components(Path(task_dir))
    if not root.is_dir() or root.is_symlink():
        raise BenchmarkLoadError("task package must be a real directory")
    task_yaml = _contained_file(root, "task.yaml")
    if not task_yaml.is_file():
        raise BenchmarkLoadError("task.yaml is missing")
    raw = _read_yaml(task_yaml)
    try:
        task = TaskSpec.model_validate(_tuplify(raw))
    except ValidationError as error:
        message = str(error).lower()
        if "relative" in message or "path" in message:
            raise BenchmarkLoadError("relative check path is invalid") from None
        raise BenchmarkLoadError("task schema is invalid") from None

    lock_file = root / "repository.lock"
    if lock_file.exists():
        if lock_file.is_symlink() or not lock_file.is_file():
            raise BenchmarkLoadError("repository.lock must be a regular file")
        try:
            lock = json.loads(
                lock_file.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_json_pairs,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            if isinstance(error, ValueError) and str(error) == "duplicate JSON key":
                raise BenchmarkLoadError("duplicate JSON key") from None
            raise BenchmarkLoadError("repository.lock is invalid") from error
        try:
            digest = lock["content_digest"]
        except (KeyError, TypeError) as error:
            raise BenchmarkLoadError("repository.lock is invalid") from error
        _validate_digest(digest)
        expected = task.repository.content_digest
        if expected is not None and digest != expected:
            raise BenchmarkLoadError("repository lock digest mismatch")
    elif task.human_approval.value == "approved":
        raise BenchmarkLoadError("approved task repository.lock is missing")
    if task.human_approval.value == "approved":
        _require_complete_package(root)
    package_digest = _package_digest(root)
    object.__setattr__(task, "_loader_attestation", _LOADER_ATTESTATION)
    object.__setattr__(task, "_loader_root", root.resolve())
    object.__setattr__(task, "_loader_package_digest", package_digest)
    return task


def require_loaded_task(task: object) -> TaskSpec:
    """Require a loader-attested task and revalidate its package on use.

    Re-reading the package closes the gap where a caller keeps a previously
    loaded model after changing ``task.yaml`` or the package layout.
    """

    if type(task) is not TaskSpec:
        raise BenchmarkLoadError("execution requires a loader-owned TaskSpec")
    if getattr(task, "_loader_attestation", None) is not _LOADER_ATTESTATION:
        raise BenchmarkLoadError("execution requires a loader-owned TaskSpec")
    root = getattr(task, "_loader_root", None)
    if not isinstance(root, Path):
        raise BenchmarkLoadError("loader task package root is unavailable")
    current = load_task(root)
    if (
        current.model_dump(mode="python") != task.model_dump(mode="python")
        or getattr(current, "_loader_package_digest", None)
        != getattr(task, "_loader_package_digest", None)
    ):
        raise BenchmarkLoadError("task package changed after loading")
    return current


def load_manifest(path: Path) -> BenchmarkManifest:
    """Load the immutable manifest and validate every inline task."""

    manifest_path = Path(path)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BenchmarkLoadError("benchmark manifest must be a regular file")
    try:
        raw = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_pairs,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error) == "duplicate JSON key":
            raise BenchmarkLoadError("duplicate JSON key") from None
        raise BenchmarkLoadError("benchmark manifest is invalid JSON") from error
    try:
        manifest = BenchmarkManifest.model_validate(_tuplify(raw))
    except Exception as error:
        raise BenchmarkLoadError("benchmark manifest schema is invalid") from error
    tasks_root = manifest_path.parent / "tasks"
    if tasks_root.is_symlink() or not tasks_root.is_dir():
        raise BenchmarkLoadError("manifest task package root is missing")
    loaded_tasks: list[TaskSpec] = []
    for declared in manifest.tasks:
        package = tasks_root / declared.task_id
        if not package.exists():
            raise BenchmarkLoadError("manifest task package is missing")
        loaded = load_task(package)
        if loaded.model_dump(mode="python") != declared.model_dump(mode="python"):
            raise BenchmarkLoadError("manifest task package differs from manifest")
        loaded_tasks.append(loaded)
    if manifest.manifest_digest is not None:
        payload = dict(raw)
        payload.pop("manifest_digest", None)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        expected = "sha256:" + hashlib.sha256(encoded).hexdigest()
        if manifest.manifest_digest != expected:
            raise BenchmarkLoadError("benchmark manifest digest mismatch")
    # Preserve loader provenance for consumers while keeping the manifest's
    # public identity identical to the signed JSON payload.
    return manifest.model_copy(update={"tasks": tuple(loaded_tasks)})


__all__ = ["BenchmarkLoadError", "load_manifest", "load_task", "require_loaded_task"]
