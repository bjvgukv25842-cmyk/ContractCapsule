"""Budget-parity and condition-blind provider acceptance tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from baselines import (
    BudgetOverflow,
    Condition,
    ContextArtifact,
    ContextProvider,
    assert_budget_parity,
    provider_for,
)


@dataclass(frozen=True)
class FixtureTask:
    task_id: str
    package_root: Path
    context_files: tuple[str, ...]
    prompt: str = "Preserve the audit rule while changing the endpoint."


@pytest.fixture
def task(tmp_path: Path) -> FixtureTask:
    root = tmp_path / "task"
    (root / "capsules" / "old" / "payload").mkdir(parents=True)
    (root / "capsules" / "new" / "payload").mkdir(parents=True)
    (root / "gold").mkdir()
    (root / "tests").mkdir()
    (root / "context.md").write_text(
        "The audit rule must remain enabled.\n"
        "The endpoint changes from /v1 to /v2.\n",
        encoding="utf-8",
    )
    atom = {
        "atom_id": "endpoint-change",
        "statement": "The endpoint changes from /v1 to /v2.",
        "compression_class": "P1_STRUCTURED",
    }
    for revision in ("old", "new"):
        (root / "capsules" / revision / "payload" / "atoms.jsonl").write_text(
            json.dumps(atom) + "\n", encoding="utf-8"
        )
    # This must never reach a runtime context artifact.
    (root / "gold" / "required-atoms.json").write_text(
        '{"gold_label": "CC", "expected_condition": "B1"}\n', encoding="utf-8"
    )
    (root / "tests" / "target.txt").write_text(
        "condition B2 should pass only for the gold task\n", encoding="utf-8"
    )
    return FixtureTask(
        task_id="fixture-task",
        package_root=root,
        context_files=(
            "context.md",
            "capsules/old/payload/atoms.jsonl",
            "capsules/new/payload/atoms.jsonl",
            "gold/required-atoms.json",
            "tests/target.txt",
        ),
    )


def test_all_conditions_share_provider_interface_and_are_condition_blind(
    task: FixtureTask,
) -> None:
    artifacts: list[ContextArtifact] = []
    for condition in Condition:
        provider = provider_for(condition)
        assert isinstance(provider, ContextProvider)
        artifact = provider.provide(task, budget=256)
        artifacts.append(artifact)
        assert artifact.condition is condition
        assert artifact.token_count <= 256
        assert "gold_label" not in artifact.payload
        assert "expected_condition" not in artifact.payload
        assert not any(
            f"{candidate.value}" in artifact.payload
            for candidate in Condition
        )
    assert_budget_parity(artifacts, 256)


def test_budget_parity_rejects_mismatched_artifact_budget(task: FixtureTask) -> None:
    first = provider_for(Condition.B1).provide(task, budget=256)
    second = provider_for(Condition.B2).provide(task, budget=128)
    with pytest.raises(ValueError, match="budget"):
        assert_budget_parity((first, second), 256)


def test_p0_overflow_fails_closed(task: FixtureTask, tmp_path: Path) -> None:
    p0 = tmp_path / "p0.md"
    p0.write_text("P0_EXACT: " + ("must-preserve " * 100), encoding="utf-8")
    constrained = FixtureTask(
        task_id=task.task_id,
        package_root=task.package_root,
        context_files=("p0.md",),
    )
    # Keep the fixture outside the package's declared root to ensure the
    # provider does not accidentally read arbitrary paths.
    (task.package_root / "p0.md").write_text(p0.read_text(), encoding="utf-8")
    with pytest.raises(BudgetOverflow):
        provider_for(Condition.B1).provide(constrained, budget=8)


def test_provider_rejects_path_escape(task: FixtureTask) -> None:
    escaped = FixtureTask(
        task_id=task.task_id,
        package_root=task.package_root,
        context_files=("../outside.txt",),
    )
    with pytest.raises(ValueError, match="path"):
        provider_for(Condition.B1).provide(escaped, budget=256)
