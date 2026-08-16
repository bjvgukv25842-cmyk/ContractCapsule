"""Deterministic, secret-scanned source snapshot ingestion for M3."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from yaml.tokens import AliasToken, AnchorToken, TagToken

from contractcapsule.audit import quarantine as quarantine_module
from contractcapsule.audit.quarantine import (
    QuarantineError,
    QuarantineStore,
    TrustRoot,
    default_store,
)
from contractcapsule.models import Principal
from contractcapsule.models.base import (
    is_canonical_https_uri,
    is_safe_relative_path,
    reject_surrogates,
)
from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.storage.cas import FilesystemCAS

SourceMode = Literal["CAS", "GIT_IMMUTABLE", "EXTERNAL_IMMUTABLE"]


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _timestamp(value: datetime | None = None) -> str:
    now = value or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _strict_absolute(path: Path) -> Path:
    absolute = Path(path.absolute())
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise QuarantineError(f"source path contains a symbolic link: {current}")
    return absolute


def _canonical_repository(value: str) -> str:
    if not is_canonical_https_uri(value):
        raise QuarantineError("repository identity must be canonical HTTPS")
    return value


def _full_revision(value: str) -> str:
    if not isinstance(value, str) or not (
        (value.startswith("sha1:") and len(value) == 45)
        or (value.startswith("sha256:") and len(value) == 71)
    ):
        raise QuarantineError("Git revision must be a full sha1: or sha256: object ID")
    _algorithm, digest = value.split(":", 1)
    if any(character not in "0123456789abcdef" for character in digest):
        raise QuarantineError("Git revision must use lowercase hexadecimal")
    return value


def _infer_media_type(path: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "text/plain"


def _unique_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise QuarantineError("duplicate JSON object key in source")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise QuarantineError(f"non-finite JSON constant is forbidden: {value}")


def _strict_source_json(text: str) -> object:
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_json_pairs,
            parse_constant=_reject_json_constant,
        )
    except QuarantineError:
        raise
    except json.JSONDecodeError as error:
        raise QuarantineError("source JSON is invalid") from error


class _UniqueSourceYamlLoader(yaml.SafeLoader):
    pass


def _construct_source_mapping(
    loader: _UniqueSourceYamlLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[object, object]:
    loader.flatten_mapping(node)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise QuarantineError("duplicate YAML object key in source")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueSourceYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_source_mapping,
)


def _strict_source_yaml(text: str) -> object:
    try:
        if any(
            isinstance(token, (AliasToken, AnchorToken, TagToken))
            for token in yaml.scan(text)
        ):
            raise QuarantineError(
                "YAML aliases, anchors, and tags are forbidden in source"
            )
        return yaml.load(text, Loader=_UniqueSourceYamlLoader)
    except QuarantineError:
        raise
    except yaml.YAMLError as error:
        raise QuarantineError("source YAML is invalid") from error


def _parser_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".py", ".js", ".ts", ".java", ".go", ".rs", ".c", ".cpp", ".h"}:
        return "code"
    if suffix in {".json", ".jsonl", ".schema"}:
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    return "text"


def _git_show(root: Path, revision: str, relative_path: str) -> bytes:
    raw_revision = revision.split(":", 1)[1]
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "show", f"{raw_revision}:{relative_path}"],
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise QuarantineError("immutable Git source cannot be read locally") from error


def _normalize_git_remote(value: str) -> str:
    remote = value.strip()
    if remote.startswith("git@") and ":" in remote:
        identity, path = remote.split(":", 1)
        remote = f"https://{identity.removeprefix('git@')}/{path}"
    elif remote.startswith("ssh://"):
        parsed = urlsplit(remote)
        if parsed.hostname is None:
            raise QuarantineError("Git remote identity is invalid")
        remote = f"https://{parsed.hostname.lower()}{parsed.path}"
    remote = remote.removesuffix(".git").removesuffix("/")
    return _canonical_repository(remote)


def _verify_repository_identity(root: Path, expected: str) -> None:
    try:
        configured = subprocess.check_output(
            ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise QuarantineError(
            "Git source requires a verifiable origin repository"
        ) from error
    if _normalize_git_remote(configured) != _normalize_git_remote(expected):
        raise QuarantineError("Git origin does not match repository identity")


def _verify_git_commit(root: Path, revision: str) -> None:
    raw_revision = revision.split(":", 1)[1]
    try:
        subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{raw_revision}^{{commit}}"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise QuarantineError("Git revision is not a local immutable commit") from error


@dataclass(frozen=True, slots=True)
class SourceInput:
    """Caller-supplied source locator.

    For CAS and Git modes ``path`` identifies a local regular file.  External mode may
    additionally provide local ``content`` for an offline, independently hashed fixture;
    no network fetch is attempted by M3.
    """

    path: Path | None = None
    mode: SourceMode = "CAS"
    repository: str | None = None
    revision: str | None = None
    repository_root: Path | None = None
    media_type: str | None = None
    access_policy: str = "repository-authorized"
    cas: FilesystemCAS | None = None
    quarantine: QuarantineStore | None = None
    content: bytes | None = None
    uri: str | None = None
    source: str | None = None
    verification_method: str | None = None
    generated: bool = False

    def __post_init__(self) -> None:
        if self.mode not in {"CAS", "GIT_IMMUTABLE", "EXTERNAL_IMMUTABLE"}:
            raise QuarantineError("unsupported source mode")
        if not self.access_policy:
            raise QuarantineError("access_policy must be non-empty")
        reject_surrogates(self.access_policy)
        if self.mode == "GIT_IMMUTABLE":
            if self.path is None or self.repository is None or self.revision is None:
                raise QuarantineError(
                    "Git source requires path, repository, and revision"
                )
            _canonical_repository(self.repository)
            _full_revision(self.revision)
        elif self.mode == "CAS" and self.path is None:
            raise QuarantineError("CAS source requires a local path")
        elif self.mode == "EXTERNAL_IMMUTABLE":
            if (
                not self.uri
                or self.content is None
                or not self.source
                or not self.verification_method
            ):
                raise QuarantineError(
                    "external source requires URI, content, source, and verification method"
                )
            if not (
                is_canonical_https_uri(self.uri)
                or self.uri.startswith("doi:")
                or self.uri.startswith("urn:")
            ):
                raise QuarantineError(
                    "external source locator is not a supported persistent URI"
                )


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """Immutable bytes plus enough locator data to reproduce each source span."""

    snapshot_id: str
    content: bytes
    content_digest: str
    mode: SourceMode
    media_type: str
    captured_at: str
    principal_id: str
    relative_path: str
    path: Path | None = None
    repository_root: Path | None = field(default=None, compare=False, repr=False)
    repository: str | None = None
    revision: str | None = None
    uri: str | None = None
    source: str | None = None
    verification_method: str | None = None
    access_policy: str = "repository-authorized"
    parser_kind: str = "text"
    generated: bool = False
    _quarantine_token: object | None = field(default=None, repr=False, compare=False)
    _source_proof: object | None = field(default=None, repr=False, compare=False)
    quarantine: QuarantineStore = field(
        default_factory=default_store, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        if _digest(self.content) != self.content_digest:
            raise QuarantineError("snapshot content digest mismatch")
        if not self.snapshot_id or not self.relative_path:
            raise QuarantineError("snapshot identifiers are required")
        quarantine_module.scan_secrets(self.content)

    def text(self) -> str:
        try:
            return self.content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise QuarantineError("source snapshot is not valid UTF-8") from error

    def lines(self) -> tuple[str, ...]:
        return tuple(self.text().splitlines(keepends=True))

    def line_span(self, start_line: int, end_line: int) -> bytes:
        lines = self.lines()
        if start_line < 1 or end_line < start_line or end_line > len(lines):
            raise QuarantineError("source span is outside snapshot")
        return "".join(lines[start_line - 1 : end_line]).encode("utf-8")

    def assert_current(self) -> None:
        """Check local bytes and immutable Git bytes before using a binding."""

        if self.mode == "EXTERNAL_IMMUTABLE":
            quarantine_module.scan_secrets(self.content)
            return
        if self.path is None or self.path.is_symlink() or not self.path.is_file():
            raise QuarantineError("source path is unavailable or not regular")
        current = _strict_absolute(self.path).read_bytes()
        if _digest(current) != self.content_digest or current != self.content:
            raise QuarantineError("source drift detected")
        if self.mode == "GIT_IMMUTABLE":
            if self.repository_root is None:
                raise QuarantineError("verified repository root is required")
            committed = _git_show(
                self.repository_root, self.revision or "", self.relative_path
            )
            if committed != self.content:
                raise QuarantineError("immutable Git source drift detected")


@dataclass(frozen=True, slots=True)
class TrustedDeterministicCollector:
    """Service-composed Git collector that alone may attest deterministic T2 input.

    Possession of the Registry/Quarantine trust root is an application-composition
    authority, not a per-request option. Public ``snapshot_source`` deliberately
    lacks this authority and therefore classifies caller input as T3.
    """

    quarantine: QuarantineStore
    _capability: object = field(repr=False, compare=False)

    def __init__(self, quarantine: QuarantineStore, trust_root: TrustRoot) -> None:
        if type(quarantine) is not QuarantineStore:
            raise TypeError("collector quarantine must be a QuarantineStore")
        if type(trust_root) is not TrustRoot:
            raise TypeError("collector trust_root must be a TrustRoot")
        object.__setattr__(self, "quarantine", quarantine)
        object.__setattr__(
            self,
            "_capability",
            quarantine._bind_deterministic_collector(trust_root),
        )

    def snapshot(self, source: SourceInput, principal: Principal) -> SourceSnapshot:
        if type(source) is not SourceInput:
            raise TypeError("source must be a SourceInput")
        if source.quarantine is not self.quarantine:
            raise QuarantineError(
                "trusted collector source must use its composed quarantine"
            )
        return _snapshot_source(source, principal, self._capability)


def _snapshot_source(
    source: SourceInput,
    principal: Principal,
    collector_capability: object | None,
) -> SourceSnapshot:
    """Capture and register one immutable source snapshot."""

    if type(principal) is not Principal:
        raise TypeError("principal must be a Principal")
    # Uncomposed ingestion gets an isolated deny-only quarantine. Reusing the
    # module default would let unrelated requests collide on snapshot identity
    # and mutable local source handles.
    store = source.quarantine or QuarantineStore()
    path: Path | None = None
    relative_path = "external/content"
    repository_root: Path | None = None
    if source.mode in {"CAS", "GIT_IMMUTABLE"}:
        assert source.path is not None
        path = _strict_absolute(source.path)
        if not path.exists() or not path.is_file() or path.is_symlink():
            raise QuarantineError("source path must be an existing regular file")
        repository_root = _strict_absolute(source.repository_root or path.parent)
        if not repository_root.exists() or not repository_root.is_dir():
            raise QuarantineError("repository root must be an existing directory")
        try:
            relative_path = path.relative_to(repository_root).as_posix()
        except ValueError as error:
            raise QuarantineError(
                "source path must be inside repository root"
            ) from error
        if not is_safe_relative_path(relative_path):
            raise QuarantineError("source path is not a safe repository-relative path")
        content = path.read_bytes()
        if source.mode == "GIT_IMMUTABLE":
            assert source.repository is not None and source.revision is not None
            _verify_repository_identity(repository_root, source.repository)
            _verify_git_commit(repository_root, source.revision)
            committed = _git_show(repository_root, source.revision, relative_path)
            if committed != content:
                raise QuarantineError(
                    "source working tree differs from immutable commit"
                )
    else:
        assert source.content is not None and source.uri is not None
        content = bytes(source.content)
        if source.uri.startswith("doi:") or source.uri.startswith("urn:"):
            relative_path = source.uri
    quarantine_module.scan_secrets(content)
    parser_kind = _parser_kind(path or Path(relative_path))
    decoded_content = content.decode("utf-8", errors="strict")
    if parser_kind == "json":
        _strict_source_json(decoded_content)
    elif parser_kind == "yaml":
        _strict_source_yaml(decoded_content)
    digest = _digest(content)
    if source.cas is not None:
        reference = source.cas.put_blob(
            content,
            source.media_type
            or _infer_media_type(path or Path(relative_path), source.media_type),
        )
        if reference.digest != digest:
            raise QuarantineError("CAS returned an unexpected source digest")
    media_type = _infer_media_type(path or Path(relative_path), source.media_type)
    metadata = {
        "mode": source.mode,
        "repository": source.repository,
        "revision": source.revision,
        "path": relative_path,
        "content_digest": digest,
        "media_type": media_type,
        "uri": source.uri,
        "source": source.source,
        "verification_method": source.verification_method,
        "access_policy": source.access_policy,
        "generated": source.generated,
    }
    snapshot_id = (
        "snapshot-" + hashlib.sha256(canonical_json_bytes(metadata)).hexdigest()[:32]
    )
    snapshot = SourceSnapshot(
        snapshot_id=snapshot_id,
        content=content,
        content_digest=digest,
        mode=source.mode,
        media_type=media_type,
        captured_at=_timestamp(),
        principal_id=principal.principal_id,
        relative_path=relative_path,
        path=path,
        repository_root=repository_root,
        repository=source.repository,
        revision=source.revision,
        uri=source.uri,
        source=source.source,
        verification_method=source.verification_method,
        access_policy=source.access_policy,
        parser_kind=parser_kind,
        generated=source.generated,
        quarantine=store,
    )
    object.__setattr__(snapshot, "_quarantine_token", store._snapshot_capability())
    # Only the service-composed collector can request a T2 proof after the Git,
    # commit, parser, digest, and source-path checks above. Public ingestion has no
    # collector capability, so ``generated=False`` remains a non-authoritative hint.
    if collector_capability is not None:
        proof = store._issue_deterministic_source_proof(
            snapshot, collector_capability
        )
        if proof is not None:
            object.__setattr__(snapshot, "_source_proof", proof)
    registered = store.register_snapshot(snapshot)
    if type(registered) is not SourceSnapshot:
        raise QuarantineError("snapshot registration returned an invalid object")
    return registered


def snapshot_source(source: SourceInput, principal: Principal) -> SourceSnapshot:
    """Capture caller input as T3, irrespective of its generated declaration."""

    return _snapshot_source(source, principal, None)
