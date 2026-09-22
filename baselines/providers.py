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

from contractcapsule.models.view import CompiledView, view_manifest_digest
from contractcapsule.validate.integrity import ValidationService
from contractcapsule.validate.reports import CompressionReport

from .budget import (
    Budget,
    BudgetError,
    BudgetOverflow,
    budget_digest,
    count_tokens,
    enforce_budget,
    normalize_budget,
    payload_bytes,
)


class ProviderError(ValueError):
    """A task package cannot be converted into a trusted context artifact."""


# Process-local capability set only by ``ContextProvider.provide``.  A caller
# can construct a structurally valid ``ContextArtifact`` for display, but it
# cannot pass one to the experiment runner as provider output without this
# attestation.
_PROVIDER_ATTESTATION = object()


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
    r"(?:\b(?:gold|condition|expected)\b\s*[:=]|"
    r"gold[-_ ]?(?:label|atom|truth|check)|target[-_ ]?effect|"
    r"protected[-_ ]?(?:invariant|check)|forbidden[-_ ]?spillover|"
    r"expected[-_ ]?(?:condition|outcome|label))",
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
    _provider_attestation: object | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _provider_task_id: str | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _provider_repository_commit: str | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _provider_package_root: str | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _provider_package_digest: str | None = field(
        default=None, init=False, repr=False, compare=False
    )

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
            if self.token_count != count_tokens(self.content):
                raise ProviderError("artifact token count does not match content")
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


def _attest_artifact(
    artifact: ContextArtifact,
    *,
    task_id: str | None,
    repository_commit: str | None,
    package_root: Path | None,
    package_digest: str | None,
) -> ContextArtifact:
    object.__setattr__(artifact, "_provider_attestation", _PROVIDER_ATTESTATION)
    object.__setattr__(artifact, "_provider_task_id", task_id)
    object.__setattr__(artifact, "_provider_repository_commit", repository_commit)
    object.__setattr__(
        artifact,
        "_provider_package_root",
        str(package_root) if package_root is not None else None,
    )
    object.__setattr__(artifact, "_provider_package_digest", package_digest)
    return artifact


