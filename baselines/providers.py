"""Condition-blind CapsuleBench context providers.

The providers intentionally operate on a small ``TaskSpec``-shaped boundary
instead of importing the benchmark loader.  This keeps the baseline substrate
usable while task packages are being screened and lets the loader evolve
without duplicating its schema here.
"""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar

from .budget import (
    Budget,
    BudgetError,
    BudgetOverflow,
    budget_digest,
    enforce_budget,
    normalize_budget,
    payload_bytes,
)


class ProviderError(ValueError):
    """A task package cannot be converted into a trusted context artifact."""


class Condition(StrEnum):
    """The six preregistered primary study conditions."""

    B0 = "B0"
    B1 = "B1"
    B2 = "B2"
    B3 = "B3"
    B4 = "B4"
    CC = "CC"


_CONDITION_TOKEN = re.compile(r"(?<![A-Za-z0-9_])(?:B[0-4]|CC)(?![A-Za-z0-9_])")
_GOLD_MARKER = re.compile(
    r"(?:gold|condition|target[-_ ]?effect|protected[-_ ]?invariant|"
    r"forbidden[-_ ]?spillover|expected[-_ ]?(?:condition|outcome|label))",
    re.IGNORECASE,
)
_TEXT_EXTENSIONS = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".go",
        ".h",
        ".hpp",
        ".java",
        ".js",
        ".json",
        ".jsonl",
        ".md",
        ".py",
        ".rs",
        ".sh",
        ".sql",
        ".text",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)
_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "adjudication",
        "gold",
        "licenses",
        "results",
        "tests",
        "__pycache__",
    }
)


@dataclass(frozen=True, slots=True)
class _Source:
    relative_path: str
    text: str
    p0: bool = False


@dataclass(frozen=True, slots=True)
class _TaskOverride:
    """Attach a package root to a schema object without mutating it."""

    task: object
    package_root: object


@dataclass(frozen=True, slots=True)
class ContextArtifact:
    """Immutable provider output with neutral digest and budget accounting."""

    condition: Condition
    content: str
    digest: str
    token_count: int
    budget: Budget
    byte_count: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            condition = self.condition
            if not isinstance(condition, Condition):
                condition = Condition(str(condition))
            if type(self.content) is not str:
                raise ProviderError("artifact content must be text")
            if type(self.digest) is not str or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", self.digest
            ):
                raise ProviderError("artifact digest is invalid")
            expected_digest = "sha256:" + hashlib.sha256(
                self.content.encode("utf-8", errors="strict")
            ).hexdigest()
            if self.digest != expected_digest:
                raise ProviderError("artifact digest does not match content")
            if type(self.token_count) is not int or self.token_count < 0:
                raise ProviderError("artifact token count is invalid")
            normalized = normalize_budget(self.budget)
            if type(self.byte_count) is not int or self.byte_count < 0:
                raise ProviderError("artifact byte count is invalid")
            if self.byte_count != payload_bytes(self.content):
                raise ProviderError("artifact byte count does not match content")
            metadata = dict(self.metadata)
            object.__setattr__(self, "condition", condition)
            object.__setattr__(self, "budget", normalized)
            object.__setattr__(self, "metadata", MappingProxyType(metadata))
        except (BudgetError, TypeError, ValueError) as error:
            if isinstance(error, ProviderError):
                raise
            raise ProviderError("invalid context artifact") from error

    @property
    def payload(self) -> str:
        """Alias used by the benchmark harness and scorer."""

        return self.content

    @property
    def text(self) -> str:
        return self.content

    @property
    def view(self) -> str:
        return self.content

    @property
    def tokens(self) -> int:
        return self.token_count

    @property
    def budget_tokens(self) -> int:
        return self.budget.max_tokens

    @property
    def payload_digest(self) -> str:
        return self.digest

    @property
    def runtime_view(self) -> str:
        return self.content

    @property
    def payload_bytes(self) -> bytes:
        return self.content.encode("utf-8")

    def as_dict(self) -> dict[str, Any]:
        """Serialize without exposing source labels or gold material."""

        return {
            "condition": self.condition.value,
            "content": self.content,
            "digest": self.digest,
            "token_count": self.token_count,
            "budget_tokens": self.budget.max_tokens,
            "byte_count": self.byte_count,
            "metadata": dict(self.metadata),
        }


