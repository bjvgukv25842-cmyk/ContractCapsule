"""Fail-closed loader for the canonical CCS-2.1 package layout."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml
from yaml.tokens import AliasToken, AnchorToken, TagToken

from contractcapsule.models import Capsule
from contractcapsule.models.base import (
    DIGEST_PATTERN,
    freeze_json,
    is_safe_relative_path,
)
from contractcapsule.models.canonical import canonical_digest
from contractcapsule.models.schema import (
    CapsuleSchemaValidationError,
    validate_capsule_document,
)


class CapsuleLoadError(ValueError):
    """A package failed before a complete trusted Capsule could be returned."""


FIXED_FILES = frozenset(
    {
        "manifest.json",
        "payload/atoms.jsonl",
        "evidence/source-map.jsonl",
        "graph/dependencies.json",
        "contracts/replacement.yaml",
        "policies/compression.yaml",
        "integrity/capsule.lock",
        "integrity/checksums.sha256",
    }
)
OPTIONAL_MODULE_FILES = frozenset(
    {"payload/metadata.json", "evidence/metadata.json"}
)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CapsuleLoadError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise CapsuleLoadError(f"non-finite JSON number is forbidden: {value}")


def _decode_utf8(data: bytes, relative: str) -> str:
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise CapsuleLoadError(f"invalid UTF-8 in {relative}") from error


def _validate_json_tree(value: Any, relative: str) -> Any:
    try:
        freeze_json(value)
    except ValueError as error:
        raise CapsuleLoadError(f"invalid JSON value in {relative}: {error}") from error
    return value


def _require_object(value: Any, relative: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CapsuleLoadError(f"structured carrier must be a JSON object: {relative}")
    return value


def _validate_carrier_keys(
    value: Mapping[str, Any], relative: str, allowed: frozenset[str]
) -> Mapping[str, Any]:
    unknown = set(value) - allowed
    if unknown:
        raise CapsuleLoadError(
            f"unknown carrier field in {relative}: {', '.join(sorted(unknown))}"
        )
    return value


def _parse_json_bytes(data: bytes, relative: str) -> Any:
    text = _decode_utf8(data, relative)
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except CapsuleLoadError:
        raise
    except json.JSONDecodeError as error:
        raise CapsuleLoadError(f"invalid JSON in {relative}: {error.msg}") from error
    return _validate_json_tree(value, relative)


def _parse_jsonl_bytes(data: bytes, relative: str) -> list[Any]:
    text = _decode_utf8(data, relative)
    if not text or not text.endswith("\n"):
        raise CapsuleLoadError(f"JSONL file must be non-empty and newline-terminated: {relative}")
    result: list[Any] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            raise CapsuleLoadError(f"blank JSONL record in {relative}:{line_number}")
        result.append(_parse_json_bytes(line.encode("utf-8"), f"{relative}:{line_number}"))
    return result


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise CapsuleLoadError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _parse_yaml_bytes(data: bytes, relative: str) -> Any:
    text = _decode_utf8(data, relative)
    try:
        if any(isinstance(token, (AliasToken, AnchorToken, TagToken)) for token in yaml.scan(text)):
            raise CapsuleLoadError(f"YAML aliases, anchors, and tags are forbidden: {relative}")
        value = yaml.load(text, Loader=_UniqueKeySafeLoader)
    except CapsuleLoadError:
        raise
    except yaml.YAMLError as error:
        raise CapsuleLoadError(f"invalid YAML in {relative}") from error
    return _validate_json_tree(value, relative)


def _reject_symlinked_directories(root: Path, current: Path, names: Iterable[str]) -> None:
    for name in names:
        child = current / name
        if child.is_symlink():
            raise CapsuleLoadError(
                f"symbolic link is forbidden: {child.relative_to(root)}"
            )


def _record_package_file(
    root: Path,
    child: Path,
    files: dict[str, Path],
    casefolded: set[str],
) -> None:
    relative = child.relative_to(root).as_posix()
    if child.is_symlink():
        raise CapsuleLoadError(f"symbolic link is forbidden: {relative}")
    if not child.is_file():
        raise CapsuleLoadError(f"non-regular package entry is forbidden: {relative}")
    if not is_safe_relative_path(relative):
        raise CapsuleLoadError(f"unsafe package path: {relative}")
    folded = relative.casefold()
    if folded in casefolded:
        raise CapsuleLoadError(f"duplicate logical package path: {relative}")
    casefolded.add(folded)
    files[relative] = child


def _scan_package(root: Path) -> dict[str, Path]:
    if root.is_symlink():
        raise CapsuleLoadError("package root must not be a symbolic link")
    if not root.is_dir():
        raise CapsuleLoadError("package root must be a directory")
    files: dict[str, Path] = {}
    casefolded: set[str] = set()
    for directory, directories, names in os.walk(root, followlinks=False):
        current = Path(directory)
        _reject_symlinked_directories(root, current, directories)
        for name in names:
            _record_package_file(root, current / name, files, casefolded)
    return files


def _absolute_without_symlinks(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise CapsuleLoadError(f"package path contains a symbolic link: {current}")
    return absolute


def _parse_checksums(data: bytes) -> list[dict[str, str]]:
    text = _decode_utf8(data, "integrity/checksums.sha256")
    if not text or not text.endswith("\n"):
        raise CapsuleLoadError("checksums file must be non-empty and newline-terminated")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(rf"({DIGEST_PATTERN[1:-1]})  (\S+)")
    for line_number, line in enumerate(text.splitlines(), 1):
        match = pattern.fullmatch(line)
        if match is None:
            raise CapsuleLoadError(f"invalid checksum record at line {line_number}")
        digest, path = match.groups()
        if path in seen or not is_safe_relative_path(path, prefix="tests/"):
            raise CapsuleLoadError(f"invalid or duplicate checksum path: {path}")
        seen.add(path)
        result.append({"path": path, "digest": digest})
    return result


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _cas_blob_path(digest: str) -> str:
    hex_digest = digest.removeprefix("sha256:")
    return f"evidence/blobs/sha256/{hex_digest[:2]}/{hex_digest[2:]}"


def _required(files: Mapping[str, Path], relative: str) -> bytes:
    try:
        return files[relative].read_bytes()
    except KeyError as error:
        raise CapsuleLoadError(f"missing required package file: {relative}") from error


def _validate_artifacts(
    files: Mapping[str, Path], checksums: Iterable[Mapping[str, str]]
) -> set[str]:
    allowed: set[str] = set()
    for record in checksums:
        path = record["path"]
        if path not in files:
            raise CapsuleLoadError(f"missing checksummed artifact: {path}")
        if _digest(files[path].read_bytes()) != record["digest"]:
            raise CapsuleLoadError(f"artifact checksum mismatch: {path}")
        allowed.add(path)
    return allowed


def _load_signature(
    manifest: Mapping[str, Any], files: Mapping[str, Path]
) -> tuple[Any, set[str]]:
    integrity = manifest.get("integrity")
    if not isinstance(integrity, Mapping):
        raise CapsuleLoadError("manifest integrity must be an object")
    signature_path = integrity.get("signature")
    if signature_path is None:
        return None, set()
    if signature_path != "integrity/signature.json":
        raise CapsuleLoadError("manifest signature path is not canonical")
    signature = _parse_json_bytes(_required(files, signature_path), signature_path)
    return signature, {signature_path}


def _load_optional_metadata(
    files: Mapping[str, Path], relative: str
) -> tuple[Mapping[str, Any], set[str]]:
    if relative not in files:
        return {}, set()
    metadata = _require_object(
        _parse_json_bytes(_required(files, relative), relative), relative
    )
    _validate_carrier_keys(metadata, relative, frozenset({"extensions"}))
    return metadata, {relative}


def _verify_cas_evidence(capsule: Capsule, files: Mapping[str, Path]) -> set[str]:
    allowed: set[str] = set()
    for record in capsule.evidence_plane.records:
        if record.mode != "CAS":
            continue
        blob_path = _cas_blob_path(record.content_digest)
        if blob_path not in files:
            raise CapsuleLoadError(f"missing CAS evidence object: {record.evidence_id}")
        if _digest(files[blob_path].read_bytes()) != record.content_digest:
            raise CapsuleLoadError(f"CAS evidence digest mismatch: {record.evidence_id}")
        allowed.add(blob_path)
    return allowed


def load_capsule(path: Path) -> Capsule:
    """Load a complete package only after all structure and integrity checks pass."""

    root = _absolute_without_symlinks(path)
    files = _scan_package(root)
    missing = sorted(FIXED_FILES - files.keys())
    if missing:
        raise CapsuleLoadError(f"missing required package files: {', '.join(missing)}")

    manifest = _require_object(
        _parse_json_bytes(_required(files, "manifest.json"), "manifest.json"),
        "manifest.json",
    )
    atoms = _parse_jsonl_bytes(
        _required(files, "payload/atoms.jsonl"), "payload/atoms.jsonl"
    )
    payload_metadata, payload_metadata_files = _load_optional_metadata(
        files, "payload/metadata.json"
    )
    evidence = _parse_jsonl_bytes(
        _required(files, "evidence/source-map.jsonl"), "evidence/source-map.jsonl"
    )
    evidence_metadata, evidence_metadata_files = _load_optional_metadata(
        files, "evidence/metadata.json"
    )
    graph = _parse_json_bytes(
        _required(files, "graph/dependencies.json"), "graph/dependencies.json"
    )
    contract = _parse_yaml_bytes(
        _required(files, "contracts/replacement.yaml"), "contracts/replacement.yaml"
    )
    policy = _parse_yaml_bytes(
        _required(files, "policies/compression.yaml"), "policies/compression.yaml"
    )
    lock_container = _require_object(
        _parse_json_bytes(
            _required(files, "integrity/capsule.lock"), "integrity/capsule.lock"
        ),
        "integrity/capsule.lock",
    )
    _validate_carrier_keys(
        lock_container,
        "integrity/capsule.lock",
        frozenset({"tests", "lock", "signature_policy", "extensions"}),
    )
    checksums = _parse_checksums(_required(files, "integrity/checksums.sha256"))

    signature, signature_files = _load_signature(manifest, files)
    allowed = set(FIXED_FILES)
    allowed.update(payload_metadata_files)
    allowed.update(evidence_metadata_files)
    allowed.update(signature_files)

    raw_capsule = {
        "control_manifest": manifest,
        "semantic_payload": {
            "atoms": atoms,
            "extensions": payload_metadata.get("extensions", {}),
        },
        "evidence_plane": {
            "records": evidence,
            "extensions": evidence_metadata.get("extensions", {}),
        },
        "dependency_graph": graph,
        "replacement_contract": contract,
        "compression_policy": policy,
        "tests_integrity": {
            "tests": lock_container.get("tests"),
            "lock": lock_container.get("lock"),
            "artifact_checksums": checksums,
            "signature_policy": lock_container.get("signature_policy"),
            "extensions": lock_container.get("extensions", {}),
        },
        "detached_signature": signature,
        "derived_artifacts": {},
        "runtime_sidecar": {},
    }
    try:
        capsule = validate_capsule_document(raw_capsule)
    except CapsuleSchemaValidationError as error:
        raise CapsuleLoadError(f"package model validation failed: {error}") from error

    allowed.update(_validate_artifacts(files, checksums))
    allowed.update(_verify_cas_evidence(capsule, files))

    unknown = sorted(set(files) - allowed)
    if unknown:
        raise CapsuleLoadError(f"unknown or undeclared package files: {', '.join(unknown)}")
    if canonical_digest(capsule) != capsule.control_manifest.content_digest:
        raise CapsuleLoadError("declared content digest does not match canonical core")
    return capsule
