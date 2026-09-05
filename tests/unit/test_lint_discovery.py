"""Exercise Ruff discovery with the repository's actual configuration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _environment(config_home: Path) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        XDG_CONFIG_HOME=str(config_home),
    )
    return environment


def _git_init(root: Path, environment: dict[str, str]) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True, env=environment)
    subprocess.run(
        ["git", "-C", str(root), "config", "core.excludesFile", os.devnull],
        check=True,
        env=environment,
    )


def _ruff(
    root: Path, environment: dict[str, str], *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", *arguments],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("inherited_build_ignore", [False, True])
def test_builder_diagnostic_is_found_but_root_build_is_ignored(
    tmp_path: Path, inherited_build_ignore: bool
) -> None:
    environment = _environment(tmp_path / "config")
    if inherited_build_ignore:
        _git_init(tmp_path, environment)
        (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
    root = tmp_path / "project"
    _git_init(root, environment)
    for name in (".gitignore", "pyproject.toml"):
        shutil.copyfile(ROOT / name, root / name)
    for name in ("src/contractcapsule/build/probe.py", "build/generated.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("missing_builder_name\n", encoding="utf-8")

    result = _ruff(
        root, environment, ".", "--select", "F821", "--output-format", "json"
    )

    assert result.returncode == 1, (result.stdout, result.stderr)
    assert [
        (Path(item["filename"]).relative_to(root).as_posix(), item["code"])
        for item in json.loads(result.stdout)
    ] == [("src/contractcapsule/build/probe.py", "F821")]


def test_directory_discovery_covers_independent_python_inventory(
    tmp_path: Path,
) -> None:
    expected = {
        path.relative_to(ROOT).as_posix()
        for directory in (ROOT / "src/contractcapsule", ROOT / "tests")
        for path in directory.rglob("*.py")
    }
    builder = {
        path for path in expected if path.startswith("src/contractcapsule/build/")
    }
    assert builder == {
        "src/contractcapsule/build/__init__.py",
        "src/contractcapsule/build/atomize.py",
        "src/contractcapsule/build/ingest.py",
        "src/contractcapsule/build/publish.py",
    }
    result = _ruff(
        ROOT,
        _environment(tmp_path / "config"),
        "src/contractcapsule",
        "tests",
        "--show-files",
    )
    assert result.returncode == 0, result.stderr
    discovered = {
        Path(line).relative_to(ROOT).as_posix()
        for line in result.stdout.splitlines()
        if line.endswith(".py")
    }
    assert discovered == expected
