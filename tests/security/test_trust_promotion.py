from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from contractcapsule.audit.quarantine import (
    ApprovalAuthority,
    CandidateAtom,
    EvidenceBinding,
    HumanApproval,
    QuarantineError,
    QuarantineStore,
)
from contractcapsule.build.atomize import (
    bind_evidence,
    extract_candidate_atoms,
    render_evidence,
)
from contractcapsule.build.ingest import SourceInput, SourceSnapshot, snapshot_source
from contractcapsule.models import Principal


def _candidate(
    tmp_path: Path,
) -> tuple[QuarantineStore, SourceSnapshot, CandidateAtom, EvidenceBinding]:
    path = tmp_path / "rules.md"
    path.write_text("# Rules\nThe service MUST use TLS.\n", encoding="utf-8")
    authority = ApprovalAuthority({"human": b"secret"})
    store = QuarantineStore(approval_verifier=authority.verifier())
    snapshot = snapshot_source(
        SourceInput(path=path, mode="CAS", quarantine=store, generated=True),
        Principal("builder"),
    )
    candidate = extract_candidate_atoms(snapshot)[1]
    binding = bind_evidence(candidate, snapshot)
    return store, snapshot, candidate, binding


def test_generated_observation_is_quarantined(tmp_path: Path) -> None:
    store, _snapshot, candidate, _binding = _candidate(tmp_path)
    assert candidate.trust_level == "T3"
    assert candidate.status == "candidate"
    assert store.pending(candidate.candidate_id) is True


def test_forged_or_mismatched_approval_fails_closed(tmp_path: Path) -> None:
    store, _snapshot, candidate, binding = _candidate(tmp_path)
    authority = ApprovalAuthority({"human": b"secret"})
    genuine = authority.issue(candidate, (binding,), "human")
    forged = HumanApproval(
        approval_id=genuine.approval_id,
        candidate_id=genuine.candidate_id,
        approver_id=genuine.approver_id,
        approved_at=genuine.approved_at,
        decision="approve",
        candidate_digest="sha256:" + "0" * 64,
        evidence_digests=genuine.evidence_digests,
        expires_at=genuine.expires_at,
        signature=genuine.signature,
    )
    with pytest.raises(QuarantineError, match="approval"):
        store.promote(candidate.candidate_id, forged)


def test_approval_signature_tampering_fails_closed(tmp_path: Path) -> None:
    store, _snapshot, candidate, binding = _candidate(tmp_path)
    authority = ApprovalAuthority({"human": b"secret"})
    genuine = authority.issue(candidate, (binding,), "human")
    forged = replace(genuine, signature="hmac-sha256:" + "0" * 64)
    with pytest.raises(QuarantineError, match="trusted"):
        store.promote(candidate.candidate_id, forged)


def test_expired_approval_fails_closed(tmp_path: Path) -> None:
    store, _snapshot, candidate, binding = _candidate(tmp_path)
    authority = ApprovalAuthority({"human": b"secret"})
    expired = authority.issue(
        candidate,
        (binding,),
        "human",
        approved_at=datetime.now(UTC) - timedelta(days=2),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    with pytest.raises(QuarantineError, match="expired"):
        store.promote(candidate.candidate_id, expired)


@pytest.mark.parametrize("compression_class", ["P0_EXACT", "P1_STRUCTURED"])
def test_missing_evidence_cannot_promote_p0_or_p1(
    tmp_path: Path, compression_class: str
) -> None:
    store, _snapshot, candidate, _binding = _candidate(tmp_path)
    if compression_class != candidate.compression_class:
        object.__setattr__(candidate, "compression_class", compression_class)
        store._bindings[candidate.candidate_id] = ()  # type: ignore[attr-defined]
    authority = ApprovalAuthority({"human": b"secret"})
    approval = authority.issue(candidate, (), "human")
    with pytest.raises(QuarantineError, match="evidence"):
        store.promote(candidate.candidate_id, approval)


def test_approval_cannot_be_self_issued_without_trusted_authority(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rules.md"
    path.write_text("# Rules\nThe service MUST use TLS.\n", encoding="utf-8")
    store = QuarantineStore()
    snapshot = snapshot_source(
        SourceInput(path=path, mode="CAS", quarantine=store), Principal("builder")
    )
    candidate = extract_candidate_atoms(snapshot)[1]
    binding = bind_evidence(candidate, snapshot)
    with pytest.raises(QuarantineError, match="approval"):
        store.promote(
            candidate.candidate_id,
            HumanApproval.untrusted(
                candidate.candidate_id, evidence_digests=(binding.content_digest,)
            ),
        )


def test_secret_scan_is_repeated_before_evidence_rendering(tmp_path: Path) -> None:
    _store, snapshot, _candidate_atom, binding = _candidate(tmp_path)
    assert render_evidence(binding, snapshot) == "The service MUST use TLS.\n"
    object.__setattr__(
        snapshot,
        "content",
        b"# Rules\napi_key = 'sk-live-1234567890123456'\n",
    )
    object.__setattr__(snapshot, "mode", "EXTERNAL_IMMUTABLE")
    with pytest.raises(QuarantineError, match="secret"):
        render_evidence(binding, snapshot)


def test_quarantine_store_exposes_verify_only_boundary(tmp_path: Path) -> None:
    authority = ApprovalAuthority({"human": b"secret"})
    store = QuarantineStore(approval_verifier=authority.verifier())
    assert not hasattr(store, "approval_authority")
    path = tmp_path / "rules.md"
    path.write_text("# Rules\nTLS MUST be enabled.\n", encoding="utf-8")
    snapshot = snapshot_source(
        SourceInput(path=path, mode="CAS", quarantine=store, generated=True),
        Principal("builder"),
    )
    candidate = extract_candidate_atoms(snapshot)[1]
    assert candidate.trust_level == "T3"
    assert candidate.status == "candidate"
