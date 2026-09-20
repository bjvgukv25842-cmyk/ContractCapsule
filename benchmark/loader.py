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


def load_task(task_dir: Path) -> TaskSpec:
    """Load one task package without following paths outside its root."""

    root = Path(task_dir)
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
    return task


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
    for declared in manifest.tasks:
        package = tasks_root / declared.task_id
        if not package.exists():
            raise BenchmarkLoadError("manifest task package is missing")
        loaded = load_task(package)
        if loaded != declared:
            raise BenchmarkLoadError("manifest task package differs from manifest")
    if manifest.manifest_digest is not None:
        payload = dict(raw)
        payload.pop("manifest_digest", None)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        expected = "sha256:" + hashlib.sha256(encoded).hexdigest()
        if manifest.manifest_digest != expected:
            raise BenchmarkLoadError("benchmark manifest digest mismatch")
    return manifest
