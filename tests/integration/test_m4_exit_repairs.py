"""Approved exit repairs exercised through the real M4 compiler composition."""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from contractcapsule.compile.budget import LocalTokenCounter
from contractcapsule.models.core import Atom
from contractcapsule.models.view import RankedAtom, TaskContext, ViewBudget
from contractcapsule.resolve.rank import FTS5BM25Ranker
from tests.integration.test_compile_view import pipeline, selection
from tests.m4_helpers import M4Fixture


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
