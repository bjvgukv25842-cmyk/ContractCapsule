from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from contractcapsule.audit.quarantine import (
    ApprovalAuthority,
    HumanApproval,
    QuarantineError,
    QuarantineStore,
    SecretDetectedError,
)
from contractcapsule.build.atomize import bind_evidence, extract_candidate_atoms
from contractcapsule.build.ingest import (
    SourceInput,
    TrustedDeterministicCollector,
    snapshot_source,
)
from contractcapsule.build.publish import (
    BuildError,
    BuildRequest,
    DraftCapsule,
    build_capsule,
    publish_draft,
)
from contractcapsule.models import Principal
from contractcapsule.storage.cas import FilesystemCAS
from contractcapsule.storage.registry import PolicyDecision, Registry


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


class _AllowPolicy:
    def resolve(
        self, principal: Principal, action: str, authority: str, scope: object
    ) -> PolicyDecision:
        del principal, action, authority, scope
        return PolicyDecision(True, frozenset({"repository-authorized"}))


@pytest.fixture
def git_source(tmp_path: Path) -> tuple[Path, str, Principal]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "M3 test")
    _git(root, "remote", "add", "origin", "https://example.invalid/project")
    source = root / "policy.md"
    source.write_text(
        "# Token policy\nTokens MUST expire within 15 minutes.\n", encoding="utf-8"
    )
    _git(root, "add", "policy.md")
    _git(root, "commit", "-q", "-m", "fixture")
    revision = _git(root, "rev-parse", "HEAD")
    return root, revision, Principal("m3-test")


def test_snapshot_and_atomization_are_deterministic(
    git_source: tuple[Path, str, Principal],
) -> None:
    root, revision, principal = git_source
    source = SourceInput(
        path=root / "policy.md",
        mode="GIT_IMMUTABLE",
        repository="https://example.invalid/project",
        revision=f"sha1:{revision}",
        repository_root=root,
    )
    first = snapshot_source(source, principal)
    second = snapshot_source(source, principal)
    assert first.snapshot_id == second.snapshot_id
    assert first.content_digest == second.content_digest
    assert extract_candidate_atoms(first) == extract_candidate_atoms(second)


@pytest.mark.parametrize(
    ("filename", "content", "symbols"),
    [
        (
            "module.py",
            "class Service:\n    pass\n\ndef run() -> None:\n    pass\n",
            {"Service", "run"},
        ),
        ("config.json", '{"enabled":true,"timeout":15}\n', {"enabled", "timeout"}),
        ("schema.yaml", "type: object\nrequired:\n  - enabled\n", {"type", "required"}),
    ],
)
def test_code_config_and_schema_use_deterministic_structural_parsers(
    tmp_path: Path, filename: str, content: str, symbols: set[str]
) -> None:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    snapshot = snapshot_source(SourceInput(path=path), Principal("parser"))
    first = extract_candidate_atoms(snapshot)
    second = extract_candidate_atoms(snapshot)
    assert first == second
    assert {atom.symbol_or_heading for atom in first} == symbols


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("duplicate.json", '{"a":1,"a":2}\n'),
        ("duplicate.yaml", "a: 1\na: 2\n"),
    ],
)
def test_source_structured_parsers_reject_duplicate_keys(
    tmp_path: Path, filename: str, content: str
) -> None:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    with pytest.raises(QuarantineError, match="duplicate"):
        snapshot_source(SourceInput(path=path), Principal("parser"))


def test_git_binding_contains_commit_path_stable_heading_and_digests(
    git_source: tuple[Path, str, Principal],
) -> None:
    root, revision, principal = git_source
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    store = QuarantineStore(trust_root=authority.trust_root())
    collector = TrustedDeterministicCollector(store, authority.trust_root())
    source = SourceInput(
        path=root / "policy.md",
        mode="GIT_IMMUTABLE",
        repository="https://example.invalid/project",
        revision=f"sha1:{revision}",
        repository_root=root,
        quarantine=store,
    )
    snapshot = collector.snapshot(source, principal)
    candidate = extract_candidate_atoms(snapshot)[0]
    binding = bind_evidence(candidate, snapshot)
    assert candidate.trust_level == "T2"
    assert binding.mode == "GIT_IMMUTABLE"
    assert binding.repository == source.repository
    assert binding.revision == source.revision
    assert binding.path == "policy.md"
    assert binding.symbol_or_heading == "Token policy"
    assert binding.span_digest.startswith("sha256:")
    assert binding.content_digest == snapshot.content_digest


