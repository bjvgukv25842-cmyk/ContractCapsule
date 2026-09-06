"""Offline, resource-locked token counting and full-text budget accounting."""

import base64
import hashlib
import json
from dataclasses import dataclass, field
from importlib.metadata import version as distribution_version
from pathlib import Path

import tiktoken

from contractcapsule.build.ingest import _strict_absolute
from contractcapsule.compile.errors import CompileError
from contractcapsule.compile.protocols import TokenCounter
from contractcapsule.models.base import reject_surrogates
from contractcapsule.models.view import TokenAccounting, ViewBudget
from contractcapsule.resolve.policies import snapshot_digest

_PROFILE_HASH = "df47711b119989c276e11a040d7a727cb10eff78216c3b1c38614d8aadf63653"
_VOCAB_HASH = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"


def _verified_bytes(path: Path, digest: str) -> bytes:
    try:
        path = _strict_absolute(path)
        if not path.is_file():
            raise CompileError("TOKENIZER_UNAVAILABLE")
        data = path.read_bytes()
    except (OSError, ValueError, RuntimeError):
        raise CompileError("TOKENIZER_UNAVAILABLE") from None
    if hashlib.sha256(data).hexdigest() != digest:
        raise CompileError("TOKENIZER_INTEGRITY")
    return data


def _local_encoding(directory: Path) -> tiktoken.Encoding:
    profile = json.loads(
        _verified_bytes(directory / "o200k_base.profile.json", _PROFILE_HASH)
    )
    vocabulary = _verified_bytes(directory / "o200k_base.tiktoken", _VOCAB_HASH)
    ranks: dict[bytes, int] = {}
    for line in vocabulary.splitlines():
        token, rank = line.split()
        value = base64.b64decode(token, validate=True)
        if value in ranks:
            raise CompileError("TOKENIZER_INTEGRITY")
        ranks[value] = int(rank)
    if set(ranks.values()) != set(range(len(ranks))):
        raise CompileError("TOKENIZER_INTEGRITY")
    return tiktoken.Encoding(**profile["encoding"], mergeable_ranks=ranks)


@dataclass(frozen=True)
class LocalTokenCounter:
    """Exact neutral-text encoding, not an inferred provider billing counter."""

    model_id: str
    resource_dir: Path | None = field(default=None, repr=False)
    _encoding: tiktoken.Encoding = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            if type(self.model_id) is not str or not self.model_id:
                raise CompileError("INVALID_CONFIGURATION")
            reject_surrogates(self.model_id)
            if distribution_version("tiktoken") != "0.14.0":
                raise CompileError("TOKENIZER_UNAVAILABLE")
            directory = self.resource_dir
            if directory is None:
                directory = Path(__file__).parents[1] / "resources/tokenizers"
            object.__setattr__(self, "_encoding", _local_encoding(directory))
        except CompileError:
            raise
        except (
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
            AttributeError,
            ImportError,
        ):
            raise CompileError("TOKENIZER_UNAVAILABLE") from None

    @property
    def profile(self) -> str:
        return "ccs-neutral-o200k/1.0.0"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def config_digest(self) -> str:
        return snapshot_digest(
            {
                "model_id": self.model_id,
                "profile": self.profile,
                "version": self.version,
                "library": "tiktoken/0.14.0",
                "profile_sha256": _PROFILE_HASH,
                "vocabulary_sha256": _VOCAB_HASH,
                "special_tokens": "ordinary_text",
            }
        )

    def count(self, text: str) -> int:
        try:
            if type(text) is not str:
                raise CompileError("INVALID_TOKEN_INPUT")
            reject_surrogates(text)
            return len(self._encoding.encode_ordinary(text))
        except CompileError:
            raise
        except (ValueError, TypeError, RuntimeError):
            raise CompileError("INVALID_TOKEN_INPUT") from None


def rendered_content(sections: tuple[tuple[str, str], ...]) -> str:
    if type(sections) is not tuple:
        raise CompileError("INVALID_RENDER_SECTIONS")
    names: set[str] = set()
    for part in sections:
        if type(part) is not tuple or len(part) != 2:
            raise CompileError("INVALID_RENDER_SECTIONS")
        name, text = part
        if type(name) is not str or not name or name in names or type(text) is not str:
            raise CompileError("INVALID_RENDER_SECTIONS")
        names.add(name)
    return "".join(text for _, text in sections)


def _count(counter: TokenCounter, text: str) -> int:
    try:
        result = counter.count(text)
        if type(result) is not int or not 0 <= result <= 2**53 - 1:
            raise CompileError("TOKENIZER_UNAVAILABLE")
        return result
    except Exception:  # noqa: BLE001 - injected counters must fail closed without raw diagnostics.
        raise CompileError("TOKENIZER_UNAVAILABLE") from None


def account_tokens(
    sections: tuple[tuple[str, str], ...], counter: TokenCounter, budget: ViewBudget
) -> TokenAccounting:
    content = rendered_content(sections)
    counts = {name: _count(counter, text) for name, text in sections}
    total = _count(counter, content)
    return TokenAccounting(
        total=total,
        available=budget.available,
        sections=counts,
        boundary_adjustment=total - sum(counts.values()),
    )
