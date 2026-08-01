from hashlib import sha256
from pathlib import Path

CCS_SPEC_PATH = Path("docs/spec/CCS-2.1.md")
SPEC_SHA256 = "aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c"

EXECUTION_PLAN_PATH = Path(
    "docs/superpowers/plans/"
    "2026-07-30-contract-capsule-fse-2027-execution-plan.md"
)
EXECUTION_PLAN_SHA256 = (
    "7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0"
)


class FrozenBaselineMismatch(RuntimeError):
    """Raised when a frozen project baseline is missing or has changed."""


def verify_frozen_baseline(path: Path, expected_digest: str) -> str:
    digest = sha256()
    try:
        with path.open("rb") as baseline:
            for chunk in iter(lambda: baseline.read(1024 * 1024), b""):
                digest.update(chunk)
    except FileNotFoundError as error:
        raise FrozenBaselineMismatch(f"frozen baseline is missing: {path}") from error

    actual_digest = digest.hexdigest()
    if actual_digest != expected_digest:
        raise FrozenBaselineMismatch(
            "frozen baseline digest mismatch: "
            f"expected {expected_digest}, got {actual_digest} for {path}"
        )
    return actual_digest