def test_external_immutable_source_is_offline_but_fully_bound(tmp_path: Path) -> None:
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    store = QuarantineStore(trust_root=authority.trust_root())
    snapshot = snapshot_source(
        SourceInput(
            mode="EXTERNAL_IMMUTABLE",
            content=b"The endpoint MUST remain documented.\n",
            uri="https://example.invalid/immutable-source",
            source="publisher-record",
            verification_method="publisher-checksum",
            media_type="text/plain",
            quarantine=store,
        ),
        Principal("builder"),
    )
    candidate = extract_candidate_atoms(snapshot)[0]
    binding = bind_evidence(candidate, snapshot)
    assert binding.mode == "EXTERNAL_IMMUTABLE"
    assert binding.uri == snapshot.uri
    approval = authority.issue(candidate, (binding,), "reviewer")
    validated = store.promote(candidate.candidate_id, approval)
    draft = build_capsule(BuildRequest(atoms=(validated,), quarantine=store))
    record = draft.capsule.evidence_plane.records[0]
    assert record.mode == "EXTERNAL_IMMUTABLE"
    assert record.content_digest == snapshot.content_digest


def test_git_requires_full_commit_and_matching_repository_identity(
    git_source: tuple[Path, str, Principal],
) -> None:
    root, revision, principal = git_source
    with pytest.raises(QuarantineError, match="full"):
        snapshot_source(
            SourceInput(
                path=root / "policy.md",
                mode="GIT_IMMUTABLE",
                repository="https://example.invalid/project",
                revision="HEAD",
                repository_root=root,
            ),
            principal,
        )
    with pytest.raises(QuarantineError, match="origin"):
        snapshot_source(
            SourceInput(
                path=root / "policy.md",
                mode="GIT_IMMUTABLE",
                repository="https://other.invalid/project",
                revision=f"sha1:{revision}",
                repository_root=root,
            ),
            principal,
        )


