from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from experiments.pilot import (
    PilotConfig,
    build_pilot_schedule,
    validate_pilot_inputs,
)

TASK_IDS = tuple(f"candidate-{index:03d}" for index in range(1, 7))
STRATA = {task_id: f"stratum-{index}" for index, task_id in enumerate(TASK_IDS, 1)}


def _config(**overrides: object) -> PilotConfig:
    values: dict[str, object] = {
        "study_id": "m8-pilot-test",
        "agent": "codex",
        "task_ids": TASK_IDS,
        "task_strata": STRATA,
        "conditions": ("B0", "B2", "B4", "CC"),
        "repetitions": 2,
        "runtime_budget_tokens": 2048,
        "timeout_seconds": 900.0,
        "model": "codex-test",
        "version": "1.2.3",
        "binary": "/usr/bin/codex",
        "expected_manifest_digest": "sha256:" + "1" * 64,
        "expected_protocol_digest": "sha256:" + "2" * 64,
    }
    values.update(overrides)
    return PilotConfig.model_validate(values)


def test_pilot_config_rejects_duplicate_task_ids() -> None:
    with pytest.raises(ValidationError, match="task_ids"):
        _config(task_ids=(TASK_IDS[0], TASK_IDS[0], *TASK_IDS[2:]))


def test_pilot_config_requires_six_explicit_strata() -> None:
    with pytest.raises(ValidationError, match="task_strata"):
        _config(task_strata={TASK_IDS[0]: "only-one"})


@pytest.mark.parametrize(
    ("field", "value"),
    [("conditions", ("B0", "B1", "B2", "CC")), ("repetitions", 1)],
)
def test_pilot_config_requires_exact_scope(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        _config(**{field: value})


def test_screening_manifest_is_refused_before_any_run(tmp_path: Path) -> None:
    config = _config(
        expected_manifest_digest=None,
        expected_protocol_digest=None,
    )
    report = validate_pilot_inputs(
        config,
        manifest_path=Path("benchmark/benchmark-manifest.json"),
        protocol_path=Path("research/protocol.md"),
    )
    assert report.ready is False
    assert report.scheduled_runs == 48
    assert "benchmark_not_frozen" in report.blockers
    assert "task_not_approved" in report.blockers
    assert "manifest_digest_missing" in report.blockers
    assert not list(tmp_path.iterdir())


def test_protocol_and_manifest_digest_mismatches_are_blockers() -> None:
    config = _config(
        expected_manifest_digest="sha256:" + "f" * 64,
        expected_protocol_digest="sha256:" + "e" * 64,
    )
    report = validate_pilot_inputs(
        config,
        manifest_path=Path("benchmark/benchmark-manifest.json"),
        protocol_path=Path("research/protocol.md"),
    )
    assert report.ready is False
    assert "manifest_digest_mismatch" in report.blockers
    assert "protocol_digest_mismatch" in report.blockers


def test_schedule_is_deterministic_and_has_48_cells() -> None:
    config = _config()
    first = build_pilot_schedule(config)
    second = build_pilot_schedule(config)
    assert first == second
    assert len(first) == 48
    assert first[0].task_id == "candidate-001"
    assert first[0].condition == "B0"
    assert first[0].repetition == 0
    assert first[-1].task_id == "candidate-006"
    assert first[-1].condition == "CC"
    assert first[-1].repetition == 1
