from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from experiments.models import PreflightReceipt
from experiments.pilot import (
    PilotConfig,
    PilotGateError,
    PilotGateReport,
    build_pilot_schedule,
    main,
    validate_pilot_inputs,
)
from experiments.preflight import binary_digest

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


def test_checked_in_config_refuses_and_writes_only_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    report_path = tmp_path / "readiness.json"
    monkeypatch.chdir(tmp_path)

    result = main(
        [
            "--config",
            str(repo_root / "experiments/configs/m8-pilot.yaml"),
            "--manifest",
            str(repo_root / "benchmark/benchmark-manifest.json"),
            "--protocol",
            str(repo_root / "research/protocol.md"),
            "--report",
            str(report_path),
        ]
    )

    assert result == 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ready"] is False
    assert "benchmark_not_frozen" in report["blockers"]
    assert not (tmp_path / "results/pilot/runs.jsonl").exists()


def test_readiness_report_cannot_be_overwritten(tmp_path: Path) -> None:
    from experiments.pilot import _write_report

    report_path = tmp_path / "readiness.json"
    report_path.write_text("original\n", encoding="utf-8")
    report = PilotGateReport(
        ready=False,
        task_ids=TASK_IDS,
        scheduled_runs=48,
        config_digest="sha256:" + "0" * 64,
    )

    with pytest.raises(PilotGateError, match="cannot be overwritten"):
        _write_report(report_path, report)
    assert report_path.read_text(encoding="utf-8") == "original\n"


def test_invalid_preflight_receipt_is_a_blocker(tmp_path: Path) -> None:
    receipt_path = tmp_path / "preflight.json"
    receipt_path.write_text("{}\n", encoding="utf-8")
    config = _config(
        preflight_receipt=receipt_path,
        model="codex-frozen",
        version="1.2.3",
        binary="/usr/bin/codex",
    )

    report = validate_pilot_inputs(
        config,
        manifest_path=Path("benchmark/benchmark-manifest.json"),
        protocol_path=Path("research/protocol.md"),
    )

    assert "preflight_receipt_invalid" in report.blockers


def _signed_receipt(path: Path, key: bytes) -> None:
    binary = sys.executable
    receipt = PreflightReceipt(
        config_digest="sha256:" + "a" * 64,
        agent="codex",
        version="codex-test",
        model="codex-model",
        binary=binary,
        binary_digest=binary_digest(binary),
        capabilities=("test",),
        available=True,
    )
    receipt = receipt.model_copy(
        update={
            "digest": receipt.computed_digest(),
            "signature": receipt.computed_signature(key),
        }
    )
    path.write_text(
        json.dumps(receipt.model_dump(mode="json")) + "\n", encoding="utf-8"
    )


def test_preflight_signature_must_be_verified(tmp_path: Path) -> None:
    key = b"k" * 32
    receipt_path = tmp_path / "preflight.json"
    _signed_receipt(receipt_path, key)
    config = _config(
        preflight_receipt=receipt_path,
        model="codex-model",
        version="codex-test",
        binary=sys.executable,
    )

    without_key = validate_pilot_inputs(
        config,
        manifest_path=Path("benchmark/benchmark-manifest.json"),
        protocol_path=Path("research/protocol.md"),
    )
    assert "preflight_signature_unverified" in without_key.blockers

    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["signature"] = "sha256:" + "0" * 64
    receipt_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    forged = validate_pilot_inputs(
        config,
        manifest_path=Path("benchmark/benchmark-manifest.json"),
        protocol_path=Path("research/protocol.md"),
        preflight_signing_key=key,
    )
    assert "preflight_signature_invalid" in forged.blockers


def test_dangling_pilot_output_symlink_is_a_blocker(tmp_path: Path) -> None:
    output_path = tmp_path / "runs.jsonl"
    output_path.symlink_to(tmp_path / "missing-runs.jsonl")
    config = _config(output_path=output_path)

    report = validate_pilot_inputs(
        config,
        manifest_path=Path("benchmark/benchmark-manifest.json"),
        protocol_path=Path("research/protocol.md"),
    )

    assert "pilot_output_exists" in report.blockers


def test_existing_raw_pilot_output_is_a_blocker(tmp_path: Path) -> None:
    raw_output_dir = tmp_path / "raw"
    raw_output_dir.mkdir()
    config = _config(raw_output_dir=raw_output_dir)

    report = validate_pilot_inputs(
        config,
        manifest_path=Path("benchmark/benchmark-manifest.json"),
        protocol_path=Path("research/protocol.md"),
    )

    assert "pilot_raw_output_exists" in report.blockers


def test_invalid_adjudication_jsonl_is_a_blocker(tmp_path: Path) -> None:
    manifest_path = tmp_path / "benchmark-manifest.json"
    adjudication_path = tmp_path / "adjudication.jsonl"
    adjudication_path.write_text("{}\nnot-json\n", encoding="utf-8")
    config = _config()

    report = validate_pilot_inputs(
        config,
        manifest_path=manifest_path,
        protocol_path=Path("research/protocol.md"),
    )

    assert "adjudication_invalid" in report.blockers
