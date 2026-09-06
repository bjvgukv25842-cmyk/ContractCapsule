"""Real publication regressions from the independent M4 service review."""

import hashlib
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from contractcapsule.audit.quarantine import ValidatedAtom
from contractcapsule.build.atomize import bind_evidence, extract_candidate_atoms
from contractcapsule.build.ingest import SourceInput, TrustedDeterministicCollector
from contractcapsule.build.publish import _validate_through_loader
from contractcapsule.compile.errors import CompileError
from contractcapsule.compile.evidence import NativeEvidenceResolver
from contractcapsule.compile.git_evidence import validate_git_locator
from contractcapsule.models.core import GitImmutableEvidence
from contractcapsule.resolve.graph import resolve_graph
from contractcapsule.resolve.policies import StaticEligibilityAuthorizer
from tests.m4_helpers import M4Fixture
from tests.unit.test_dependency_closure import admit, dependencies, edge
from tests.unit.test_eligibility import (
    AS_OF,
    READER,
    access_grant,
    freshness_for,
    task_context,
)
from tests.unit.test_evidence_handles import native_publication


@pytest.mark.parametrize("kind", ["requires", "conflicts"])
@pytest.mark.parametrize("source", ["a", "com.example.owner"])
def test_foreign_graph_sources_cannot_rewrite_owner_dependencies(
    tmp_path: Path, kind: str, source: str
) -> None:
    fixture = M4Fixture.create(tmp_path)
    owner = fixture.publish(
        capsule_id="com.example.owner", atoms=({"atom_id": "a"}, {"atom_id": "b"})
    )
    foreign = fixture.publish(
        capsule_id="com.example.foreign",
        atoms=({"atom_id": "c"},),
        amend=dependencies((), (), (edge(source, "b", kind),)),
    )
    with pytest.raises(CompileError, match="^INVALID_GRAPH$"):
        resolve_graph(admit(fixture, (owner, foreign)), task_context())


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE
    ).strip()


def test_capsule_source_edges_are_bound_to_declaring_release(tmp_path: Path) -> None:
    fixture = M4Fixture.create(tmp_path)
    first = fixture.publish(
        capsule_id="com.example.owner",
        version="1.0.0",
        atoms=({"atom_id": "old"},),
        amend=dependencies((), (), (edge("com.example.owner", "old"),)),
    )
    second = fixture.publish(
        capsule_id="com.example.owner", version="2.0.0", atoms=({"atom_id": "new"},)
    )
    graph = resolve_graph(admit(fixture, (first, second)), task_context())
    assert graph.close_atoms({"new"}) == {"new"}
    assert graph.close_atoms({"old"}) == {"old"}


def test_legacy_git_locator_still_requires_real_anchor(tmp_path: Path) -> None:
    pub, _, _, _ = native_publication(tmp_path, "GIT_IMMUTABLE")
    record = pub.capsule.evidence_plane.records[0]
    assert isinstance(record, GitImmutableEvidence)
    legacy = record.model_copy(update={"extensions": {}})
    validate_git_locator(legacy, "# Evidence\r\nMUST keep native bytes.\r\n")
    changed = legacy.model_copy(
        update={
            "locator": legacy.locator.model_copy(
                update={"symbol_or_heading": "invented"}
            )
        }
    )
    with pytest.raises(CompileError, match="^EVIDENCE_INTEGRITY$"):
        validate_git_locator(changed, "# Evidence\r\nMUST keep native bytes.\r\n")


def test_missing_promised_git_object_never_starts_fetch(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    pub, task, resolver, _ = native_publication(source, "GIT_IMMUTABLE")
    _git(source, "config", "uploadpack.allowFilter", "true")
    partial = tmp_path / "partial"
    _git(
        tmp_path,
        "clone",
        "--filter=blob:none",
        "--no-checkout",
        source.as_uri(),
        str(partial),
    )
    _git(partial, "remote", "set-url", "origin", "https://example.invalid/repo")
    resolver = replace(resolver, git_roots={"https://example.invalid/repo": partial})
    trace = tmp_path / "git-trace.txt"
    objects = {
        p.relative_to(partial).as_posix(): p.read_bytes()
        for p in (partial / ".git/objects").rglob("*")
        if p.is_file()
    }
    # Prevent transport even on RED; trace detects the prohibited fetch attempt itself.
    with (
        patch.dict(
            os.environ,
            {
                "GIT_TRACE": str(trace),
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "protocol.allow",
                "GIT_CONFIG_VALUE_0": "never",
            },
        ),
        pytest.raises(CompileError, match="^EVIDENCE_UNAVAILABLE$"),
    ):
        resolver.resolve(
            pub, pub.capsule.semantic_payload.atoms[0], READER, task, AS_OF
        )
    assert "fetch origin" not in trace.read_text()
    assert objects == {
        p.relative_to(partial).as_posix(): p.read_bytes()
        for p in (partial / ".git/objects").rglob("*")
        if p.is_file()
    }


class _GitFixture(M4Fixture):
    def _promote(self, index: int, options: Any) -> ValidatedAtom:
        root = self.harness.root
        path = root / "source.md"
        path.write_bytes(b"# Policy\nMUST preserve approved rule.\n")
        for args in (
            ("init", "-q"),
            ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "M4 test"),
            ("remote", "add", "origin", "https://example.invalid/repo"),
            ("add", "source.md"),
            ("commit", "-qm", "fixture"),
        ):
            _git(root, *args)
        store = self.harness.store
        snapshot = TrustedDeterministicCollector(
            store, self.harness.authority.trust_root()
        ).snapshot(
            SourceInput(
                path=path,
                mode="GIT_IMMUTABLE",
                repository="https://example.invalid/repo",
                revision="sha1:" + _git(root, "rev-parse", "HEAD"),
                repository_root=root,
                quarantine=store,
                access_policy="team-auth",
                generated=False,
            ),
            self.harness.principal,
        )
        candidate = extract_candidate_atoms(snapshot)[1]
        binding = bind_evidence(candidate, snapshot)
        approval = self.harness.authority.issue(candidate, (binding,), "reviewer")
        return store.promote(candidate.candidate_id, approval)


def _thin_load(capsule: Any, blobs: Any, *args: Any) -> Any:
    return _validate_through_loader(capsule, {}, *args)


@pytest.mark.parametrize("fault", ["different_span", "locator_heading"])
def test_git_excerpt_stays_bound_to_approval_and_stable_anchor(
    tmp_path: Path, fault: str
) -> None:
    fixture = _GitFixture.create(tmp_path)

    def amend(raw: dict[str, Any]) -> None:
        raw["control_manifest"]["scope"]["paths"] = ["source.md"]
        record = raw["evidence_plane"]["records"][0]
        if fault == "different_span":
            record["locator"].update(
                start_line=1,
                end_line=1,
                span_digest="sha256:" + hashlib.sha256(b"# Policy\n").hexdigest(),
            )
        else:
            record["locator"]["symbol_or_heading"] = "invented-anchor"

    with patch("tests.m4_helpers._validate_through_loader", _thin_load):
        pub = fixture.publish(amend=amend)
    resolver = NativeEvidenceResolver(
        fixture.registry,
        StaticEligibilityAuthorizer(grants=(access_grant(),)),
        freshness_for(pub),
        {"https://example.invalid/repo": fixture.harness.root},
        {},
    )
    with pytest.raises(CompileError, match="^EVIDENCE_INTEGRITY$"):
        resolver.resolve(
            pub,
            pub.capsule.semantic_payload.atoms[0],
            READER,
            task_context(paths=("source.md",)),
            AS_OF,
        )
