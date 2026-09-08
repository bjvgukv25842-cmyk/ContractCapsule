"""Approved exit repairs exercised through the real M4 compiler composition."""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from contractcapsule.compile.budget import LocalTokenCounter
from contractcapsule.compile.evidence import NativeEvidenceResolver
from contractcapsule.compile.renderers import NeutralViewRenderer
from contractcapsule.models.core import Atom
from contractcapsule.models.view import (
    CompiledView,
    RankedAtom,
    TaskContext,
    ViewBudget,
)
from contractcapsule.resolve.graph import ResolvedGraph
from contractcapsule.resolve.rank import FTS5BM25Ranker
from tests.integration.test_compile_view import pipeline, selection
from tests.m4_helpers import M4Fixture
from tests.unit.test_eligibility import access_grant, task_context


@dataclass(frozen=True)
class ReverseRanker:
    version: str = "1.0.0"
    config_digest: str = "sha256:" + "1" * 64

    def rank_atoms(self, atoms: list[Atom], task: TaskContext) -> list[RankedAtom]:
        return list(reversed(FTS5BM25Ranker().rank_atoms(atoms, task)))


@pytest.fixture(scope="module")
def counter() -> LocalTokenCounter:
    return LocalTokenCounter("exit-repair-test")


@pytest.mark.parametrize(
    "earlier,later",
    [
        ("P2_EVIDENCE", "P3_SUMMARY"),
        ("P2_EVIDENCE", "P4_TRANSIENT"),
        ("P3_SUMMARY", "P4_TRANSIENT"),
    ],
)
def test_compiler_owns_optional_class_precedence(
    tmp_path: Path, counter: LocalTokenCounter, earlier: str, later: str
) -> None:
    fixture = M4Fixture.create(tmp_path)

    def no_expiry(raw: dict[str, Any]) -> None:
        for policy in raw["compression_policy"]["classes"]:
            if policy["name"] == "P4_TRANSIENT":
                policy["ttl"] = None

    publication = fixture.publish(
        atoms=(
            {
                "atom_id": "first",
                "statement": "token required evidence. " * 70,
                "compression_class": earlier,
            },
            {
                "atom_id": "second",
                "statement": "token background history. " * 70,
                "compression_class": later,
            },
        ),
        amend=no_expiry,
    )
    compiler, request = pipeline(fixture, (publication,), counter)
    full = compiler.compile_view(request)
    assert full.validation.valid and selection(full) == {"first", "second"}
    assert full.manifest.tokens.total > 1400
    limited = request.model_copy(update={"budget": ViewBudget(model_input_tokens=1400)})
    native = compiler.compile_view(limited)
    alternate = replace(compiler, ranker=ReverseRanker()).compile_view(limited)
    assert native.validation.valid and selection(native) == {"first"}
    assert alternate.validation.valid and selection(alternate) == {"first"}
    assert alternate.manifest.tokens.total == counter.count(alternate.content)