def test_symlinked_source_is_rejected_before_snapshot(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text("# Safe\nThis MUST remain local.\n", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(target)
    with pytest.raises(QuarantineError, match="symbolic link"):
        snapshot_source(SourceInput(path=link, mode="CAS"), Principal("builder"))


def test_source_drift_is_rejected_even_when_old_line_numbers_are_reused(
    git_source: tuple[Path, str, Principal],
) -> None:
    root, revision, principal = git_source
    source = SourceInput(
        path=root / "policy.md",
        mode="GIT_IMMUTABLE",
        repository="https://example.invalid/project",
        revision=f"sha1:{revision}",
        repository_root=root,
    )
    snapshot = snapshot_source(source, principal)
    candidate = extract_candidate_atoms(snapshot)[1]
    root.joinpath("policy.md").write_text(
        "# Token policy\nTokens MUST expire within 90 minutes.\n", encoding="utf-8"
    )
    with pytest.raises(QuarantineError, match="drift"):
        bind_evidence(candidate, snapshot)


def test_validated_atom_requires_binding_and_external_approval(
    git_source: tuple[Path, str, Principal],
) -> None:
    root, revision, principal = git_source
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    store = QuarantineStore(approval_verifier=authority.verifier())
    source = SourceInput(
        path=root / "policy.md",
        mode="GIT_IMMUTABLE",
        repository="https://example.invalid/project",
        revision=f"sha1:{revision}",
        repository_root=root,
        quarantine=store,
    )
    snapshot = snapshot_source(source, principal)
    candidate = extract_candidate_atoms(snapshot)[1]
    with pytest.raises(QuarantineError, match="evidence"):
        store.promote(
            candidate.candidate_id, HumanApproval.untrusted(candidate.candidate_id)
        )
    binding = bind_evidence(candidate, snapshot)
    approval = authority.issue(candidate, (binding,), "reviewer")
    validated = store.promote(candidate.candidate_id, approval)
    assert validated.status == "validated"
    assert validated.trust_level == "T1"
    assert validated.evidence_bindings == (binding,)


def test_build_rejects_raw_candidate_and_accepts_only_validated_atoms(
    git_source: tuple[Path, str, Principal],
) -> None:
    root, revision, principal = git_source
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    store = QuarantineStore(approval_verifier=authority.verifier())
    source = SourceInput(
        path=root / "policy.md",
        mode="GIT_IMMUTABLE",
        repository="https://example.invalid/project",
        revision=f"sha1:{revision}",
        repository_root=root,
        quarantine=store,
    )
    snapshot = snapshot_source(source, principal)
    candidate = extract_candidate_atoms(snapshot)[1]
    with pytest.raises(QuarantineError):
        build_capsule(BuildRequest(atoms=(candidate,)))  # type: ignore[arg-type]
    binding = bind_evidence(candidate, snapshot)
    approval = authority.issue(candidate, (binding,), "reviewer")
    validated = store.promote(candidate.candidate_id, approval)
    draft = build_capsule(BuildRequest(atoms=(validated,), quarantine=store))
    assert draft.capsule.semantic_payload.atoms[0].status == "validated"
    assert draft.capsule.control_manifest.lifecycle == "VALIDATED"
    recorded = draft.capsule.semantic_payload.atoms[0].extensions["x-trust"]
    assert recorded["approval"]["approval_id"] == approval.approval_id


def test_formal_atom_requires_evidence(
    git_source: tuple[Path, str, Principal],
) -> None:
    root, revision, principal = git_source
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    store = QuarantineStore(approval_verifier=authority.verifier())
    snapshot = snapshot_source(
        SourceInput(
            path=root / "policy.md",
            mode="GIT_IMMUTABLE",
            repository="https://example.invalid/project",
            revision=f"sha1:{revision}",
            repository_root=root,
            quarantine=store,
        ),
        principal,
    )
    candidate = extract_candidate_atoms(snapshot)[1]
    with pytest.raises(QuarantineError, match="evidence"):
        store.promote(
            candidate.candidate_id,
            HumanApproval.untrusted(candidate.candidate_id),
        )


def test_summary_cannot_replace_evidence(tmp_path: Path) -> None:
    source_path = tmp_path / "policy.md"
    source_path.write_text(
        "# Policy\nRequests MUST be authenticated.\n", encoding="utf-8"
    )
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    store = QuarantineStore(approval_verifier=authority.verifier())
    snapshot = snapshot_source(
        SourceInput(path=source_path, mode="CAS", quarantine=store),
        Principal("builder"),
    )
    candidate = extract_candidate_atoms(snapshot)[1]
    binding = bind_evidence(candidate, snapshot)
    approval = authority.issue(candidate, (binding,), "reviewer")
    validated = store.promote(candidate.candidate_id, approval)
    draft = build_capsule(BuildRequest(atoms=(validated,), quarantine=store))
    atom = draft.capsule.semantic_payload.atoms[0]
    evidence = draft.capsule.evidence_plane.records[0]
    assert atom.statement == "Requests MUST be authenticated."
    assert atom.evidence_refs == (evidence.evidence_id,)
    assert evidence.content_digest == snapshot.content_digest
    assert evidence.extensions["x-source-map"]["span_digest"] == binding.span_digest


def test_public_build_validate_publish_pipeline_has_no_draft_bypass(
    git_source: tuple[Path, str, Principal], tmp_path: Path
) -> None:
    root, revision, principal = git_source
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    store = QuarantineStore(approval_verifier=authority.verifier())
    snapshot = snapshot_source(
        SourceInput(
            path=root / "policy.md",
            mode="GIT_IMMUTABLE",
            repository="https://example.invalid/project",
            revision=f"sha1:{revision}",
            repository_root=root,
            quarantine=store,
        ),
        principal,
    )
    candidate = extract_candidate_atoms(snapshot)[1]
    binding = bind_evidence(candidate, snapshot)
    approval = authority.issue(candidate, (binding,), "reviewer")
    validated = store.promote(candidate.candidate_id, approval)
    signature = {
        "algorithm": "m3-test-only",
        "key_id": "m3-test-key",
        "value": "test-signature-not-production",
        "envelope": {"x-purpose": "M3 trust-path test"},
    }
    draft = build_capsule(
        BuildRequest(
            atoms=(validated,),
            quarantine=store,
            lifecycle="PUBLISHED",
            detached_signature=signature,
        )
    )
    registry = Registry(
        tmp_path / "registry.sqlite3",
        FilesystemCAS(tmp_path / "cas"),
        resolver=_AllowPolicy(),
        trust_root=authority.trust_root(),
    )
    published = publish_draft(draft, principal, registry)
    assert (
        published.capsule.control_manifest.content_digest
        == draft.capsule.control_manifest.content_digest
    )
    assert (
        registry.get("org.contractcapsule.generated", "0.1.0", principal) == published
    )

    forged = DraftCapsule(
        capsule=draft.capsule,
        atom_ids=draft.atom_ids,
        package_path=None,
        validation_pipeline=draft.validation_pipeline,
    )
    with pytest.raises(BuildError, match="public-loader"):
        publish_draft(forged, principal, registry)


def test_public_pipeline_reuses_m2_cas_and_registry_authorization(
    tmp_path: Path,
) -> None:
    principal = Principal("builder")
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    store = QuarantineStore(trust_root=authority.trust_root())
    cas = FilesystemCAS(tmp_path / "cas")
    source_path = tmp_path / "policy.md"
    source_path.write_text("# Policy\nThe service MUST use TLS.\n", encoding="utf-8")
    snapshot = snapshot_source(
        SourceInput(
            path=source_path,
            mode="CAS",
            cas=cas,
            quarantine=store,
        ),
        principal,
    )
    candidate = extract_candidate_atoms(snapshot)[1]
    binding = bind_evidence(candidate, snapshot)
    validated = store.promote(
        candidate.candidate_id,
        authority.issue(candidate, (binding,), "reviewer"),
    )
    draft = build_capsule(
        BuildRequest(
            atoms=(validated,),
            quarantine=store,
            lifecycle="PUBLISHED",
            detached_signature={
                "algorithm": "m3-test-only",
                "key_id": "m3-test-key",
                "value": "test-signature-not-production",
                "envelope": {},
            },
        )
    )
    registry = Registry(
        tmp_path / "registry.sqlite3",
        cas,
        resolver=_AllowPolicy(),
        trust_root=authority.trust_root(),
    )
    published = publish_draft(draft, principal, registry)
    assert registry.get_blob(snapshot.content_digest, principal) == snapshot.content
    assert published.registry_status == "PUBLISHED"


def test_tampered_validated_atom_cannot_bypass_quarantine(
    git_source: tuple[Path, str, Principal],
) -> None:
    root, revision, principal = git_source
    authority = ApprovalAuthority({"reviewer": b"test-secret"})
    store = QuarantineStore(approval_verifier=authority.verifier())
    snapshot = snapshot_source(
        SourceInput(
            path=root / "policy.md",
            mode="GIT_IMMUTABLE",
            repository="https://example.invalid/project",
            revision=f"sha1:{revision}",
            repository_root=root,
            quarantine=store,
        ),
        principal,
    )
    candidate = extract_candidate_atoms(snapshot)[1]
    binding = bind_evidence(candidate, snapshot)
    approval = authority.issue(candidate, (binding,), "reviewer")
    validated = store.promote(candidate.candidate_id, approval)
    forged = replace(validated, statement="Unbound generated replacement")
    with pytest.raises(QuarantineError, match="not promoted"):
        build_capsule(BuildRequest(atoms=(forged,), quarantine=store))


def test_secret_content_is_rejected_before_storage_or_rendering(tmp_path: Path) -> None:
    source_path = tmp_path / "secret.md"
    source_path.write_text(
        "# Credentials\napi_key = 'sk-test-1234567890'\n", encoding="utf-8"
    )
    with pytest.raises(SecretDetectedError):
        snapshot_source(SourceInput(path=source_path, mode="CAS"), Principal("m3-test"))
