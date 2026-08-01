from pathlib import Path

import pytest

from contractcapsule.spec_lock import (
    CCS_SPEC_PATH,
    EXECUTION_PLAN_PATH,
    EXECUTION_PLAN_SHA256,
    SPEC_SHA256,
    FrozenBaselineMismatch,
    verify_frozen_baseline,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("relative_path", "expected_digest"),
    [
        (
            CCS_SPEC_PATH,
            "aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c",
        ),
        (
            EXECUTION_PLAN_PATH,
            "7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0",
        ),
    ],
)
def test_frozen_baseline_matches_approved_digest(
    relative_path: Path, expected_digest: str
) -> None:
    assert verify_frozen_baseline(REPOSITORY_ROOT / relative_path, expected_digest) == (
        expected_digest
    )


def test_exported_digests_are_the_approved_values() -> None:
    assert (
        SPEC_SHA256
        == "aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c"
    )
    assert (
        EXECUTION_PLAN_SHA256
        == "7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0"
    )


def test_modified_baseline_is_rejected(tmp_path: Path) -> None:
    modified_spec = tmp_path / "CCS-2.1.md"
    source = REPOSITORY_ROOT / CCS_SPEC_PATH
    modified_spec.write_bytes(source.read_bytes() + b"\nmodified\n")

    with pytest.raises(FrozenBaselineMismatch, match="frozen baseline digest mismatch"):
        verify_frozen_baseline(modified_spec, SPEC_SHA256)
