from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "research" / "source-repository-lock.json"
MANIFEST_PATH = ROOT / "benchmark" / "benchmark-manifest.json"
CANONICAL_REPOSITORY = "https://github.com/bjvgukv25842-cmyk/ContractCapsule.git"


def _git(*args: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(ROOT), *args),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _normalized_repository(value: str) -> str:
    return value.removesuffix("/").removesuffix(".git")


def test_source_repository_lock_matches_local_history() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    baseline = lock["baseline"]

    assert lock["schema_version"] == "1"
    assert lock["project"] == "ContractCapsule"
    assert lock["canonical_repository"] == CANONICAL_REPOSITORY
    assert lock["remote_name"] == "origin"
    assert lock["default_branch"] == "main"
    assert re.fullmatch(r"[0-9a-f]{40}", baseline["commit"])
    assert re.fullmatch(r"[0-9a-f]{40}", baseline["tree"])
    assert re.fullmatch(r"[0-9a-f]{40}", baseline["tag_object"])
    assert _git("cat-file", "-t", baseline["commit"]) == "commit"
    assert _git("show", "-s", "--format=%T", baseline["commit"]) == baseline["tree"]
    assert _git("rev-parse", baseline["tag"]) == baseline["tag_object"]
    assert _git("rev-parse", f"{baseline['tag']}^{{commit}}") == baseline["commit"]
    subprocess.run(
        (
            "git",
            "-C",
            str(ROOT),
            "merge-base",
            "--is-ancestor",
            baseline["commit"],
            "HEAD",
        ),
        check=True,
    )
    assert _normalized_repository(_git("remote", "get-url", "origin")) == (
        _normalized_repository(CANONICAL_REPOSITORY)
    )
    assert {
        lock["publication"]["main_commit_at_publication"],
        lock["publication"]["work_branch_commit_at_publication"],
        lock["publication"]["tag_commit"],
    } == {baseline["commit"]}


def test_project_repository_is_not_a_benchmark_task_source() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    project_repository = _normalized_repository(lock["canonical_repository"])
    task_repositories = {
        _normalized_repository(task["repository"]["source_url"])
        for task in manifest["tasks"]
    }

    assert project_repository not in task_repositories
