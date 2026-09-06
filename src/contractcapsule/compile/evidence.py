"""Native source reads bound to exact publications and current authorization."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from contractcapsule.audit.quarantine import scan_secrets
from contractcapsule.build.ingest import _strict_absolute
from contractcapsule.compile.errors import CompileError
from contractcapsule.compile.git_evidence import read_git_evidence, validate_git_locator
from contractcapsule.compile.protocols import EligibilityAuthorizer, FreshnessChecker
from contractcapsule.models.base import Principal, is_safe_relative_path
from contractcapsule.models.core import Atom, EvidenceRecord
from contractcapsule.models.view import EvidenceHandle, EvidenceMaterial, TaskContext
from contractcapsule.resolve.eligibility import AdmittedCapsule, EligibilityResolver
from contractcapsule.resolve.policies import capsule_ref, snapshot_digest
from contractcapsule.storage.registry import PublishedCapsule, Registry


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _local_bytes(path: Path) -> bytes:
    try:
        path = _strict_absolute(path)
        if not path.is_file():
            raise CompileError("EVIDENCE_UNAVAILABLE")
        return path.read_bytes()
    except (OSError, ValueError, RuntimeError):
        raise CompileError("EVIDENCE_UNAVAILABLE") from None


def _source_span(record: EvidenceRecord, content: bytes) -> tuple[str, str | None]:
    text = content.decode("utf-8", errors="strict")
    if record.mode == "GIT_IMMUTABLE":
        validate_git_locator(record, text)
        locator: Mapping[str, object] = record.locator.model_dump()
    elif "x-source-map" in record.extensions:
        source = record.extensions["x-source-map"]
        if not isinstance(source, Mapping):
            raise CompileError("EVIDENCE_INTEGRITY")
        locator = source
    else:
        return text, None
    start, end = locator.get("start_line"), locator.get("end_line")
    span_digest = locator.get("span_digest")
    lines = text.splitlines(keepends=True)
    if (
        type(start) is not int
        or type(end) is not int
        or not 1 <= start <= end <= len(lines)
        or type(span_digest) is not str
    ):
        raise CompileError("EVIDENCE_INTEGRITY")
    excerpt = "".join(lines[start - 1 : end])
    if _digest(excerpt.encode("utf-8")) != span_digest:
        raise CompileError("EVIDENCE_INTEGRITY")
    return excerpt, span_digest


@dataclass(frozen=True)
class NativeEvidenceResolver:
    registry: Registry = field(repr=False)
    authorizer: EligibilityAuthorizer = field(repr=False)
    freshness: FreshnessChecker = field(repr=False)
    git_roots: Mapping[str, Path] = field(repr=False)
    external_sources: Mapping[str, Path] = field(repr=False)
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        if type(self.registry) is not Registry or self.version != "1.0.0":
            raise CompileError("INVALID_CONFIGURATION")
        for name in ("git_roots", "external_sources"):
            mapping = getattr(self, name)
            if not isinstance(mapping, Mapping) or any(
                type(key) is not str
                or not key
                or not isinstance(path, Path)
                or not path.is_absolute()
                for key, path in mapping.items()
            ):
                raise CompileError("INVALID_CONFIGURATION")
            object.__setattr__(
                self, name, MappingProxyType(dict(sorted(mapping.items())))
            )

    @property
    def config_digest(self) -> str:
        return snapshot_digest(
            {
                "version": self.version,
                "git_roots": {key: str(value) for key, value in self.git_roots.items()},
                "external_sources": {
                    key: str(value) for key, value in self.external_sources.items()
                },
                "authorizer_version": self.authorizer.version,
                "freshness_version": self.freshness.version,
            }
        )

    def _admit(
        self, pub: PublishedCapsule, principal: Principal, task: TaskContext, as_of: str
    ) -> AdmittedCapsule:
        admission = EligibilityResolver(
            self.registry, self.authorizer, self.freshness, as_of
        ).resolve((pub,), task, principal)
        if len(admission.items) != 1:
            raise CompileError("EVIDENCE_UNAUTHORIZED")
        return admission.items[0]

    def _content(self, record: EvidenceRecord, principal: Principal) -> bytes:
        if record.mode == "CAS":
            content = self.registry.get_blob(record.content_digest, principal)
        elif record.mode == "GIT_IMMUTABLE":
            if record.repository not in self.git_roots or not is_safe_relative_path(
                record.path
            ):
                raise CompileError("EVIDENCE_UNAVAILABLE")
            content = read_git_evidence(self.git_roots[record.repository], record)
        else:
            if record.uri not in self.external_sources:
                raise CompileError("EVIDENCE_UNAVAILABLE")
            content = _local_bytes(self.external_sources[record.uri])
        if _digest(content) != record.content_digest:
            raise CompileError("EVIDENCE_INTEGRITY")
        try:
            scan_secrets(content)
        except Exception:  # noqa: BLE001 - scanner faults cannot permit source output.
            raise CompileError("SECRET_DETECTED") from None
        return content

    def _material(
        self, admitted: AdmittedCapsule, record: EvidenceRecord, principal: Principal
    ) -> EvidenceMaterial:
        content = self._content(record, principal)
        excerpt, span_digest = _source_span(record, content)
        # A shared Evidence row must not disclose identifiers of inadmissible siblings.
        members = tuple(sorted(set(record.atom_ids) & set(admitted.atom_ids)))
        handle = EvidenceHandle(
            capsule=capsule_ref(admitted.published.capsule),
            evidence_id=record.evidence_id,
            atom_ids=members,
            mode=record.mode,
            content_digest=record.content_digest,
            span_digest=span_digest,
            resolver_version=self.version,
        )
        return EvidenceMaterial(
            handle=handle,
            excerpt=excerpt,
            full_text=content.decode("utf-8", errors="strict"),
        )

    def resolve(
        self,
        capsule: PublishedCapsule,
        atom: Atom,
        principal: Principal,
        task: TaskContext,
        as_of: str,
    ) -> tuple[EvidenceMaterial, ...]:
        try:
            before = (
                self.authorizer.context_digest(task, principal),
                self.freshness.context_digest(),
            )
            admitted = self._admit(capsule, principal, task, as_of)
            known = {
                item.atom_id: item
                for item in admitted.published.capsule.semantic_payload.atoms
            }
            if atom.atom_id not in admitted.atom_ids or atom != known.get(atom.atom_id):
                raise CompileError("EVIDENCE_UNAUTHORIZED")
            references = set(known[atom.atom_id].evidence_refs)
            material = tuple(
                self._material(admitted, record, principal)
                for record in sorted(
                    admitted.published.capsule.evidence_plane.records,
                    key=lambda r: r.evidence_id,
                )
                if record.evidence_id in references
            )
            if len(material) != len(references) or not material:
                raise CompileError("EVIDENCE_UNAVAILABLE")
            if before != (
                self.authorizer.context_digest(task, principal),
                self.freshness.context_digest(),
            ):
                raise CompileError("POLICY_SNAPSHOT_CHANGED")
            return material
        except CompileError:
            raise
        except Exception:  # noqa: BLE001 - native source/authorization failures must not leak details.
            raise CompileError("EVIDENCE_UNAVAILABLE") from None

    def expand(
        self,
        handle: EvidenceHandle,
        principal: Principal,
        task: TaskContext,
        as_of: str,
    ) -> EvidenceMaterial:
        try:
            pub = self.registry.get(
                handle.capsule.capsule_id, handle.capsule.version, principal
            )
            if (
                capsule_ref(pub.capsule) != handle.capsule
                or handle.resolver_version != self.version
            ):
                raise CompileError("EVIDENCE_INTEGRITY")
            admitted = self._admit(pub, principal, task, as_of)
            if not handle.atom_ids or not set(handle.atom_ids) <= set(
                admitted.atom_ids
            ):
                raise CompileError("EVIDENCE_UNAUTHORIZED")
            atom = next(
                atom
                for atom in pub.capsule.semantic_payload.atoms
                if atom.atom_id == handle.atom_ids[0]
            )
            sources = self.resolve(pub, atom, principal, task, as_of)
            for source in sources:
                if source.handle == handle:
                    return source
            raise CompileError("EVIDENCE_INTEGRITY")
        except CompileError:
            raise
        except Exception:  # noqa: BLE001 - handle lookup is a fail-closed public source boundary.
            raise CompileError("EVIDENCE_UNAVAILABLE") from None