def is_provider_artifact(value: object) -> bool:
    """Return whether ``value`` is an artifact emitted by a context provider."""

    return (
        type(value) is ContextArtifact
        and getattr(value, "_provider_attestation", None) is _PROVIDER_ATTESTATION
    )


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
        if (
            len(source_paths) == 1
            and source_paths[0].startswith("compiled-view:")
        ):
            metadata["view_manifest_digest"] = source_paths[0].split(":", 1)[1]
        base_task = _base_task(selected)
        task_id = _lookup(base_task, "task_id")
        repository = _lookup(base_task, "repository")
        repository_commit = _lookup(repository, "commit")
        if task_id is not None and not isinstance(task_id, str):
            raise ProviderError("task_id is invalid")
        if repository_commit is not None and not isinstance(repository_commit, str):
            raise ProviderError("repository commit is invalid")
        package_root = _task_root(selected)
        package_digest = getattr(base_task, "_loader_package_digest", None)
        if package_digest is not None and not isinstance(package_digest, str):
            raise ProviderError("task package digest is invalid")
        return _attest_artifact(
            ContextArtifact(
                condition=self.condition,
                content=payload,
                digest=digest,
                token_count=token_count,
                budget=normalized,
                byte_count=byte_count,
                metadata=metadata,
            ),
            task_id=task_id,
            repository_commit=repository_commit,
            package_root=package_root,
            package_digest=package_digest,
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


def _base_task(task: object) -> object:
    return task.task if isinstance(task, _TaskOverride) else task


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
        raw = getattr(_base_task(task), "_loader_root", None)
    if raw is None:
        return None
    value = _path_value(raw)
    if value is None:
        raise ProviderError("task package root is invalid")
    root = Path(value).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    # A provider may be called directly, without the benchmark loader's
    # package-root checks. Reject symlink components before resolving so a
    # caller cannot redirect a task package to an unrelated directory.
    probe = Path(root.anchor)
    for part in root.parts[1:]:
        probe /= part
        if probe.is_symlink():
            raise ProviderError("task package root must not contain symlinks")
    try:
        root = root.resolve(strict=True)
    except OSError as error:
        raise ProviderError("task package root is unavailable") from error
    if not root.is_dir():
        raise ProviderError("task package root is not a directory")
    return root


def _task_approved(task: object) -> bool:
    approval = _lookup(task, "human_approval", "approval_status")
    if getattr(approval, "value", approval) != "approved":
        return False
    if _lookup(task, "executable") is not True:
        return False
    repository = _lookup(task, "repository")
    return _lookup(repository, "source_status") == "verified"


def _declared_p0_paths(task: object) -> frozenset[str]:
    raw = _lookup(task, "p0_paths", "mandatory_p0_paths")
    if raw is None:
        return frozenset()
    if isinstance(raw, (str, Path, Mapping)) or not isinstance(raw, Iterable):
        raise ProviderError("task P0 metadata is invalid")
    paths: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item or "\\" in item or item.startswith("/"):
            raise ProviderError("task P0 path is invalid")
        parts = item.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ProviderError("task P0 path is invalid")
        paths.add(item)
    if paths and not _task_approved(task):
        raise ProviderError("P0 metadata requires an approved executable task")
    return frozenset(paths)


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
    parts = {part.casefold() for part in Path(relative).parts}
    return bool(parts & _EXCLUDED_PARTS)


def _sanitize(raw: str, *, p0: bool) -> str:
    try:
        raw.encode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ProviderError("context file is not valid UTF-8") from error
    lines: list[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        has_forbidden_marker = _GOLD_MARKER.search(line) or _CONDITION_TOKEN.search(line)
        # P0 is exact material. Silently deleting a marked line would turn a
        # failed integrity check into a successful but incomplete view.
        if p0 and has_forbidden_marker:
            raise ProviderError("declared P0 context contains a gold or condition marker")
        # Non-P0 material is filtered so benchmark labels cannot enter a view.
        if has_forbidden_marker:
            continue
        lines.append(line.rstrip())
    text = "\n".join(lines).strip()
    return text


def _source_digest(paths: Sequence[str]) -> str:
    payload = "\n".join(paths).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _collect_sources(task: object) -> tuple[_Source, ...]:
    root = _task_root(task)
    p0_paths = _declared_p0_paths(task)
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

    if not pairs and p0_paths:
        raise ProviderError("declared P0 path is unavailable")
    if not pairs:
        raw = _lookup(task, "context", "context_text", "prompt", "prompt_text", "description")
        if isinstance(raw, str) and raw:
            text = _sanitize(raw, p0=False)
            if text:
                return (_Source("task-context", text, False),)
        return ()

    sources: list[_Source] = []
    seen_p0: set[str] = set()
    for relative, path in pairs:
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ProviderError("context file cannot be read") from error
        normalized_relative = relative.replace("\\", "/")
        p0 = normalized_relative in p0_paths
        if p0:
            seen_p0.add(normalized_relative)
        text = _sanitize(raw, p0=p0)
        if text:
            sources.append(_Source(relative, text, p0))
    if p0_paths - seen_p0:
        raise ProviderError("declared P0 path is unavailable")
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
                statements.append(
                    _Source(
                        source.relative_path,
                        _sanitize(statement, p0=source.p0),
                        source.p0,
                    )
                )
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
        if not _task_approved(task):
            raise ProviderError("CC requires an approved executable task and compiled view manifest")
        compiled = _lookup(task, "compiled_view")
        if type(compiled) is not CompiledView or not compiled.validation.valid:
            raise ProviderError("CC requires a validated compiled view manifest")
        service = _lookup(task, "compiled_view_service", "validation_service")
        capsules = _lookup(task, "compiled_view_capsules", "capsules")
        if type(service) is not ValidationService:
            raise ProviderError("CC requires an independent validation service proof")
        if type(capsules) is not list or not capsules:
            raise ProviderError("CC requires the exact validated capsule list")
        task_id = _lookup(task, "task_id")
        try:
            request = service.request
            request_task_id = request.task.task_id
            request_budget = request.budget.available
        except Exception as error:
            raise ProviderError("CC validation service request is invalid") from error
        if task_id is None or request_task_id != task_id or compiled.manifest.task_id != task_id:
            raise ProviderError("compiled view task binding mismatch")
        actual_manifest = view_manifest_digest(compiled.manifest)
        if request_budget != budget.max_tokens:
            raise ProviderError("compiled view budget binding mismatch")
        if compiled.manifest.model_id != request.model_id:
            raise ProviderError("compiled view model binding mismatch")
        if compiled.manifest.tokenizer_profile != request.tokenizer_profile:
            raise ProviderError("compiled view tokenizer binding mismatch")
        if compiled.manifest.renderer_version != request.renderer_version:
            raise ProviderError("compiled view renderer binding mismatch")
        if compiled.manifest.tokens.available != budget.max_tokens:
            raise ProviderError("compiled view budget mismatch")
        try:
            report = service.validate_compression(compiled, capsules)
            if type(report) is not CompressionReport or not report.valid:
                raise ProviderError("independent CCS compression validation failed")
            service.verify_report(report, capsules, view=compiled)
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError("independent CCS compression validation failed") from error
        token_count = count_tokens(compiled.content)
        if token_count != compiled.manifest.tokens.total:
            raise ProviderError("compiled view token accounting mismatch")
        if token_count > budget.max_tokens:
            raise BudgetOverflow("p0_budget_overflow")
        if _GOLD_MARKER.search(compiled.content) or _CONDITION_TOKEN.search(
            compiled.content
        ):
            raise ProviderError("compiled view contains condition or gold markers")
        # The compiler has already performed closure/P0 selection. Treat the
        # resulting view as mandatory so this provider can never trim it.
        return compiled.content, True, ("compiled-view:" + actual_manifest,)


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
    "is_provider_artifact",
    "provider_for",
]
