"""Strict release comparison, independently of interface labels and lock identity."""

import pytest

from contractcapsule.compile.errors import CompileError
from contractcapsule.resolve.versions import parse_interface, satisfies


@pytest.mark.parametrize(
    ("version", "constraint", "expected"),
    [
        ("1.2.0", "==1.2", True),
        ("1.0.0", ">= 1, < 2", True),
        ("1.0.0", ">1", False),
        ("1.0.0", "<=1", True),
        ("1.0.0", "!=1", False),
        ("1.0.0", "<1", False),
        ("1.0.0+first", "==1.0.0+second", True),
        ("1.0.0-alpha", "<1.0.0-alpha.1", True),
        ("1.0.0-alpha.1", "<1.0.0-alpha.beta", True),
        ("1.0.0-beta.2", "<1.0.0-beta.11", True),
        ("1.0.0-rc.1", "<1.0.0", True),
        ("2.0.0", ">=1,<2", False),
    ],
)
def test_release_comparisons(version: str, constraint: str, expected: bool) -> None:
    assert satisfies(version, constraint) is expected


@pytest.mark.parametrize(
    "constraint",
    [
        "",
        " ",
        "1",
        "^1",
        "~1",
        "==1.*",
        ">=1 || <2",
        ">=01",
        "==1.02",
        "==1.0.0-01",
        "==1.0.0\n",
        ">=1,",
        ">=1,broken",
        "===1",
        "==v1.0.0",
    ],
)
def test_invalid_constraint_rejected(constraint: str) -> None:
    with pytest.raises(CompileError, match="^INVALID_VERSION_CONSTRAINT$"):
        satisfies("1.0.0", constraint)


@pytest.mark.parametrize("value", ["01.0.0", "1.0.0-01", "1.0.0\n", "v1.0.0"])
def test_invalid_release_rejected(value: str) -> None:
    with pytest.raises(CompileError, match="^INVALID_VERSION_CONSTRAINT$"):
        satisfies(value, ">=1")


def test_interface_preserves_exact_versioned_name() -> None:
    assert parse_interface("security/auth/v12") == (
        "security/auth",
        "security/auth/v12",
    )


@pytest.mark.parametrize("value", ["auth", "auth/v01", "/v1", "auth/v1\n"])
def test_interface_grammar_matches_admission(value: str) -> None:
    with pytest.raises(CompileError, match="^INTERFACE_INCOMPATIBLE$"):
        parse_interface(value)
