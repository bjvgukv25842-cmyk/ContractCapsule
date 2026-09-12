"""Validate immutable bytes before writing fresh controller-owned mount trees."""

from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from contractcapsule.models.base import is_safe_relative_path
from contractcapsule.swap.trees import FrozenTree, RunnerError, validate_tree
from contractcapsule.validate.models import Artifact, Invocation, RunnerConfig
from contractcapsule.validate.run_models import Snapshot, TreeEntry, digest_bytes

TREE_INPUTS = frozenset({"initial", "current", "old_final", "new_final"})
BYTE_INPUTS = frozenset({"task", "view", "observations"})
INPUT_BYTES_LIMIT = 16 * 1024 * 1024


def verified_artifacts(
    invocation: Invocation, artifacts: tuple[Artifact, ...]
) -> tuple[Artifact, ...]:
    if not isinstance(invocation, Invocation) or type(artifacts) is not tuple:
        raise RunnerError("invalid invocation/artifact transport")
    if any(type(a) is not Artifact for a in artifacts):
        raise RunnerError("invalid artifact transport")
    Invocation.model_validate(
        {name: getattr(invocation, name) for name in Invocation.model_fields}
    )
    parsed = tuple(Artifact.model_validate(a.model_dump()) for a in artifacts)
    by_id = {a.test_id: a for a in parsed}
    if len(by_id) != len(parsed) or len({a.path for a in parsed}) != len(parsed):
        raise RunnerError("duplicate artifact identity/path")
    for artifact in parsed:
        if (
            not is_safe_relative_path(artifact.path)
            or any(c in artifact.path for c in "*?[]")
            or digest_bytes(artifact.data) != artifact.digest
        ):
            raise RunnerError("unsafe artifact path or changed bytes")
    if any(a not in by_id for a in invocation.artifact_ids):
        raise RunnerError("artifact subset incomplete")
    selected = tuple(by_id[name] for name in invocation.artifact_ids)
    if PurePosixPath(by_id[invocation.test_id].path).suffix != ".py":
        raise RunnerError("entry must be a Python artifact")
    return selected


def prepare_stage(
    root: Path,
    invocation: Invocation,
    artifacts: tuple[Artifact, ...],
    inputs: Mapping[str, FrozenTree | bytes],
    workspace: FrozenTree | None,
    config: RunnerConfig,
) -> str:
    selected = verified_artifacts(invocation, artifacts)
    if set(inputs) - TREE_INPUTS - BYTE_INPUTS:
        raise RunnerError("unsupported stage input")
    root.chmod(0o755)
    program_root = root / "runner"
    program_root.mkdir(mode=0o755)
    for artifact in selected:
        path = program_root / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(artifact.data)
        path.chmod(0o444)
    input_root = root / "inputs"
    input_root.mkdir(mode=0o755)
    for name, value in inputs.items():
        _write_input(input_root, name, value, config)
    seed = workspace or FrozenTree(
        Snapshot(entries=(TreeEntry(path=".", kind="directory", mode=0o755),)), ()
    )
    validate_tree(seed, config)
    seed.materialize(root / "seed")
    return next(a.path for a in selected if a.test_id == invocation.test_id)


def _write_input(
    root: Path, name: str, value: FrozenTree | bytes, config: RunnerConfig
) -> None:
    if name in TREE_INPUTS and type(value) is FrozenTree:
        validate_tree(value, config)
        value.materialize(root / name)
    elif (
        name in BYTE_INPUTS and type(value) is bytes and len(value) <= INPUT_BYTES_LIMIT
    ):
        path = root / (name + ".json")
        path.write_bytes(value)
        path.chmod(0o444)
    else:
        raise RunnerError("stage input type or size invalid")