class ContextProvider(ABC):
    """Common interface implemented by every primary condition."""

    condition: ClassVar[Condition]

    def __init__(
        self,
        task: object | None = None,
        package_root: object | None = None,
        *,
        task_root: object | None = None,
        context_root: object | None = None,
    ) -> None:
        self._bound_task = task
        roots = [value for value in (package_root, task_root, context_root) if value is not None]
        if len(roots) > 1:
            raise ProviderError("task package root provided more than once")
        self._bound_root = roots[0] if roots else None

    @abstractmethod
    def _render(
        self, task: object, budget: Budget
    ) -> tuple[str, bool, tuple[str, ...]]:
        """Return payload, whether it contains mandatory P0 material, sources."""

    def provide(
        self,
        task: object | None = None,
        budget: object | None = None,
        *args: object,
        package_root: object | None = None,
        task_root: object | None = None,
        context_root: object | None = None,
    ) -> ContextArtifact:
        # Accept both ``provide(task, budget)`` and the task-package-oriented
        # ``provide(task, package_root, budget)`` form used by early M7
        # harnesses.  The latter is normalized before any file is opened.
        if args:
            if len(args) != 1:
                raise ProviderError("provider accepts task, root, and budget")
            if budget is None:
                raise BudgetError("budget is required")
            root_argument, budget = budget, args[0]
            if package_root is not None or task_root is not None or context_root is not None:
                raise ProviderError("task package root provided more than once")
            package_root = root_argument
        selected = self._bound_task if task is None else task
        if selected is None:
            raise ProviderError("task is required")
        if budget is None:
            raise BudgetError("budget is required")
        roots = [
            value
            for value in (self._bound_root, package_root, task_root, context_root)
            if value is not None
        ]
        if len(roots) > 1:
            raise ProviderError("task package root provided more than once")
        if roots:
            selected = _TaskOverride(selected, roots[0])
        normalized = normalize_budget(budget)
        payload, p0, source_paths = self._render(selected, normalized)
        normalized, token_count, byte_count = enforce_budget(payload, normalized, p0=p0)
        source_digest = _source_digest(source_paths)
        digest = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        metadata = {
            "source_count": len(source_paths),
            "source_digest": source_digest,
            "budget_digest": budget_digest(normalized),
            "tokenizer": "ccs-neutral-o200k/1.0.0",
        }
        return ContextArtifact(
            condition=self.condition,
            content=payload,
            digest=digest,
            token_count=token_count,
            budget=normalized,
            byte_count=byte_count,
            metadata=metadata,
        )

    # These aliases make the boundary convenient for the experiment harness
    # while retaining one implementation and one accounting path.
    def build(
        self,
        task: object | None = None,
        budget: object | None = None,
        *args: object,
        **kwargs: object,
    ) -> ContextArtifact:
        return self.provide(task, budget, *args, **kwargs)

    def render(
        self,
        task: object | None = None,
        budget: object | None = None,
        *args: object,
        **kwargs: object,
    ) -> ContextArtifact:
        return self.provide(task, budget, *args, **kwargs)

    def __call__(
        self,
        task: object | None = None,
        budget: object | None = None,
        *args: object,
        **kwargs: object,
    ) -> ContextArtifact:
        return self.provide(task, budget, *args, **kwargs)


def _lookup(task: object, *names: str) -> object | None:
    if isinstance(task, _TaskOverride):
        for name in names:
            if name in {"package_root", "package_dir", "task_root", "task_dir", "root"}:
                return task.package_root
        return _lookup(task.task, *names)
    if isinstance(task, Mapping):
        for name in names:
            if name in task:
                return task[name]
    for name in names:
        if hasattr(task, name):
            return getattr(task, name)
    return None


