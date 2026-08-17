"""Fail-closed quarantine and human-approval primitives for M3.

The quarantine store is deliberately small and local.  It is an audit boundary, not a
replacement for the M2 Registry or a production identity/signature service.  In
particular, a candidate can only be promoted when an injected trusted authority verifies
an approval record that covers the exact candidate and evidence digests.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any, Protocol

from contractcapsule.models.base import (
    ModelInvariantError,
    freeze_json,
    reject_surrogates,
    thaw_json,
)
from contractcapsule.models.canonical import canonical_json_bytes


class QuarantineError(ValueError):
    """A candidate cannot cross the quarantine trust boundary."""


class SecretDetectedError(QuarantineError):
    """Source or evidence text contains a likely secret."""


class TrustLevel:
    """Stable trust labels used by the M3 evidence pipeline."""

    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_PEM_SECRET_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_TOKEN_PREFIX_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,}|"
    r"sk-(?:live|test)-[A-Za-z0-9]{10,}|xox[baprs]-[A-Za-z0-9-]{12,})\b"
)
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|secret(?:[_-]?key)?|password|passwd)"
    r"\b\s*[:=]\s*(['\"]?)([A-Za-z0-9_./+=:-]{12,})\1"
)

TRUST_POLICY_VERSION = "CCS-2.1-m3-trust-v1"
SECRET_SCANNER_VERSION = "m3-secret-scanner-v1"
DETERMINISTIC_SOURCE_PROFILE = "CCS-2.1-deterministic-source-v1"


def _ensure_digest(value: str, label: str = "digest") -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise QuarantineError(f"{label} must be a canonical sha256 digest")
    return value


def _as_utc(value: datetime | None) -> datetime:
    candidate = value or datetime.now(UTC)
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=UTC)
    return candidate.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00").astimezone(
            UTC
        )
    except (TypeError, ValueError) as error:
        raise QuarantineError("approval timestamp is invalid") from error


def scan_secrets(data: bytes | str) -> None:
    """Reject high-confidence secret patterns before persistence or rendering."""

    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise SecretDetectedError("evidence is not valid UTF-8") from error
    elif isinstance(data, str):
        text = data
    else:
        raise TypeError("secret scanner accepts bytes or str")
    try:
        for character in text:
            reject_surrogates(character)
    except ModelInvariantError as error:
        raise SecretDetectedError(
            "lone Unicode surrogate is forbidden in evidence"
        ) from error
    if (
        _PEM_SECRET_RE.search(text)
        or _TOKEN_PREFIX_RE.search(text)
        or _ASSIGNMENT_SECRET_RE.search(text)
    ):
        raise SecretDetectedError("secret-like content is forbidden in source evidence")


@dataclass(frozen=True, slots=True)
class DeterministicSourceProof:
    """Opaque service proof for a deterministically parsed immutable Git snapshot."""

    snapshot_id: str
    content_digest: str
    mode: str
    parser_kind: str
    repository: str
    revision: str
    path: str
    _repository_root: Path = field(repr=False, compare=False)
    collector_profile: str = DETERMINISTIC_SOURCE_PROFILE
    _token: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _ensure_digest(self.content_digest, "deterministic source content_digest")
        if self.mode != "GIT_IMMUTABLE":
            raise QuarantineError("deterministic source proof requires immutable Git")
        if self.parser_kind not in {"markdown", "code", "json", "yaml"}:
            raise QuarantineError("source parser is not in the deterministic profile")


@dataclass(frozen=True, slots=True)
class EvidenceBinding:
    """A source span bound to immutable source bytes and a candidate atom."""

    binding_id: str
    candidate_id: str
    snapshot_id: str
    mode: str
    content_digest: str
    span_digest: str
    media_type: str
    captured_at: str
    access_policy: str = "repository-authorized"
    repository: str | None = None
    revision: str | None = None
    path: str | None = None
    symbol_or_heading: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    uri: str | None = None
    source: str | None = None
    verification_method: str | None = None
    source_bytes: bytes = field(default=b"", repr=False)

    def __post_init__(self) -> None:
        _ensure_digest(self.content_digest, "content_digest")
        _ensure_digest(self.span_digest, "span_digest")
        if self.mode not in {"CAS", "GIT_IMMUTABLE", "EXTERNAL_IMMUTABLE"}:
            raise QuarantineError("unknown evidence mode")
        if not self.candidate_id or not self.snapshot_id or not self.binding_id:
            raise QuarantineError("evidence binding identifiers must be non-empty")
        if self.mode == "GIT_IMMUTABLE":
            if not all(
                (self.repository, self.revision, self.path, self.symbol_or_heading)
            ):
                raise QuarantineError(
                    "Git evidence requires repository, revision, path, and locator"
                )
            if (
                self.start_line is None
                or self.end_line is None
                or self.start_line < 1
                or self.end_line < self.start_line
            ):
                raise QuarantineError("Git evidence locator lines are invalid")
        if self.mode == "EXTERNAL_IMMUTABLE" and not all(
            (self.uri, self.source, self.verification_method)
        ):
            raise QuarantineError("external evidence requires a complete locator")
        if (
            _ensure_digest("sha256:" + hashlib.sha256(self.source_bytes).hexdigest())
            != self.content_digest
        ):
            raise QuarantineError("evidence bytes do not match content_digest")


@dataclass(frozen=True, slots=True)
class CandidateAtom:
    """Source-derived candidate awaiting evidence and external approval.

    Public or generated ingestion starts at T3. A service-composed deterministic
    Git collector may issue a T2 candidate, but neither class is validated yet.
    """

    candidate_id: str
    atom_id: str
    kind: str
    statement: str
    modality: str
    scope: tuple[str, ...]
    source_snapshot_id: str
    start_line: int
    end_line: int
    symbol_or_heading: str
    compression_class: str = "P1_STRUCTURED"
    generated: bool = False
    trust_level: str = TrustLevel.T3
    status: str = "candidate"
    _quarantine_token: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.status != "candidate" or self.trust_level not in {
            TrustLevel.T0,
            TrustLevel.T1,
            TrustLevel.T2,
            TrustLevel.T3,
        }:
            raise QuarantineError(
                "new candidates must have a classified candidate state"
            )
        if self.generated and self.trust_level != TrustLevel.T3:
            raise QuarantineError("generated candidates must start at T3/candidate")
        if not self.candidate_id or not self.atom_id or not self.statement.strip():
            raise QuarantineError("candidate identity and statement are required")
        if not self.scope or self.start_line < 1 or self.end_line < self.start_line:
            raise QuarantineError("candidate source span is invalid")
        reject_surrogates(self.statement)


@dataclass(frozen=True, slots=True)
class HumanApproval:
    """An externally issued approval covering one exact candidate and evidence set."""

    approval_id: str
    candidate_id: str
    approver_id: str
    approved_at: str
    decision: str
    candidate_digest: str
    evidence_digests: tuple[str, ...]
    expires_at: str | None = None
    signature: str = ""
    issuer: str = "trusted-human-review"

    def __post_init__(self) -> None:
        if not self.approval_id or not self.candidate_id or not self.approver_id:
            raise QuarantineError("approval identifiers must be non-empty")
        if self.decision not in {"approve", "reject"}:
            raise QuarantineError("approval decision is invalid")
        _ensure_digest(self.candidate_digest, "candidate_digest")
        for digest in self.evidence_digests:
            _ensure_digest(digest, "evidence_digest")
        _parse_timestamp(self.approved_at)
        if self.expires_at is not None:
            _parse_timestamp(self.expires_at)

    @classmethod
    def untrusted(
        cls,
        candidate_id: str,
        *,
        evidence_digests: tuple[str, ...] = (),
    ) -> HumanApproval:
        """Build an intentionally unverifiable record for negative tests."""

        return cls(
            approval_id="untrusted-" + secrets.token_hex(8),
            candidate_id=candidate_id,
            approver_id="untrusted",
            approved_at=_timestamp(datetime.now(UTC)),
            decision="approve",
            candidate_digest="sha256:" + "0" * 64,
            evidence_digests=evidence_digests,
            signature="",
            issuer="untrusted-test-record",
        )

    def signing_payload(self) -> bytes:
        return canonical_json_bytes(
            {
                "approval_id": self.approval_id,
                "candidate_id": self.candidate_id,
                "approver_id": self.approver_id,
                "approved_at": self.approved_at,
                "decision": self.decision,
                "candidate_digest": self.candidate_digest,
                "evidence_digests": list(self.evidence_digests),
                "expires_at": self.expires_at,
                "issuer": self.issuer,
            }
        )


class TrustRoot:
    """Sealed, process-local trust root for M3 approval and publication proofs.

    This is a deliberately narrow research adapter.  It gives the service one fixed
    authority at construction time; callers cannot install an arbitrary allow-all
    verifier or choose a verifier per publication.
    """

    def __init__(
        self,
        approver_secrets: Mapping[str, bytes],
        *,
        issuer: str = "trusted-human-review",
        policy_version: str = TRUST_POLICY_VERSION,
    ) -> None:
        normalized = {str(key): bytes(value) for key, value in approver_secrets.items()}
        if not normalized or any(not value for value in normalized.values()):
            raise QuarantineError("trust root requires non-empty approver secrets")
        if not issuer or not policy_version:
            raise QuarantineError("trust root identifiers must be non-empty")
        reject_surrogates(issuer)
        reject_surrogates(policy_version)
        self._secrets = MappingProxyType(normalized)
        self.issuer = issuer
        self.policy_version = policy_version
        self._signer_id = min(normalized)
        self._permit_token = object()
        self._sealed = True

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("TrustRoot is immutable")
        object.__setattr__(self, name, value)

    @property
    def root_id(self) -> str:
        identity = {
            "issuer": self.issuer,
            "policy_version": self.policy_version,
            "signer_id": self._signer_id,
            "approvers": [
                {
                    "approver_id": approver_id,
                    "key_fingerprint": hashlib.sha256(secret).hexdigest(),
                }
                for approver_id, secret in sorted(self._secrets.items())
            ],
        }
        return (
            "trust-root-"
            + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()[:32]
        )

    def verifier(self) -> ApprovalVerifier:
        return _HmacApprovalVerifier(self._secrets, self.issuer, self)

    def _sign_payload(self, payload: Mapping[str, Any]) -> str:
        frozen = freeze_json(payload)
        if not isinstance(frozen, Mapping):
            raise QuarantineError("publication proof payload must be an object")
        message = canonical_json_bytes(thaw_json(frozen))
        signature = hmac.new(
            self._secrets[self._signer_id], message, hashlib.sha256
        ).hexdigest()
        return f"hmac-sha256:{self._signer_id}:{signature}"

    def _permit_capability(self) -> object:
        return self._permit_token

    def _sign_permit(self, payload: Mapping[str, Any], capability: object) -> str:
        if capability is not self._permit_token:
            raise QuarantineError("permit signing capability is invalid")
        return self._sign_payload(payload)

    def verify_payload(self, payload: Mapping[str, Any], signature: str) -> bool:
        if not isinstance(signature, str) or not signature.startswith("hmac-sha256:"):
            return False
        parts = signature.split(":", 2)
        if len(parts) != 3 or parts[1] != self._signer_id:
            return False
        try:
            expected = self._sign_payload(payload)
        except (QuarantineError, ValueError, TypeError):
            return False
        return hmac.compare_digest(signature, expected)


class _PublicationIssuer:
    """Process-local capability attached only to store-issued permits."""

    _deterministic_source_token: object
    _loader_token: object

    __slots__ = (
        "_deterministic_source_token",
        "_loader_token",
        "_sealed",
        "_token",
        "store_id",
    )

    def __init__(
        self, store_id: str, deterministic_source_token: object, loader_token: object
    ) -> None:
        object.__setattr__(self, "store_id", store_id)
        object.__setattr__(self, "_token", object())
        object.__setattr__(
            self, "_deterministic_source_token", deterministic_source_token
        )
        object.__setattr__(self, "_loader_token", loader_token)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("publication issuer is immutable")
        object.__setattr__(self, name, value)

    def owns_source_proof(self, proof: object) -> bool:
        return (
            type(proof) is DeterministicSourceProof
            and proof._token is self._deterministic_source_token
        )

    def owns_loader_attestation(self, attestation: object) -> bool:
        return getattr(attestation, "_capability", None) is self._loader_token


@dataclass(frozen=True, slots=True)
class PublicationPermit:
    """Signed final-publication proof issued only by a quarantine store."""

    payload: Mapping[str, Any]
    signature: str
    source_bytes: tuple[bytes, ...] = field(default=(), repr=False, compare=False)
    source_proofs: tuple[DeterministicSourceProof, ...] = field(
        default=(), repr=False, compare=False
    )
    loader_attestation: Any | None = field(default=None, repr=False, compare=False)
    issuer_capability: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            frozen = freeze_json(self.payload)
        except (ModelInvariantError, TypeError, ValueError) as error:
            raise QuarantineError(
                "publication proof payload is not JSON-safe"
            ) from error
        if not isinstance(frozen, Mapping):
            raise QuarantineError("publication proof payload must be an object")
        if not isinstance(self.signature, str) or not self.signature:
            raise QuarantineError("publication proof signature is required")
        if any(not isinstance(item, bytes) for item in self.source_bytes):
            raise QuarantineError("publication proof source subjects must be bytes")
        if any(
            type(item) is not DeterministicSourceProof for item in self.source_proofs
        ):
            raise QuarantineError("publication proof source resolvers are invalid")
        object.__setattr__(self, "payload", frozen)

    def verify(self, trust_root: TrustRoot) -> bool:
        if type(trust_root) is not TrustRoot:
            return False
        return trust_root.verify_payload(thaw_json(self.payload), self.signature)


class ApprovalAuthority:
    """Injectable local verifier for auditable human approval records.

    The secret map is intentionally supplied by the caller; candidates cannot create a
    trusted authority implicitly.  This is a test/research trust adapter, not a claim of
    production signature security.
    """

    def __init__(
        self,
        approver_secrets: Mapping[str, bytes],
        *,
        issuer: str = "trusted-human-review",
    ) -> None:
        self._trust_root = TrustRoot(approver_secrets, issuer=issuer)
        self._secrets = MappingProxyType(dict(self._trust_root._secrets))
        self.issuer = self._trust_root.issuer

    def issue(
        self,
        candidate: CandidateAtom,
        bindings: Iterable[EvidenceBinding],
        approver_id: str,
        *,
        approved_at: datetime | None = None,
        expires_at: datetime | None = None,
        approval_id: str | None = None,
    ) -> HumanApproval:
        if approver_id not in self._secrets:
            raise QuarantineError("approver is not trusted")
        binding_tuple = tuple(bindings)
        candidate_digest = candidate_digest_for(candidate)
        approval = HumanApproval(
            approval_id=approval_id or "approval-" + secrets.token_hex(12),
            candidate_id=candidate.candidate_id,
            approver_id=approver_id,
            approved_at=_timestamp(_as_utc(approved_at)),
            decision="approve",
            candidate_digest=candidate_digest,
            evidence_digests=tuple(
                binding_digest_for(binding) for binding in binding_tuple
            ),
            expires_at=_timestamp(_as_utc(expires_at))
            if expires_at is not None
            else None,
            signature="",
            issuer=self.issuer,
        )
        signature = hmac.new(
            self._secrets[approver_id], approval.signing_payload(), hashlib.sha256
        ).hexdigest()
        return replace(approval, signature=f"hmac-sha256:{signature}")

    def verifier(self) -> ApprovalVerifier:
        """Return a verify-only trust adapter suitable for a quarantine store."""

        return self._trust_root.verifier()

    def trust_root(self) -> TrustRoot:
        """Return the immutable service trust root for explicit composition."""

        return self._trust_root


class ApprovalVerifier(Protocol):
    def verify(self, approval: HumanApproval) -> bool: ...


class _HmacApprovalVerifier:
    def __init__(
        self,
        approver_secrets: Mapping[str, bytes],
        issuer: str,
        trust_root: TrustRoot | None = None,
    ) -> None:
        self.__secrets = dict(approver_secrets)
        self.__issuer = issuer
        self.__trust_root = trust_root

    @property
    def trust_root(self) -> TrustRoot | None:
        return self.__trust_root

    def verify(self, approval: HumanApproval) -> bool:
        secret = self.__secrets.get(approval.approver_id)
        if (
            secret is None
            or approval.issuer != self.__issuer
            or not approval.signature.startswith("hmac-sha256:")
        ):
            return False
        expected = hmac.new(
            secret, approval.signing_payload(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(
            approval.signature.removeprefix("hmac-sha256:"), expected
        )


class _DenyAllApprovalVerifier:
    def verify(self, approval: HumanApproval) -> bool:
        del approval
        return False


@dataclass(frozen=True, slots=True)
class ValidatedAtom:
    """A candidate after trusted evidence and human approval checks."""

    candidate_id: str
    atom_id: str
    kind: str
    statement: str
    modality: str
    scope: tuple[str, ...]
    source_snapshot_id: str
    start_line: int
    end_line: int
    symbol_or_heading: str
    compression_class: str
    evidence_bindings: tuple[EvidenceBinding, ...]
    approval: HumanApproval
    source_trust_level: str = TrustLevel.T2
    generated: bool = False
    trust_level: str = TrustLevel.T1
    status: str = "validated"

    def __post_init__(self) -> None:
        if self.status != "validated" or self.trust_level not in {
            TrustLevel.T0,
            TrustLevel.T1,
            TrustLevel.T2,
        }:
            raise QuarantineError("validated atom has invalid trust state")
        if not self.evidence_bindings:
            raise QuarantineError("validated atom requires evidence bindings")


def candidate_digest_for(candidate: CandidateAtom) -> str:
    payload = {
        "candidate_id": candidate.candidate_id,
        "atom_id": candidate.atom_id,
        "kind": candidate.kind,
        "statement": candidate.statement,
        "modality": candidate.modality,
        "scope": list(candidate.scope),
        "source_snapshot_id": candidate.source_snapshot_id,
        "start_line": candidate.start_line,
        "end_line": candidate.end_line,
        "symbol_or_heading": candidate.symbol_or_heading,
        "compression_class": candidate.compression_class,
        "generated": candidate.generated,
        "trust_level": candidate.trust_level,
        "status": candidate.status,
    }
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def binding_digest_for(binding: EvidenceBinding) -> str:
    payload = {
        "binding_id": binding.binding_id,
        "candidate_id": binding.candidate_id,
        "snapshot_id": binding.snapshot_id,
        "mode": binding.mode,
        "content_digest": binding.content_digest,
        "span_digest": binding.span_digest,
        "media_type": binding.media_type,
        "captured_at": binding.captured_at,
        "access_policy": binding.access_policy,
        "repository": binding.repository,
        "revision": binding.revision,
        "path": binding.path,
        "symbol_or_heading": binding.symbol_or_heading,
        "start_line": binding.start_line,
        "end_line": binding.end_line,
        "uri": binding.uri,
        "source": binding.source,
        "verification_method": binding.verification_method,
    }
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class QuarantineStore:
    """Append-only in-memory quarantine state with default-deny promotion."""

    def __init__(
        self,
        approval_verifier: ApprovalVerifier | None = None,
        *,
        trust_root: TrustRoot | None = None,
    ) -> None:
        if (
            approval_verifier is not None
            and type(approval_verifier) is not _HmacApprovalVerifier
        ):
            raise TypeError("quarantine requires the project trust-root verifier")
        if trust_root is not None and type(trust_root) is not TrustRoot:
            raise TypeError("trust_root must be a TrustRoot")
        verifier_root = (
            approval_verifier.trust_root
            if type(approval_verifier) is _HmacApprovalVerifier
            else None
        )
        if (
            trust_root is not None
            and verifier_root is not None
            and trust_root is not verifier_root
        ):
            raise QuarantineError("approval verifier and trust root disagree")
        self._trust_root = trust_root or verifier_root
        self._approval_verifier = (
            self._trust_root.verifier()
            if self._trust_root is not None
            else _DenyAllApprovalVerifier()
        )
        self._snapshots: dict[str, Any] = {}
        self._candidates: dict[str, CandidateAtom] = {}
        self._bindings: dict[str, tuple[EvidenceBinding, ...]] = {}
        self._promoted: dict[str, ValidatedAtom] = {}
        self._snapshot_token = object()
        self._candidate_token = object()
        self._deterministic_source_token = object()
        self._loader_token = object()
        self._loader_store_id = "quarantine-" + secrets.token_hex(16)
        self._publication_issuer = _PublicationIssuer(
            self._loader_store_id,
            self._deterministic_source_token,
            self._loader_token,
        )
        self._permit_token = object()
        self._lock = RLock()
        self._composition_sealed = True

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_composition_sealed", False) and name in {
            "_trust_root",
            "_approval_verifier",
            "_snapshot_token",
            "_candidate_token",
            "_deterministic_source_token",
            "_loader_token",
            "_loader_store_id",
            "_publication_issuer",
            "_permit_token",
        }:
            raise AttributeError("QuarantineStore trust composition is immutable")
        object.__setattr__(self, name, value)

    def _has_trust_root(self) -> bool:
        return self._trust_root is not None

    def _bind_deterministic_collector(self, trust_root: TrustRoot) -> object:
        """Bind the deterministic collector to this service composition root."""

        if type(trust_root) is not TrustRoot or trust_root is not self._trust_root:
            raise QuarantineError(
                "deterministic collector requires the configured trust root"
            )
        return self._deterministic_source_token

    def register_snapshot(self, snapshot: Any) -> Any:
        with self._lock:
            from contractcapsule.build.ingest import SourceSnapshot

            if type(snapshot) is not SourceSnapshot:
                raise QuarantineError("snapshot must be the ingestion boundary type")
            if getattr(snapshot, "_quarantine_token", None) is not self._snapshot_token:
                raise QuarantineError(
                    "snapshot was not created by the ingestion boundary"
                )
            proof = getattr(snapshot, "_source_proof", None)
            if proof is not None and not self.has_deterministic_source_proof(snapshot):
                raise QuarantineError(
                    "deterministic source snapshot lacks a trusted parser proof"
                )
            existing = self._snapshots.get(snapshot.snapshot_id)
            if existing is not None:
                trust_fields = (
                    "content_digest",
                    "mode",
                    "media_type",
                    "principal_id",
                    "relative_path",
                    "repository",
                    "revision",
                    "uri",
                    "source",
                    "verification_method",
                    "access_policy",
                    "parser_kind",
                    "generated",
                )
                if any(
                    getattr(existing, field_name, None)
                    != getattr(snapshot, field_name, None)
                    for field_name in trust_fields
                ):
                    raise QuarantineError("snapshot identity collision")
                has_bound_candidates = any(
                    candidate.source_snapshot_id == snapshot.snapshot_id
                    for candidate in self._candidates.values()
                )
                if has_bound_candidates and (
                    existing.path != snapshot.path
                    or existing.repository_root != snapshot.repository_root
                    or existing.captured_at != snapshot.captured_at
                ):
                    raise QuarantineError(
                        "bound snapshot cannot be replaced by a new capture"
                    )
            self._snapshots[snapshot.snapshot_id] = snapshot
            return snapshot

    def register_candidate(self, candidate: CandidateAtom) -> None:
        with self._lock:
            if type(candidate) is not CandidateAtom:
                raise QuarantineError(
                    "candidate must be the deterministic extractor type"
                )
            if candidate._quarantine_token is not self._candidate_token:
                raise QuarantineError(
                    "candidate was not created by the deterministic extractor"
                )
            snapshot = self._snapshots.get(candidate.source_snapshot_id)
            if snapshot is None:
                raise QuarantineError("candidate references an unknown snapshot")
            expected_id = (
                "candidate-"
                + hashlib.sha256(
                    canonical_json_bytes(
                        {
                            "snapshot_id": snapshot.snapshot_id,
                            "statement": candidate.statement,
                            "kind": candidate.kind,
                            "start_line": candidate.start_line,
                            "end_line": candidate.end_line,
                            "symbol_or_heading": candidate.symbol_or_heading,
                        }
                    )
                ).hexdigest()[:32]
            )
            if candidate.candidate_id != expected_id:
                raise QuarantineError("candidate identity is not deterministic")
            if candidate.atom_id != "atom-" + expected_id.removeprefix("candidate-"):
                raise QuarantineError("candidate atom identity is not deterministic")
            if candidate.scope != (f"path:{snapshot.relative_path}",):
                raise QuarantineError("candidate scope is not source-bound")
            expected_trust = (
                TrustLevel.T2
                if self.has_deterministic_source_proof(snapshot)
                and not snapshot.generated
                else TrustLevel.T3
            )
            if (
                candidate.generated != snapshot.generated
                or candidate.trust_level != expected_trust
            ):
                raise QuarantineError("candidate trust classification is inconsistent")
            existing = self._candidates.get(candidate.candidate_id)
            if existing is not None and existing != candidate:
                raise QuarantineError("candidate identity collision")
            self._candidates[candidate.candidate_id] = candidate

    def is_registered_snapshot(self, snapshot: Any) -> bool:
        with self._lock:
            existing = self._snapshots.get(snapshot.snapshot_id)
            return (
                existing is not None
                and existing.content_digest == snapshot.content_digest
            )

    def _snapshot_capability(self) -> object:
        return self._snapshot_token

    def _candidate_capability(self) -> object:
        return self._candidate_token

    def _loader_capability(self) -> object:
        return self._loader_token

    @property
    def _loader_identity(self) -> str:
        return self._loader_store_id

    def _issue_deterministic_source_proof(
        self, snapshot: Any, collector_capability: object | None = None
    ) -> DeterministicSourceProof | None:
        from contractcapsule.build.ingest import SourceSnapshot

        if type(snapshot) is not SourceSnapshot:
            raise QuarantineError("deterministic proof requires an ingestion snapshot")
        if collector_capability is not self._deterministic_source_token:
            raise QuarantineError("deterministic collector capability is required")
        # A deterministic T2 classification is only available through the
        # explicitly composed collector boundary. Public ingestion never receives
        # this capability merely because a caller says ``generated=False``.
        if self._trust_root is None:
            return None
        if (
            snapshot.mode != "GIT_IMMUTABLE"
            or snapshot.generated
            or snapshot.parser_kind not in {"markdown", "code", "json", "yaml"}
            or not snapshot.repository
            or not snapshot.revision
            or not snapshot.relative_path
            or snapshot.repository_root is None
        ):
            if snapshot.mode == "GIT_IMMUTABLE" and not snapshot.generated:
                raise QuarantineError("verified repository root is required")
            return None
        if getattr(snapshot, "_quarantine_token", None) is not self._snapshot_token:
            raise QuarantineError("snapshot was not issued by this quarantine")
        snapshot.assert_current()
        return DeterministicSourceProof(
            snapshot_id=snapshot.snapshot_id,
            content_digest=snapshot.content_digest,
            mode=snapshot.mode,
            parser_kind=snapshot.parser_kind,
            repository=snapshot.repository,
            revision=snapshot.revision,
            path=snapshot.relative_path,
            _repository_root=snapshot.repository_root,
            _token=self._deterministic_source_token,
        )

    def has_deterministic_source_proof(self, snapshot: Any) -> bool:
        proof = getattr(snapshot, "_source_proof", None)
        return (
            isinstance(proof, DeterministicSourceProof)
            and proof._token is self._deterministic_source_token
            and proof.collector_profile == DETERMINISTIC_SOURCE_PROFILE
            and proof.snapshot_id == snapshot.snapshot_id
            and proof.content_digest == snapshot.content_digest
            and proof.mode == snapshot.mode == "GIT_IMMUTABLE"
            and proof.parser_kind == snapshot.parser_kind
            and proof.repository == snapshot.repository
            and proof.revision == snapshot.revision
            and proof.path == snapshot.relative_path
            and proof._repository_root == snapshot.repository_root
            and not snapshot.generated
        )

    def register_binding(self, binding: EvidenceBinding) -> None:
        with self._lock:
            if type(binding) is not EvidenceBinding:
                raise QuarantineError("evidence binding must be the quarantine type")
            candidate = self._candidates.get(binding.candidate_id)
            if candidate is None:
                raise QuarantineError("evidence binding references unknown candidate")
            if candidate.source_snapshot_id != binding.snapshot_id:
                raise QuarantineError("evidence binding snapshot mismatch")
            current = list(self._bindings.get(binding.candidate_id, ()))
            if binding not in current:
                current.append(binding)
            self._bindings[binding.candidate_id] = tuple(current)

    def pending(self, candidate_id: str) -> bool:
        with self._lock:
            return (
                candidate_id in self._candidates and candidate_id not in self._promoted
            )

    def bindings_for(self, candidate_id: str) -> tuple[EvidenceBinding, ...]:
        with self._lock:
            return self._bindings.get(candidate_id, ())

    def candidate(self, candidate_id: str) -> CandidateAtom:
        with self._lock:
            try:
                return self._candidates[candidate_id]
            except KeyError as error:
                raise QuarantineError("candidate is not in quarantine") from error

    @staticmethod
    def _verify_binding_locator(
        candidate: CandidateAtom, snapshot: Any, binding: EvidenceBinding
    ) -> None:
        if binding.mode == "GIT_IMMUTABLE":
            if (
                binding.repository != snapshot.repository
                or binding.revision != snapshot.revision
            ):
                raise QuarantineError("evidence binding immutable Git locator mismatch")
        elif binding.mode == "EXTERNAL_IMMUTABLE" and binding.uri != snapshot.uri:
            raise QuarantineError("evidence binding external locator mismatch")

    @staticmethod
    def _verify_binding_identity(
        candidate: CandidateAtom, snapshot: Any, binding: EvidenceBinding
    ) -> None:
        if binding.candidate_id != candidate.candidate_id:
            raise QuarantineError("evidence binding candidate mismatch")
        if binding.snapshot_id != snapshot.snapshot_id:
            raise QuarantineError("evidence binding snapshot mismatch")
        if binding.mode != snapshot.mode:
            raise QuarantineError("evidence binding mode mismatch")
        if binding.content_digest != snapshot.content_digest:
            raise QuarantineError("evidence binding content digest mismatch")
        if binding.path != snapshot.relative_path:
            raise QuarantineError("evidence binding path mismatch")
        if binding.symbol_or_heading != candidate.symbol_or_heading:
            raise QuarantineError("evidence binding symbol mismatch")
        if (
            binding.start_line != candidate.start_line
            or binding.end_line != candidate.end_line
        ):
            raise QuarantineError("evidence binding line span mismatch")
        QuarantineStore._verify_binding_locator(candidate, snapshot, binding)

    @staticmethod
    def _verify_binding_bytes(
        candidate: CandidateAtom, snapshot: Any, binding: EvidenceBinding
    ) -> None:
        if binding.source_bytes != snapshot.content:
            raise QuarantineError("evidence binding bytes mismatch")
        actual_span = snapshot.line_span(candidate.start_line, candidate.end_line)
        span_text = actual_span.decode("utf-8", errors="strict").strip()
        if span_text.startswith("#"):
            span_text = span_text.lstrip("#").strip().rstrip("#").strip()
        if span_text != candidate.statement.strip():
            raise QuarantineError("evidence binding statement mismatch")
        actual_digest = "sha256:" + hashlib.sha256(actual_span).hexdigest()
        if actual_digest != binding.span_digest:
            raise QuarantineError("evidence binding span digest mismatch")
        scan_secrets(binding.source_bytes)

    @classmethod
    def _verify_binding(
        cls, candidate: CandidateAtom, snapshot: Any, binding: EvidenceBinding
    ) -> None:
        cls._verify_binding_identity(candidate, snapshot, binding)
        cls._verify_binding_bytes(candidate, snapshot, binding)

    def _promotion_inputs(
        self, candidate_id: str
    ) -> tuple[CandidateAtom, tuple[EvidenceBinding, ...], Any]:
        candidate = self.candidate(candidate_id)
        if candidate_id in self._promoted:
            raise QuarantineError("candidate has already been promoted")
        bindings = self._bindings.get(candidate_id, ())
        if not bindings:
            raise QuarantineError("evidence binding is required before promotion")
        snapshot = self._snapshots.get(candidate.source_snapshot_id)
        if snapshot is None:
            raise QuarantineError("source snapshot is unavailable")
        return candidate, bindings, snapshot

    @staticmethod
    def _verify_snapshot(snapshot: Any) -> None:
        try:
            snapshot.assert_current()
        except Exception as error:
            raise QuarantineError("source drift detected") from error
        scan_secrets(snapshot.content)

    @staticmethod
    def _verify_approval_identity(
        candidate_id: str,
        candidate: CandidateAtom,
        bindings: tuple[EvidenceBinding, ...],
        approval: HumanApproval,
    ) -> None:
        if approval.candidate_id != candidate_id:
            raise QuarantineError("approval candidate mismatch")
        if approval.decision != "approve":
            raise QuarantineError("approval did not approve candidate")
        if approval.candidate_digest != candidate_digest_for(candidate):
            raise QuarantineError("approval candidate digest mismatch")
        expected_evidence = tuple(binding_digest_for(binding) for binding in bindings)
        if approval.evidence_digests != expected_evidence:
            raise QuarantineError("approval evidence digest mismatch")

    @staticmethod
    def _verify_approval_time(snapshot: Any, approval: HumanApproval) -> None:
        approved_at = _parse_timestamp(approval.approved_at)
        now = datetime.now(UTC)
        if approved_at > now:
            raise QuarantineError("approval timestamp is in the future")
        if (
            approval.expires_at is not None
            and _parse_timestamp(approval.expires_at) <= now
        ):
            raise QuarantineError("approval is expired")
        if (
            approval.expires_at is not None
            and _parse_timestamp(approval.expires_at) <= approved_at
        ):
            raise QuarantineError("approval expiry precedes approval time")
        if approved_at < _parse_timestamp(snapshot.captured_at):
            raise QuarantineError("approval predates the bound source snapshot")

    def _verify_approval_trust(self, snapshot: Any, approval: HumanApproval) -> None:
        if approval.approver_id == snapshot.principal_id:
            raise QuarantineError(
                "approval must come from an external trusted principal"
            )
        if not self._approval_verifier.verify(approval):
            raise QuarantineError("approval is not from a trusted authority")

    def _verify_approval(
        self,
        candidate_id: str,
        candidate: CandidateAtom,
        bindings: tuple[EvidenceBinding, ...],
        snapshot: Any,
        approval: HumanApproval,
    ) -> None:
        self._verify_approval_identity(candidate_id, candidate, bindings, approval)
        self._verify_approval_time(snapshot, approval)
        self._verify_approval_trust(snapshot, approval)

    def promote(self, candidate_id: str, approval: HumanApproval) -> ValidatedAtom:
        with self._lock:
            if type(approval) is not HumanApproval:
                raise QuarantineError("a human approval record is required")
            candidate, bindings, snapshot = self._promotion_inputs(candidate_id)
            self._verify_snapshot(snapshot)
            for binding in bindings:
                self._verify_binding(candidate, snapshot, binding)
            self._verify_approval(candidate_id, candidate, bindings, snapshot, approval)
            validated = ValidatedAtom(
                candidate_id=candidate.candidate_id,
                atom_id=candidate.atom_id,
                kind=candidate.kind,
                statement=candidate.statement,
                modality=candidate.modality,
                scope=candidate.scope,
                source_snapshot_id=candidate.source_snapshot_id,
                start_line=candidate.start_line,
                end_line=candidate.end_line,
                symbol_or_heading=candidate.symbol_or_heading,
                compression_class=candidate.compression_class,
                evidence_bindings=bindings,
                approval=approval,
                source_trust_level=candidate.trust_level,
                generated=candidate.generated,
            )
            self._promoted[candidate_id] = validated
            return validated

    def verify_validated(self, atom: ValidatedAtom) -> None:
        """Recheck that an exact validated value was emitted by this store."""

        with self._lock:
            if type(atom) is not ValidatedAtom:
                raise QuarantineError("validated atom must be the quarantine type")
            promoted = self._promoted.get(atom.candidate_id)
            if promoted is None or promoted != atom:
                raise QuarantineError(
                    "validated atom was not promoted by this quarantine"
                )
            snapshot = self._snapshots.get(atom.source_snapshot_id)
            if snapshot is None:
                raise QuarantineError("validated atom source snapshot is unavailable")
            try:
                snapshot.assert_current()
            except Exception as error:
                raise QuarantineError("validated atom source drift detected") from error
            scan_secrets(atom.statement)
            candidate = self._candidates.get(atom.candidate_id)
            if candidate is None:
                raise QuarantineError("validated atom candidate is unavailable")
            if (
                candidate.trust_level == TrustLevel.T2
                and not self.has_deterministic_source_proof(snapshot)
            ):
                raise QuarantineError(
                    "validated atom deterministic source proof is unavailable"
                )
            for binding in atom.evidence_bindings:
                self._verify_binding(candidate, snapshot, binding)
            if atom.approval.expires_at is not None and _parse_timestamp(
                atom.approval.expires_at
            ) <= datetime.now(UTC):
                raise QuarantineError("validated atom approval is expired")
            if not self._approval_verifier.verify(atom.approval):
                raise QuarantineError("validated atom approval is no longer trusted")

    @staticmethod
    def _approval_wire(approval: HumanApproval) -> dict[str, Any]:
        return {
            "approval_id": approval.approval_id,
            "candidate_id": approval.candidate_id,
            "approver_id": approval.approver_id,
            "approved_at": approval.approved_at,
            "decision": approval.decision,
            "candidate_digest": approval.candidate_digest,
            "evidence_digests": list(approval.evidence_digests),
            "expires_at": approval.expires_at,
            "signature": approval.signature,
            "issuer": approval.issuer,
        }

    @staticmethod
    def _binding_wire(binding: EvidenceBinding) -> dict[str, Any]:
        return {
            "binding_id": binding.binding_id,
            "candidate_id": binding.candidate_id,
            "snapshot_id": binding.snapshot_id,
            "mode": binding.mode,
            "content_digest": binding.content_digest,
            "span_digest": binding.span_digest,
            "media_type": binding.media_type,
            "captured_at": binding.captured_at,
            "access_policy": binding.access_policy,
            "repository": binding.repository,
            "revision": binding.revision,
            "path": binding.path,
            "symbol_or_heading": binding.symbol_or_heading,
            "start_line": binding.start_line,
            "end_line": binding.end_line,
            "uri": binding.uri,
            "source": binding.source,
            "verification_method": binding.verification_method,
        }

    @staticmethod
    def _candidate_wire(candidate: CandidateAtom) -> dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "atom_id": candidate.atom_id,
            "kind": candidate.kind,
            "statement": candidate.statement,
            "modality": candidate.modality,
            "scope": list(candidate.scope),
            "source_snapshot_id": candidate.source_snapshot_id,
            "start_line": candidate.start_line,
            "end_line": candidate.end_line,
            "symbol_or_heading": candidate.symbol_or_heading,
            "compression_class": candidate.compression_class,
            "generated": candidate.generated,
            "trust_level": candidate.trust_level,
            "status": candidate.status,
        }

    @staticmethod
    def _source_proof_wire(snapshot: Any) -> dict[str, Any] | None:
        proof = getattr(snapshot, "_source_proof", None)
        if not isinstance(proof, DeterministicSourceProof):
            return None
        return {
            "snapshot_id": proof.snapshot_id,
            "content_digest": proof.content_digest,
            "mode": proof.mode,
            "parser_kind": proof.parser_kind,
            "repository": proof.repository,
            "revision": proof.revision,
            "path": proof.path,
            "collector_profile": proof.collector_profile,
        }

    def _permit_atom_entry(
        self, atom: ValidatedAtom
    ) -> tuple[
        dict[str, Any],
        tuple[EvidenceBinding, ...],
        DeterministicSourceProof | None,
    ]:
        if type(atom) is not ValidatedAtom:
            raise QuarantineError("publication permit accepts validated atoms only")
        self.verify_validated(atom)
        candidate = self.candidate(atom.candidate_id)
        snapshot = self._snapshots.get(atom.source_snapshot_id)
        if snapshot is None:
            raise QuarantineError("validated atom snapshot is unavailable")
        bindings = tuple(atom.evidence_bindings)
        entry = self._candidate_wire(candidate)
        entry.update(
            {
                "candidate_digest": candidate_digest_for(candidate),
                "snapshot_id": atom.source_snapshot_id,
                "snapshot_principal_id": snapshot.principal_id,
                "snapshot_captured_at": snapshot.captured_at,
                "source_trust_level": atom.source_trust_level,
                "validated_trust_level": atom.trust_level,
                "validated_status": atom.status,
                "source_proof": self._source_proof_wire(snapshot),
                "approval": self._approval_wire(atom.approval),
                "bindings": [self._binding_wire(item) for item in bindings],
            }
        )
        proof = getattr(snapshot, "_source_proof", None)
        return (
            entry,
            bindings,
            proof if type(proof) is DeterministicSourceProof else None,
        )

    @staticmethod
    def _permit_subjects(
        bindings: Iterable[EvidenceBinding],
        seen: set[tuple[str, str]],
        subjects: list[dict[str, Any]],
        source_bytes: list[bytes],
    ) -> None:
        for binding in bindings:
            key = (binding.binding_id, binding.content_digest)
            if key in seen:
                continue
            seen.add(key)
            subjects.append(
                {
                    "binding_id": binding.binding_id,
                    "mode": binding.mode,
                    "content_digest": binding.content_digest,
                    "media_type": binding.media_type,
                    "snapshot_id": binding.snapshot_id,
                }
            )
            source_bytes.append(bytes(binding.source_bytes))

    @staticmethod
    def _permit_target(capsule: Any) -> dict[str, Any]:
        scope = capsule.control_manifest.scope
        return {
            "authority": capsule.control_manifest.authority,
            "scope": {
                "repositories": list(scope.repositories),
                "paths": list(scope.paths),
                "environments": list(scope.environments),
            },
        }

    @staticmethod
    def _validate_loader_attestation(
        attestation: Any, digest: str, expected_type: type[Any]
    ) -> None:
        if type(attestation) is not expected_type:
            raise QuarantineError("loader attestation is required")
        if not attestation.verify(None):
            raise QuarantineError("loader attestation signature is invalid")
        if attestation.capsule_digest != digest:
            raise QuarantineError("loader attestation capsule digest mismatch")

    def _validate_loader_issuer(self, attestation: Any) -> None:
        if (
            attestation._capability is not self._loader_token
            or attestation.store_id != self._loader_store_id
        ):
            raise QuarantineError(
                "loader attestation was not issued by this quarantine"
            )

    def issue_publication_permit(
        self,
        capsule: Any,
        validated_atoms: Iterable[ValidatedAtom],
        principal: Any,
        *,
        loader_attestation: Any | None = None,
    ) -> PublicationPermit:
        """Issue a signed, one-shot-at-a-time publication attestation.

        The permit is intentionally detached from the Capsule.  It binds the exact
        canonical digest, publisher, candidate records, evidence records and source
        subject digests, then is rechecked by Registry immediately before persistence.
        """

        if self._trust_root is None:
            raise QuarantineError("a configured trust root is required for publication")
        from contractcapsule.models import Capsule, Principal
        from contractcapsule.models.canonical import canonical_digest

        if type(capsule) is not Capsule or type(principal) is not Principal:
            raise TypeError("capsule and principal types are required")
        if capsule.control_manifest.lifecycle != "PUBLISHED":
            raise QuarantineError("publication permit requires PUBLISHED lifecycle")
        digest = canonical_digest(capsule)
        if digest != capsule.control_manifest.content_digest:
            raise QuarantineError("publication permit capsule digest is invalid")
        try:
            from contractcapsule.build.publish import LoaderAttestation
        except (ImportError, AttributeError) as error:
            raise QuarantineError("loader attestation type is unavailable") from error
        self._validate_loader_attestation(loader_attestation, digest, LoaderAttestation)
        self._validate_loader_issuer(loader_attestation)
        atoms = tuple(validated_atoms)
        if not atoms:
            raise QuarantineError("publication permit requires validated atoms")
        if (
            loader_attestation is None
        ):  # Defensive guard; helper validation is fail-closed.
            raise QuarantineError("loader attestation is required")
        entries: list[dict[str, Any]] = []
        source_bytes: list[bytes] = []
        source_proofs: list[DeterministicSourceProof] = []
        subjects: list[dict[str, Any]] = []
        seen_subjects: set[tuple[str, str]] = set()
        for atom in atoms:
            entry, bindings, source_proof = self._permit_atom_entry(atom)
            entries.append(entry)
            self._permit_subjects(bindings, seen_subjects, subjects, source_bytes)
            if source_proof is not None and source_proof not in source_proofs:
                if not self._publication_issuer.owns_source_proof(source_proof):
                    raise QuarantineError(
                        "deterministic source proof is outside the publication issuer"
                    )
                source_proofs.append(source_proof)
        target = self._permit_target(capsule)
        payload = {
            "policy_version": self._trust_root.policy_version,
            "trust_root_id": self._trust_root.root_id,
            "capsule_id": capsule.control_manifest.capsule_id,
            "version": capsule.control_manifest.version,
            "capsule_digest": digest,
            "principal_id": principal.principal_id,
            **target,
            "scanner_version": SECRET_SCANNER_VERSION,
            "loader_attestation": loader_attestation.wire(),
            "atoms": entries,
            "source_subjects": subjects,
        }
        return PublicationPermit(
            payload=payload,
            signature=self._trust_root._sign_permit(
                payload, self._trust_root._permit_capability()
            ),
            source_bytes=tuple(source_bytes),
            source_proofs=tuple(source_proofs),
            loader_attestation=loader_attestation,
            issuer_capability=self._publication_issuer,
        )


_DEFAULT_STORE = QuarantineStore()


def default_store() -> QuarantineStore:
    return _DEFAULT_STORE


def configure_default_store(store: QuarantineStore) -> None:
    """Reject public replacement of the process default trust boundary.

    Production composition passes an explicit ``QuarantineStore`` to ingestion and
    build requests.  The process-wide fallback remains permanently deny-all so an
    arbitrary first caller cannot install its own approval root.
    """

    if not isinstance(store, QuarantineStore):
        raise TypeError("default quarantine must be a QuarantineStore")
    del store
    raise QuarantineError(
        "default quarantine is immutable deny-all; use explicit trusted startup composition"
    )


def promote(candidate_id: str, approval: HumanApproval) -> ValidatedAtom:
    """Promote through the process-wide default quarantine store."""

    return _DEFAULT_STORE.promote(candidate_id, approval)
