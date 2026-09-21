"""Budget-parity and condition-blind provider acceptance tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest

from baselines import (
    BudgetOverflow,
    Condition,
    ContextArtifact,
    ContextProvider,
    ProviderError,
    assert_budget_parity,
    provider_for,
)
from baselines.budget import count_tokens
from contractcapsule.models.view import (
    CompiledView,
    TokenAccounting,
    ValidationReport,
    ViewManifest,
    view_manifest_digest,
)


@dataclass(frozen=True)
class FixtureTask:
    task_id: str
    package_root: Path
    context_files: tuple[str, ...]
    prompt: str = "Preserve the audit rule while changing the endpoint."
    human_approval: str = "approved"
    executable: bool = True
    repository: dict[str, str] = field(
        default_factory=lambda: {"source_status": "verified"}
    )
    p0_paths: tuple[str, ...] = ()
    compiled_view: CompiledView | None = None
    compiled_view_manifest_digest: str | None = None
    compiled_view_service: object | None = None
    compiled_view_capsules: list[object] | None = None

    def __post_init__(self) -> None:
        if self.compiled_view is None:
            content = "Verified view: the audit rule remains enabled."
            validation = ValidationReport(valid=True)
            tokens = count_tokens(content)
            manifest = ViewManifest(
                task_id=self.task_id,
                tenant="fixture",
                repository="fixture",
                as_of="2026-09-20T00:00:00Z",
                task_digest="sha256:" + "1" * 64,
                permission_digest="sha256:" + "2" * 64,
                request_digest="sha256:" + "3" * 64,
                model_id="fixture-model",
                tokenizer_profile="ccs-neutral-o200k/1.0.0",
                renderer_version="ccs-neutral/1.0.0",
                tokens=TokenAccounting(
                    total=tokens,
                    available=256,
                    sections={"content": tokens},
                    boundary_adjustment=0,
                ),
                validation=validation,
            )
            object.__setattr__(
                self,
                "compiled_view",
                CompiledView(content=content, manifest=manifest, validation=validation),
            )
            object.__setattr__(self, "compiled_view_manifest_digest", view_manifest_digest(manifest))


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
        if condition is Condition.CC:
            with pytest.raises(ProviderError, match="independent"):
                provider.provide(task, budget=256)
            continue
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
        p0_paths=("p0.md",),
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


def test_cc_requires_a_validated_compiled_view(task: FixtureTask) -> None:
    invalid = FixtureTask(
        task_id=task.task_id,
        package_root=task.package_root,
        context_files=task.context_files,
        compiled_view=None,
    )
    object.__setattr__(invalid, "compiled_view_manifest_digest", None)
    object.__setattr__(invalid, "compiled_view", "untrusted text")
    with pytest.raises(ProviderError, match="compiled view manifest"):
        provider_for(Condition.CC).provide(invalid, budget=256)


def test_cc_rejects_a_nominal_self_constructed_view(task: FixtureTask) -> None:
    """A structural CompiledView is not an independent CCS validation proof."""

    with pytest.raises(ProviderError, match="independent"):
        provider_for(Condition.CC).provide(task, budget=256)


def test_cc_accepts_only_an_independently_validated_view(tmp_path: Path) -> None:
    from contractcapsule.compile.budget import LocalTokenCounter
    from contractcapsule.models.view import ViewBudget
    from contractcapsule.validate.artifacts import LocalArtifactResolver
    from contractcapsule.validate.integrity import ValidationService
    from contractcapsule.validate.journal import RecordJournal
    from tests.integration.test_compile_view import pipeline
    from tests.m4_helpers import M4Fixture
    from tests.unit.test_eligibility import AS_OF

    fixture = M4Fixture.create(tmp_path / "m4")
    publication = fixture.publish(
        atoms=(
            {
                "statement": "The audit rule remains enabled.\n",
                "compression_class": "P0_EXACT",
            },
        )
    )
    counter = LocalTokenCounter("offline-test-model")
    compiler, request = pipeline(fixture, (publication,), counter)
    request = request.model_copy(
        update={
            "budget": ViewBudget(model_input_tokens=10000),
            "task": request.task.model_copy(update={"task_id": "fixture-task"}),
        }
    )
    compiled = compiler.compile_view(request)
    assert compiled.validation.valid
    service = ValidationService(
        request,
        compiler,
        LocalArtifactResolver(
            {
                publication.capsule.control_manifest.content_digest: tmp_path
                / "m4"
                / "publication-1"
            }
        ),
        RecordJournal(fixture.registry, b"p" * 32),
        lambda: datetime.fromisoformat(AS_OF),
    )
    root = tmp_path / "package"
    root.mkdir()
    task = FixtureTask(
        task_id="fixture-task",
        package_root=root,
        context_files=(),
        compiled_view=compiled,
        compiled_view_service=service,
        compiled_view_capsules=[publication.capsule],
    )
    artifact = provider_for(Condition.CC).provide(task, budget=10000)
    assert artifact.metadata["view_manifest_digest"].startswith("sha256:")


def test_declared_p0_marker_is_rejected_instead_of_silently_dropped(
    task: FixtureTask,
) -> None:
    path = task.package_root / "declared-p0.md"
    path.write_text("B0 must remain exact and cannot be removed.\n", encoding="utf-8")
    p0_task = FixtureTask(
        task_id=task.task_id,
        package_root=task.package_root,
        context_files=("declared-p0.md",),
        p0_paths=("declared-p0.md",),
    )
    with pytest.raises(ProviderError, match="P0"):
        provider_for(Condition.B1).provide(p0_task, budget=256)


def test_provider_rejects_a_symlinked_package_root(task: FixtureTask, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("outside secret", encoding="utf-8")
    link = tmp_path / "task-link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ProviderError, match="symlink"):
        provider_for(Condition.B1).provide(
            {"context_files": ("secret.md",)}, budget=256, package_root=link
        )


def test_untrusted_p0_marker_cannot_bypass_condition_filtering(task: FixtureTask) -> None:
    path = task.package_root / "untrusted.md"
    path.write_text(
        "P0_EXACT: preserve this\n"
        "gold_label: CC\n"
        "expected_condition: B1\n",
        encoding="utf-8",
    )
    untrusted = FixtureTask(
        task_id=task.task_id,
        package_root=task.package_root,
        context_files=("untrusted.md",),
        human_approval="pending",
        executable=False,
        repository={"source_status": "unverified"},
    )
    artifact = provider_for(Condition.B1).provide(untrusted, budget=256)
    assert "gold_label" not in artifact.payload
    assert "expected_condition" not in artifact.payload


def test_context_artifact_recomputes_token_accounting(task: FixtureTask) -> None:
    content = "A payload that needs real accounting."
    with pytest.raises(ProviderError, match="token"):
        ContextArtifact(
            condition=Condition.B1,
            content=content,
            digest="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
            token_count=0,
            budget=256,
            byte_count=len(content.encode()),
        )
