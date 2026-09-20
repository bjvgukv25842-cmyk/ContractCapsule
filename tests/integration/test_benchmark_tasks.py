from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.loader import BenchmarkLoadError, load_manifest, load_task
from benchmark.schema import ApprovalStatus, CheckSpec, TaskSpec

ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "benchmark" / "benchmark-manifest.json"


def test_m7_manifest_has_24_unique_screened_tasks_and_no_approval_claim() -> None:
    manifest = load_manifest(MANIFEST)

    assert len(manifest.tasks) == 24
    assert len({task.task_id for task in manifest.tasks}) == 24
    assert all(task.human_approval is ApprovalStatus.PENDING for task in manifest.tasks)
    assert all(not task.executable for task in manifest.tasks)
    assert manifest.status == "screening"


def test_task_loader_rejects_unsafe_check_paths(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "task.yaml").write_text(
        """
task_id: test-unsafe
category: policy
language: python
repository:
  source_url: https://github.com/example/project
  commit: null
  license: pending-verification
  source_status: unverified
human_approval: pending
executable: false
max_runtime_seconds: 900
checks:
  target:
    - check_id: target
      command: [pytest, ../outside.py]
      cwd: .
""",
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkLoadError, match="relative"):
        load_task(task_dir)


def test_task_loader_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "task.yaml").write_text(
        "task_id: duplicate\ntask_id: overwritten\ncategory: policy\n"
        "language: python\nrepository: {source_url: https://github.com/x/y, commit: null, license: pending-verification, source_status: unverified}\n"
        "human_approval: pending\nexecutable: false\nmax_runtime_seconds: 900\n",
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkLoadError, match="duplicate"):
        load_task(task_dir)


def test_task_loader_rejects_manifest_digest_mismatch(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    task_yaml = task_dir / "task.yaml"
    task_yaml.write_text(
        "task_id: digest-check\ncategory: policy\nlanguage: python\n"
        "repository: {source_url: https://github.com/x/y, commit: null, license: pending-verification, source_status: unverified, content_digest: sha256:1111111111111111111111111111111111111111111111111111111111111111}\n"
        "human_approval: pending\nexecutable: false\nmax_runtime_seconds: 900\n",
        encoding="utf-8",
    )
    (task_dir / "repository.lock").write_text(
        json.dumps({"content_digest": "sha256:" + "0" * 64}), encoding="utf-8"
    )

    with pytest.raises(BenchmarkLoadError, match="digest"):
        load_task(task_dir)


def test_manifest_loader_rejects_duplicate_json_keys_and_missing_packages(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"spec_version":"CCS-2.1","spec_version":"CCS-2.1",'
        '"max_view_tokens":128,"tasks":[]}',
        encoding="utf-8",
    )
    with pytest.raises(BenchmarkLoadError, match="duplicate"):
        load_manifest(duplicate)

    missing = tmp_path / "missing.json"
    missing.write_text(
        '{"spec_version":"CCS-2.1","max_view_tokens":128,'
        '"tasks":[{"task_id":"candidate-001","category":"policy",'
        '"language":"python","repository":{"source_url":"https://github.com/x/y",'
        '"commit":null,"license":"pending-verification",'
        '"source_status":"unverified"},"human_approval":"pending",'
        '"executable":false,"max_runtime_seconds":10,"checks":{}}]}',
        encoding="utf-8",
    )
    with pytest.raises(BenchmarkLoadError, match="task package"):
        load_manifest(missing)


def test_repository_lock_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "task.yaml").write_text(
        "task_id: lock-duplicate\ncategory: policy\nlanguage: python\n"
        "repository: {source_url: https://github.com/x/y, commit: null, license: pending-verification, source_status: unverified}\n"
        "human_approval: pending\nexecutable: false\nmax_runtime_seconds: 10\n",
        encoding="utf-8",
    )
    (task_dir / "repository.lock").write_text(
        '{"content_digest":"sha256:' + "0" * 64 + '","content_digest":"sha256:' + "0" * 64 + '"}',
        encoding="utf-8",
    )
    with pytest.raises(BenchmarkLoadError, match="duplicate"):
        load_task(task_dir)


def test_task_loader_rejects_symlinked_task_yaml(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("task_id: outside\n", encoding="utf-8")
    (task_dir / "task.yaml").symlink_to(outside)
    with pytest.raises(BenchmarkLoadError, match="symlink"):
        load_task(task_dir)


def test_check_spec_is_condition_blind_and_shell_free() -> None:
    check = CheckSpec(check_id="target", command=("pytest", "tests/test_target.py"))
    assert check.shell is False
    assert "CC" not in check.command


def test_task_model_requires_nonempty_check_ids() -> None:
    with pytest.raises(ValueError):
        TaskSpec(
            task_id="task",
            category="policy",
            language="python",
            repository={
                "source_url": "https://github.com/x/y",
                "commit": None,
                "license": "pending-verification",
                "source_status": "unverified",
            },
            human_approval="pending",
            executable=False,
            max_runtime_seconds=900,
            checks={"target": [{"check_id": "", "command": ["pytest"]}]},
        )


def test_frozen_manifest_cannot_contain_pending_candidates() -> None:
    with pytest.raises(ValueError, match="24 tasks"):
        from benchmark.schema import BenchmarkManifest

        BenchmarkManifest(
            status="frozen",
            max_view_tokens=128,
            tasks=(
                TaskSpec(
                    task_id="candidate-001",
                    category="policy",
                    language="python",
                    repository={
                        "source_url": "https://github.com/x/y",
                        "commit": None,
                        "license": "pending-verification",
                        "source_status": "unverified",
                    },
                    human_approval="pending",
                    executable=False,
                    max_runtime_seconds=10,
                ),
            ),
            manifest_digest="sha256:" + "0" * 64,
        )
