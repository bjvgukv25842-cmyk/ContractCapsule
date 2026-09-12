import subprocess
from pathlib import Path

import pytest

from contractcapsule.swap.attempts import AttemptStore
from contractcapsule.swap.source import git_tree
from contractcapsule.swap.trees import RunnerError
from tests.integration.test_twin_run import config


def test_attempt_store_reserves_once_and_authenticates(tmp_path: Path):
    store = AttemptStore(tmp_path / "registry.db", key=b"k" * 32)
    first = store.reserve("op-1", "sha256:" + "a" * 64)
    assert first.state == "RUNNING"
    with pytest.raises(ValueError, match="already reserved"):
        store.reserve("op-1", first.binding_digest)
    store.complete("op-1", b"manifest")
    assert store.get("op-1").state == "COMPLETE"
    with pytest.raises(ValueError, match="binding mismatch"):
        store.reserve("op-1", "sha256:" + "b" * 64)


def test_git_tree_reads_locked_commit_not_dirty_worktree(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True)
    source = tmp_path / "src.py"
    source.write_text("committed")
    subprocess.run(["git", "-C", str(tmp_path), "add", "src.py"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "seed"], check=True)
    commit = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    source.write_text("dirty")
    tree = git_tree(tmp_path, "sha1:" + commit, config())
    assert dict(tree.files)["src.py"] == b"committed"


def test_git_tree_rejects_symlink_and_missing_commit(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with pytest.raises(RunnerError):
        git_tree(tmp_path, "sha1:" + "0" * 40, config())
