"""Real offline tokenizer and complete rendered-text accounting."""

import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from contractcapsule.compile.budget import LocalTokenCounter, account_tokens
from contractcapsule.compile.errors import CompileError
from contractcapsule.models.view import ViewBudget

RESOURCE = Path(__file__).parents[2] / "src/contractcapsule/resources/tokenizers"


@pytest.fixture(scope="module")
def counter() -> LocalTokenCounter:
    return LocalTokenCounter(model_id="neutral-test")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hello world", 2),
        ("hel", 1),
        ("lo", 1),
        ("hello", 1),
        ("", 0),
        ("<|endoftext|>", 7),
        ("\u5408\u540c\u80f6\u56ca", 4),
    ],
)
def test_locked_profile_counts_real_tokens(
    counter: LocalTokenCounter, text: str, expected: int
) -> None:
    assert counter.count(text) == expected


def test_full_count_includes_nonadditive_section_boundary(
    counter: LocalTokenCounter,
) -> None:
    accounting = account_tokens(
        (("a", "hel"), ("b", "lo")), counter, ViewBudget(model_input_tokens=1)
    )
    assert accounting.total == 1
    assert dict(accounting.sections) == {"a": 1, "b": 1}
    assert accounting.boundary_adjustment == -1
    assert accounting.available == 1


def test_attempted_overbudget_accounting_is_not_silently_truncated(
    counter: LocalTokenCounter,
) -> None:
    accounting = account_tokens(
        (("text", "hello world"),), counter, ViewBudget(model_input_tokens=0)
    )
    assert accounting.total == 2 and accounting.available == 0


def test_counter_configuration_is_immutable_and_model_bound(
    counter: LocalTokenCounter,
) -> None:
    with pytest.raises(FrozenInstanceError):
        counter.model_id = "another"  # type: ignore[misc]
    assert (
        LocalTokenCounter(model_id="different").config_digest != counter.config_digest
    )


@pytest.mark.parametrize("filename", ["o200k_base.profile.json", "o200k_base.tiktoken"])
@pytest.mark.parametrize("fault", ["missing", "corrupt", "symlink"])
def test_resources_fail_without_network_or_repair(
    tmp_path: Path, filename: str, fault: str
) -> None:
    directory = tmp_path / "tokenizer"
    shutil.copytree(RESOURCE, directory)
    path = directory / filename
    path.unlink()
    if fault == "corrupt":
        path.write_bytes(b"broken resource")
    elif fault == "symlink":
        path.symlink_to(RESOURCE / filename)
    before = tuple(sorted(p.name for p in directory.iterdir()))
    with (
        patch("requests.get", side_effect=AssertionError("network forbidden")),
        pytest.raises(CompileError, match="TOKENIZER_"),
    ):
        LocalTokenCounter(model_id="neutral-test", resource_dir=directory)
    assert tuple(sorted(p.name for p in directory.iterdir())) == before


def test_healthy_counter_never_uses_tiktoken_downloading_registry() -> None:
    with (
        patch(
            "tiktoken.get_encoding", side_effect=AssertionError("registry forbidden")
        ),
        patch(
            "tiktoken.load.read_file_cached",
            side_effect=AssertionError("loader forbidden"),
        ),
    ):
        assert LocalTokenCounter(model_id="neutral-test").count("hello world") == 2


def test_runtime_library_mismatch_blocks() -> None:
    with (
        patch(
            "contractcapsule.compile.budget.distribution_version",
            return_value="999.0.0",
        ),
        pytest.raises(CompileError, match="TOKENIZER_UNAVAILABLE"),
    ):
        LocalTokenCounter(model_id="neutral-test")


def test_invalid_text_is_not_lossily_repaired(counter: LocalTokenCounter) -> None:
    with pytest.raises(CompileError, match="INVALID_TOKEN_INPUT"):
        counter.count("\ud800")


@pytest.mark.parametrize("result", [True, -1, 1.5, "3"])
def test_counter_results_must_be_nonnegative_strict_integers(result: object) -> None:
    class BadCounter:
        profile = "test"
        model_id = "test"
        version = "1.0.0"
        config_digest = "sha256:" + "0" * 64

        def count(self, text: str) -> int:
            return result  # type: ignore[return-value]

    with pytest.raises(CompileError, match="TOKENIZER_UNAVAILABLE"):
        account_tokens(
            (("part", "text"),), BadCounter(), ViewBudget(model_input_tokens=10)
        )


def test_duplicate_section_names_are_rejected(counter: LocalTokenCounter) -> None:
    with pytest.raises(CompileError, match="INVALID_RENDER_SECTIONS"):
        account_tokens(
            (("same", "a"), ("same", "b")), counter, ViewBudget(model_input_tokens=10)
        )
