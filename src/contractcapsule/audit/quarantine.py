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
from threading import RLock
from typing import Any, Protocol

from contractcapsule.models.base import ModelInvariantError, reject_surrogates
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
    """Untrusted source-derived atom.  Candidates are always T3/candidate."""

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
        self._secrets = {
            str(key): bytes(value) for key, value in approver_secrets.items()
        }
        self.issuer = issuer

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

        return _HmacApprovalVerifier(self._secrets, self.issuer)


class ApprovalVerifier(Protocol):
    def verify(self, approval: HumanApproval) -> bool: ...


class _HmacApprovalVerifier:
    def __init__(self, approver_secrets: Mapping[str, bytes], issuer: str) -> None:
        self.__secrets = dict(approver_secrets)
        self.__issuer = issuer

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

    def __init__(self, approval_verifier: ApprovalVerifier | None = None) -> None:
        self._approval_verifier = approval_verifier or _DenyAllApprovalVerifier()
        self._snapshots: dict[str, Any] = {}
        self._candidates: dict[str, CandidateAtom] = {}
        self._bindings: dict[str, tuple[EvidenceBinding, ...]] = {}
        self._promoted: dict[str, ValidatedAtom] = {}
        self._snapshot_token = object()
        self._candidate_token = object()
        self._lock = RLock()

    def register_snapshot(self, snapshot: Any) -> None:
        with self._lock:
            if getattr(snapshot, "_quarantine_token", None) is not self._snapshot_token:
                raise QuarantineError(
                    "snapshot was not created by the ingestion boundary"
                )
            existing = self._snapshots.get(snapshot.snapshot_id)
            if (
                existing is not None
                and existing.content_digest != snapshot.content_digest
            ):
                raise QuarantineError("snapshot identity collision")
            self._snapshots[snapshot.snapshot_id] = snapshot

    def register_candidate(self, candidate: CandidateAtom) -> None:
        with self._lock:
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
            expected_trust = TrustLevel.T3 if snapshot.generated else TrustLevel.T2
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

    def snapshot_token(self) -> object:
        return self._snapshot_token

    def candidate_token(self) -> object:
        return self._candidate_token

    def register_binding(self, binding: EvidenceBinding) -> None:
        with self._lock:
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
            if not isinstance(approval, HumanApproval):
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
            )
            self._promoted[candidate_id] = validated
            return validated

    def verify_validated(self, atom: ValidatedAtom) -> None:
        """Recheck that an exact validated value was emitted by this store."""

        with self._lock:
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
            for binding in atom.evidence_bindings:
                self._verify_binding(candidate, snapshot, binding)
            if atom.approval.expires_at is not None and _parse_timestamp(
                atom.approval.expires_at
            ) <= datetime.now(UTC):
                raise QuarantineError("validated atom approval is expired")
            if not self._approval_verifier.verify(atom.approval):
                raise QuarantineError("validated atom approval is no longer trusted")


_DEFAULT_STORE = QuarantineStore()


def default_store() -> QuarantineStore:
    return _DEFAULT_STORE


def configure_default_store(store: QuarantineStore) -> None:
    """Install an explicitly configured process-local store for the functional API."""

    global _DEFAULT_STORE
    if not isinstance(store, QuarantineStore):
        raise TypeError("default quarantine must be a QuarantineStore")
    _DEFAULT_STORE = store


def promote(candidate_id: str, approval: HumanApproval) -> ValidatedAtom:
    """Promote through the process-wide default quarantine store."""

    return _DEFAULT_STORE.promote(candidate_id, approval)
