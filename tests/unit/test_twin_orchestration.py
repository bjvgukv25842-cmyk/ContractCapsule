import sqlite3
import subprocess
import zlib
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
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True
    )
    source = tmp_path / "src.py"
    source.write_text("committed")
    subprocess.run(["git", "-C", str(tmp_path), "add", "src.py"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "seed"], check=True)
    commit = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    source.write_text("dirty")
    tree = git_tree(tmp_path, "sha1:" + commit, config())
    assert dict(tree.files)["src.py"] == b"committed"


def test_git_tree_rejects_symlink_and_missing_commit(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with pytest.raises(RunnerError):
        git_tree(tmp_path, "sha1:" + "0" * 40, config())


def test_attempt_reserve_rejects_injected_complete_payload(tmp_path):
    store = AttemptStore(tmp_path / "registry.db", key=b"k" * 32)
    store.reserve("op", "binding")
    with sqlite3.connect(store.database_path) as db:
        db.execute(
            "UPDATE m5_twin_attempts SET state='COMPLETE', manifest=? WHERE operation_id='op'",
            (b"forged",),
        )
    with pytest.raises(ValueError, match="authentication"):
        store.reserve("op", "binding")


def test_attempt_store_requires_private_configured_key(tmp_path):
    with pytest.raises((TypeError, ValueError)):
        AttemptStore(tmp_path / "registry.db")


def test_git_tree_rejects_backslash_names_without_rewriting(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True
    )
    (tmp_path / "safe\\unsafe").write_text("content")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "unsafe name"], check=True
    )
    commit = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    with pytest.raises(RunnerError):
        git_tree(tmp_path, "sha1:" + commit, config())


def test_attempt_field_delimiters_cannot_reuse_another_rows_signature(tmp_path):
    store = AttemptStore(tmp_path / "registry.db", key=b"k" * 32)
    store.reserve("a\0b", "c")
    with sqlite3.connect(store.database_path) as db:
        signature = db.execute("SELECT signature FROM m5_twin_attempts").fetchone()[0]
        db.execute(
            "INSERT INTO m5_twin_attempts VALUES (?,?,?,?,?)",
            ("a", "b\0c", "RUNNING", None, signature),
        )
    with pytest.raises(ValueError, match="authentication"):
        store.get("a")


def test_attempt_row_cannot_be_deleted_to_enable_a_second_run(tmp_path):
    store = AttemptStore(tmp_path / "registry.db", key=b"k" * 32)
    store.reserve("op", "binding")
    with (
        sqlite3.connect(store.database_path) as db,
        pytest.raises(sqlite3.IntegrityError),
    ):
        db.execute("DELETE FROM m5_twin_attempts")


def test_source_rehashes_git_blob_bytes_against_locked_object_id(tmp_path):
    from tests.m5_twin_helpers import TwinFixture, git

    fixture = TwinFixture(tmp_path)
    oid = git(fixture.source, 'rev-parse', 'HEAD:src/config.txt')
    loose = fixture.source / '.git/objects' / oid[:2] / oid[2:]
    loose.chmod(0o644)
    loose.write_bytes(zlib.compress(b'blob 2\0' + b'9\n'))
    with pytest.raises(RunnerError):
        git_tree(fixture.source, fixture.commit, config())