def _path_value(value: object) -> str | None:
    if isinstance(value, (str, Path)):
        return str(value)
    if isinstance(value, Mapping):
        for key in ("path", "relative_path", "file", "source"):
            if key in value:
                return _path_value(value[key])
    for key in ("path", "relative_path", "file", "source"):
        if hasattr(value, key):
            return _path_value(getattr(value, key))
    return None


def _task_root(task: object) -> Path | None:
    raw = _lookup(
        task,
        "package_root",
        "package_dir",
        "task_root",
        "task_dir",
        "root",
        "path",
    )
    if raw is None:
        return None
    value = _path_value(raw)
    if value is None:
        raise ProviderError("task package root is invalid")
    root = Path(value).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    try:
        root = root.resolve(strict=True)
    except OSError as error:
        raise ProviderError("task package root is unavailable") from error
    if not root.is_dir():
        raise ProviderError("task package root is not a directory")
    return root


def _declared_paths(task: object) -> tuple[str, ...]:
    raw = _lookup(
        task,
        "context_files",
        "authorized_context_files",
        "context_paths",
        "source_files",
    )
    if raw is None:
        return ()
    if isinstance(raw, (str, Path, Mapping)):
        raw = (raw,)
    if not isinstance(raw, Iterable):
        raise ProviderError("task context files are invalid")
    paths: set[str] = set()
    for item in raw:
        value = _path_value(item)
        if value is None:
            raise ProviderError("task context file is invalid")
        paths.add(value)
    return tuple(sorted(paths))