def test_compiler_preserves_rank_order_within_one_class(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    publication = fixture.publish(
        atoms=tuple(
            {
                "atom_id": atom_id,
                "statement": "token evidence. " * 100,
                "compression_class": "P2_EVIDENCE",
            }
            for atom_id in ("first", "second")
        )
    )
    compiler, request = pipeline(fixture, (publication,), counter)
    request = request.model_copy(update={"budget": ViewBudget(model_input_tokens=1600)})
    native = compiler.compile_view(request)
    alternate = replace(compiler, ranker=ReverseRanker()).compile_view(request)
    assert native.validation.valid and selection(native) == {"first"}
    assert alternate.validation.valid and selection(alternate) == {"second"}


def private_pair(tmp_path: Path, counter: LocalTokenCounter, *, conflict: bool = False):
    fixture = M4Fixture.create(tmp_path)

    def amend(raw: dict[str, Any]) -> None:
        if conflict:
            raw["semantic_payload"]["atoms"][0]["conflicts_with"] = ["private-second"]

    first = fixture.publish(
        capsule_id="com.private.first",
        provides=("first/v1",),
        atoms=({"atom_id": "private-first", "compression_class": "P0_EXACT"},),
        amend=amend,
    )
    second = fixture.publish(
        capsule_id="com.private.second",
        provides=("second/v1",),
        atoms=({"atom_id": "private-second", "compression_class": "P0_EXACT"},),
    )
    compiler, request = pipeline(fixture, (first, second), counter)
    task = task_context(required_interfaces=("first/v1", "second/v1"))
    return compiler, request.model_copy(update={"task": task})


def assert_withheld(view: CompiledView) -> None:
    assert not view.validation.valid and view.content == ""
    assert not view.evidence_handles
    manifest = view.manifest
    assert not manifest.capsules
    assert not manifest.decisions
    assert not manifest.providers
    assert not manifest.closure
    assert not manifest.conflicts
    assert not manifest.expanded_evidence
    assert manifest.permission_digest == "sha256:" + "0" * 64
    assert manifest.request_digest == "sha256:" + "0" * 64
    assert manifest.tokens.total == 0 and not manifest.tokens.sections
    assert manifest.rejected_counts == {"AUTHORIZATION_SNAPSHOT_INVALIDATED": 2}
    assert {service.name for service in manifest.services} == {"compiler"}
    output = view.model_dump_json()
    for identifier in (
        "com.private.first",
        "com.private.second",
        "private-first",
        "private-second",
    ):
        assert identifier not in output


@pytest.mark.parametrize("change", ["all", "partial", "invalid", "unchanged"])
def test_final_authorization_controls_entire_failure_projection(
    tmp_path: Path, counter: LocalTokenCounter, change: str
) -> None:
    compiler, request = private_pair(tmp_path, counter)
    reference = compiler.compile_view(request)
    assert reference.validation.valid and len(reference.manifest.providers) == 2
    original = NativeEvidenceResolver.resolve
    calls = 0

    def final_read(self, *args):
        nonlocal calls
        result = original(self, *args)
        calls += 1
        if calls == 4 and change != "unchanged":
            if change == "partial":
                grants = (access_grant(capsule_ids=("com.private.first",)),)
            else:
                grants = () if change == "all" else None
            object.__setattr__(self.authorizer, "grants", grants)
        return result

    with patch.object(NativeEvidenceResolver, "resolve", final_read):
        view = compiler.compile_view(request)
    assert calls == 4
    if change == "unchanged":
        assert view == reference
    else:
        expected = (
            "INVALID_POLICY_SNAPSHOT"
            if change == "invalid"
            else "POLICY_SNAPSHOT_CHANGED"
        )
        assert view.validation.blockers == (expected,)
        assert_withheld(view)


@pytest.mark.parametrize(
    "failure,blocker",
    [("rank", "RANKING_FAILED"), ("budget", "P0_OVERFLOW"), ("conflict", "CONFLICT")],
)
def test_other_failures_cannot_export_revoked_admission(
    tmp_path: Path, counter: LocalTokenCounter, failure: str, blocker: str
) -> None:
    compiler, request = private_pair(tmp_path, counter, conflict=failure == "conflict")
    if failure == "budget":
        request = request.model_copy(
            update={"budget": ViewBudget(model_input_tokens=1)}
        )
    boundary = {
        "rank": (FTS5BM25Ranker, "rank_atoms"),
        "budget": (NeutralViewRenderer, "render"),
        "conflict": (ResolvedGraph, "conflicts_for"),
    }[failure]
    original = getattr(*boundary)

    def revoke(self, *args):
        result = original(self, *args)
        object.__setattr__(compiler.authorizer, "grants", ())
        if failure == "rank":
            raise RuntimeError("rank service failed after revocation")
        return result

    with patch.object(*boundary, revoke):
        view = compiler.compile_view(request)
    assert view.validation.blockers == (blocker,)
    assert_withheld(view)


def test_authorized_budget_failure_keeps_attempted_decisions_and_tokens(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    compiler, request = private_pair(tmp_path, counter)
    reference = compiler.compile_view(request)
    request = request.model_copy(update={"budget": ViewBudget(model_input_tokens=1)})
    failed = compiler.compile_view(request)
    assert failed.validation.blockers == ("P0_OVERFLOW",) and not failed.content
    assert selection(failed) == {"private-first", "private-second"}
    assert failed.manifest.tokens.total > failed.manifest.tokens.available
    assert failed.manifest.permission_digest == reference.manifest.permission_digest
    assert failed.manifest.rejected_counts == {}