def _safe_file(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ProviderError("context path escapes task package")
    candidate = root.joinpath(path)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ProviderError("context file is unavailable") from error
    if root not in resolved.parents or candidate.is_symlink():
        raise ProviderError("context path escapes task package")
    if not resolved.is_file():
        raise ProviderError("context path is not a regular file")
    return resolved


def _excluded(relative: str) -> bool:
    parts = set(Path(relative).parts)
    return bool(parts & _EXCLUDED_PARTS)


def _is_p0(relative: str, raw: str) -> bool:
    lower = relative.casefold()
    return (
        any(part.startswith("p0") for part in Path(lower).parts)
        or "p0_exact" in raw.casefold()
        or '"compression_class"' in raw.casefold()
        and "p0" in raw.casefold()
    )


def _sanitize(raw: str, *, p0: bool) -> str:
    try:
        raw.encode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ProviderError("context file is not valid UTF-8") from error
    lines: list[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not p0 and (_GOLD_MARKER.search(line) or _CONDITION_TOKEN.search(line)):
            continue
        lines.append(line.rstrip())
    text = "\n".join(lines).strip()
    return text


def _source_digest(paths: Sequence[str]) -> str:
    payload = "\n".join(paths).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _collect_sources(task: object) -> tuple[_Source, ...]:
    root = _task_root(task)
    declared = _declared_paths(task)
    pairs: list[tuple[str, Path]] = []
    if root is not None and declared:
        for relative in declared:
            # Validate the path before applying exclusion filters.  A path
            # that mentions ``gold`` must not bypass traversal checks.
            safe_path = _safe_file(root, relative)
            # Gold and scorer files are never runtime context, even when a
            # malformed task lists them as authorized files.
            if _excluded(relative):
                continue
            pairs.append((relative.replace("\\", "/"), safe_path))
    elif root is not None:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            if _excluded(relative) or path.suffix.casefold() not in _TEXT_EXTENSIONS:
                continue
            pairs.append((relative, _safe_file(root, relative)))

    if not pairs:
        raw = _lookup(task, "context", "context_text", "prompt", "prompt_text", "description")
        if isinstance(raw, str) and raw:
            text = _sanitize(raw, p0=_is_p0("task-context", raw))
            if text:
                return (_Source("task-context", text, _is_p0("task-context", raw)),)
        return ()

    sources: list[_Source] = []
    for relative, path in pairs:
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ProviderError("context file cannot be read") from error
        p0 = _is_p0(relative, raw)
        text = _sanitize(raw, p0=p0)
        if text:
            sources.append(_Source(relative, text, p0))
    return tuple(sources)


def _join(sources: Iterable[_Source]) -> tuple[str, bool, tuple[str, ...]]:
    selected = tuple(source for source in sources if source.text)
    return (
        "\n\n".join(source.text for source in selected),
        any(source.p0 for source in selected),
        tuple(source.relative_path for source in selected),
    )


def _query_terms(task: object) -> set[str]:
    raw = _lookup(task, "prompt", "prompt_text", "description", "query", "text")
    if not isinstance(raw, str):
        return set()
    return {term.casefold() for term in re.findall(r"[A-Za-z0-9_]{3,}", raw)}


def _chunks(source: _Source) -> Iterable[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", source.text) if part.strip()]
    if paragraphs:
        yield from paragraphs
    else:
        yield source.text


def _score_chunk(chunk: str, terms: set[str]) -> int:
    words = {term.casefold() for term in re.findall(r"[A-Za-z0-9_]{3,}", chunk)}
    return len(words & terms)


def _bounded_sources(
    sources: Iterable[_Source], budget: Budget
) -> tuple[str, bool, tuple[str, ...]]:
    """Keep mandatory P0 sources and add optional sources while they fit."""

    ordered = tuple(source for source in sources if source.text)
    mandatory = [source for source in ordered if source.p0]
    optional = [source for source in ordered if not source.p0]
    if mandatory:
        payload, p0, _ = _join(mandatory)
        # A P0 overflow is never repaired by dropping another source.
        enforce_budget(payload, budget, p0=True)
        chosen = list(mandatory)
    else:
        chosen = []
    for source in optional:
        candidate = chosen + [source]
        payload, p0, _ = _join(candidate)
        try:
            enforce_budget(payload, budget, p0=p0)
        except BudgetOverflow:
            continue
        chosen.append(source)
    if ordered and not chosen:
        raise BudgetOverflow("budget_overflow")
    return _join(chosen)


def _render_rag(
    task: object, sources: tuple[_Source, ...], budget: Budget
) -> tuple[str, bool, tuple[str, ...]]:
    candidates: list[tuple[int, str, int, str, bool]] = []
    terms = _query_terms(task)
    for source in sources:
        for index, chunk in enumerate(_chunks(source)):
            candidates.append((_score_chunk(chunk, terms), source.relative_path, index, chunk, source.p0))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    chosen: list[_Source] = []
    mandatory = [item for item in candidates if item[4]]
    if mandatory:
        chosen.extend(_Source(path, chunk, p0) for _, path, _, chunk, p0 in mandatory)
        payload, p0, _ = _join(chosen)
        enforce_budget(payload, budget, p0=True)
    for _, path, _, chunk, p0 in candidates:
        source = _Source(path, chunk, p0)
        if source.p0:
            continue
        candidate = chosen + [source]
        payload, has_p0, _ = _join(candidate)
        try:
            enforce_budget(payload, budget, p0=has_p0)
        except BudgetOverflow:
            continue
        chosen.append(source)
    if candidates and not chosen:
        raise BudgetOverflow("budget_overflow")
    return _join(chosen)


def _summary(
    sources: tuple[_Source, ...], budget: Budget
) -> tuple[str, bool, tuple[str, ...]]:
    reduced: list[_Source] = []
    for source in sources:
        if source.p0:
            reduced.append(source)
            continue
        lines = [line.strip() for line in source.text.splitlines() if line.strip()]
        if not lines:
            continue
        first = lines[0]
        sentence = re.split(r"(?<=[.!?])\s+", first, maxsplit=1)[0]
        reduced.append(_Source(source.relative_path, sentence or first, False))
    return _bounded_sources(reduced, budget)


def _atom_statements(
    sources: tuple[_Source, ...], budget: Budget
) -> tuple[str, bool, tuple[str, ...]]:
    statements: list[_Source] = []
    for source in sources:
        parsed: list[Any] = []
        if source.relative_path.casefold().endswith((".json", ".jsonl")):
            try:
                if source.relative_path.casefold().endswith(".jsonl"):
                    parsed = [json.loads(line) for line in source.text.splitlines() if line.strip()]
                else:
                    value = json.loads(source.text)
                    parsed = value if isinstance(value, list) else [value]
            except (json.JSONDecodeError, TypeError):
                parsed = []
        found = False
        for item in parsed:
            if not isinstance(item, Mapping):
                continue
            statement = item.get("statement")
            if isinstance(statement, str) and statement.strip():
                p0 = "p0" in str(item.get("compression_class", "")).casefold()
                statements.append(_Source(source.relative_path, _sanitize(statement, p0=p0), p0))
                found = True
        if not found:
            statements.append(source)
    return _bounded_sources(statements, budget)


class NativeProvider(ContextProvider):
    condition = Condition.B0

    def _render(
        self, task: object, budget: Budget
    ) -> tuple[str, bool, tuple[str, ...]]:
        del task
        del budget
        return "", False, ()


class FullContextProvider(ContextProvider):
    condition = Condition.B1

    def _render(
        self, task: object, budget: Budget
    ) -> tuple[str, bool, tuple[str, ...]]:
        del budget
        return _join(_collect_sources(task))


class RAGProvider(ContextProvider):
    condition = Condition.B2

    def _render(
        self, task: object, budget: Budget
    ) -> tuple[str, bool, tuple[str, ...]]:
        return _render_rag(task, _collect_sources(task), budget)


class SummaryProvider(ContextProvider):
    condition = Condition.B3

    def _render(
        self, task: object, budget: Budget
    ) -> tuple[str, bool, tuple[str, ...]]:
        return _summary(_collect_sources(task), budget)


class AtomOnlyProvider(ContextProvider):
    condition = Condition.B4

    def _render(
        self, task: object, budget: Budget
    ) -> tuple[str, bool, tuple[str, ...]]:
        return _atom_statements(_collect_sources(task), budget)


class ContractCapsuleProvider(ContextProvider):
    condition = Condition.CC

    def _render(
        self, task: object, budget: Budget
    ) -> tuple[str, bool, tuple[str, ...]]:
        del budget
        explicit = _lookup(task, "compiled_view", "capsule_view", "runtime_view", "view_content")
        if isinstance(explicit, str) and explicit:
            p0 = _is_p0("runtime-view", explicit)
            return _sanitize(explicit, p0=p0), p0, ("runtime-view",)
        return _join(_collect_sources(task))


_PROVIDERS: Mapping[Condition, type[ContextProvider]] = MappingProxyType(
    {
        Condition.B0: NativeProvider,
        Condition.B1: FullContextProvider,
        Condition.B2: RAGProvider,
        Condition.B3: SummaryProvider,
        Condition.B4: AtomOnlyProvider,
        Condition.CC: ContractCapsuleProvider,
    }
)


def provider_for(condition: Condition | str, *args: object, **kwargs: Any) -> ContextProvider:
    """Return a fresh provider for a preregistered condition."""

    try:
        normalized = condition if isinstance(condition, Condition) else Condition(str(condition))
    except (TypeError, ValueError) as error:
        raise ProviderError("unknown benchmark condition") from error
    if len(args) > 2:
        raise ProviderError("provider accepts a task and optional package root")
    if args:
        if "task" in kwargs:
            raise ProviderError("task provided twice")
        if len(args) == 1 and isinstance(args[0], (str, Path)):
            kwargs.setdefault("package_root", args[0])
        else:
            kwargs["task"] = args[0]
    if len(args) == 2:
        if "package_root" in kwargs:
            raise ProviderError("task package root provided twice")
        kwargs["package_root"] = args[1]
    provider_type = _PROVIDERS[normalized]
    return provider_type(**kwargs)


__all__ = [
    "AtomOnlyProvider",
    "Condition",
    "ContextArtifact",
    "ContextProvider",
    "ContractCapsuleProvider",
    "FullContextProvider",
    "NativeProvider",
    "ProviderError",
    "RAGProvider",
    "SummaryProvider",
    "provider_for",
]
