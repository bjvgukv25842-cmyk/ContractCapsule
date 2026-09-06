"""Real SQLite lexical ranks, literal queries and fail-closed input boundaries."""

import sqlite3
from dataclasses import FrozenInstanceError
from itertools import permutations
from typing import Any

import pytest

from contractcapsule.compile.errors import CompileError
from contractcapsule.compile.protocols import (
    AtomRanker,
    EligibilityAuthorizer,
    FreshnessChecker,
)
from contractcapsule.models.base import Principal
from contractcapsule.models.core import Atom
from contractcapsule.models.view import TaskContext
from contractcapsule.resolve.policies import (
    RecordedFreshnessChecker,
    StaticEligibilityAuthorizer,
)
from contractcapsule.resolve.rank import FTS5BM25Ranker
from tests.m2_helpers import capsule_with_digest


def atom(atom_id: str, statement: str, **changes: Any) -> Atom:
    data = (
        capsule_with_digest()
        .semantic_payload.atoms[0]
        .model_dump(mode="python", by_alias=True)
    )
    data.update(atom_id=atom_id, statement=statement, compression_class="P2_EVIDENCE")
    data.update(changes)
    return Atom.model_validate(data)


def task(text: str = "", **changes: Any) -> TaskContext:
    data: dict[str, Any] = {
        "task_id": "rank",
        "tenant": "tenant",
        "repository": "repo",
        "paths": ("src/a.py",),
        "environment": "dev",
        "text": text,
    }
    data.update(changes)
    return TaskContext.model_validate(data)


def test_real_bm25_prefers_repeated_term_and_retains_unmatched() -> None:
    atoms = [
        atom("weak", "orchid other other"),
        atom("strong", "orchid orchid orchid"),
        atom("miss", "unrelated unrelated unrelated"),
    ]
    ranker: AtomRanker = FTS5BM25Ranker()
    result = ranker.rank_atoms(atoms, task("orchid"))
    assert [item.atom.atom_id for item in result] == ["strong", "weak", "miss"]
    # Equal document lengths give BM25 term-frequency factors 3*2.2/4.2 and 1.
    assert result[0].score == -1e-6 * (3 * 2.2 / 4.2)
    assert result[1].score == -1e-6
    assert (result[2].score, result[2].matched) == (0.0, False)


def test_frozen_services_fit_read_only_protocol_consumers() -> None:
    authorizer: EligibilityAuthorizer = StaticEligibilityAuthorizer()
    freshness: FreshnessChecker = RecordedFreshnessChecker()
    ranker: AtomRanker = FTS5BM25Ranker()
    capsule = capsule_with_digest()
    context = task("orchid")
    assert not authorizer.authorize(capsule, None, context, Principal("caller"))
    assert not freshness.check(capsule, None, "2026-09-05T00:00:00Z")
    assert ranker.rank_atoms([], context) == []


def test_compression_priority_precedes_match_and_p0_miss_is_retained() -> None:
    atoms = [
        atom("p4", "orchid", compression_class="P4_TRANSIENT"),
        atom("p2", "orchid"),
        atom("p0", "unrelated", compression_class="P0_EXACT"),
        atom("p3", "orchid", compression_class="P3_SUMMARY"),
        atom("p1", "orchid", compression_class="P1_STRUCTURED"),
    ]
    result = FTS5BM25Ranker().rank_atoms(atoms, task("orchid"))
    assert [item.atom.atom_id for item in result] == ["p0", "p1", "p2", "p3", "p4"]
    assert result[0].matched is False
    assert result[0].atom.statement == "unrelated"


@pytest.mark.parametrize("query", ['OR NOT NEAR * " ( )', '"OR" NOT (NEAR*)'])
def test_query_operators_are_literal_words(query: str) -> None:
    atoms = [atom("operator", "OR NOT NEAR"), atom("miss", "orchid")]
    result = FTS5BM25Ranker().rank_atoms(atoms, task(query))
    assert [(item.atom.atom_id, item.matched) for item in result] == [
        ("operator", True),
        ("miss", False),
    ]


def test_sql_strings_in_statements_and_queries_remain_data() -> None:
    atoms = [atom("quote'", "Robert'); DROP TABLE atoms; --"), atom("miss", "orchid")]
    result = FTS5BM25Ranker().rank_atoms(atoms, task("Robert'); DROP TABLE atoms; --"))
    assert [(item.atom.atom_id, item.matched) for item in result] == [
        ("quote'", True),
        ("miss", False),
    ]


@pytest.mark.parametrize("query", ["", " \t\n", '* " ( ) _'])
def test_empty_word_queries_have_zero_scores(query: str) -> None:
    result = FTS5BM25Ranker().rank_atoms(
        [atom("b", "orchid"), atom("a", "orchid")], task(query)
    )
    assert [(item.atom.atom_id, item.score, item.matched) for item in result] == [
        ("a", 0.0, False),
        ("b", 0.0, False),
    ]


def test_unicode_words_and_symbol_separators_are_searchable() -> None:
    atoms = [atom("unicode", "Caf\u00e9 \u4e2d\u6587 123"), atom("miss", "orchid")]
    result = FTS5BM25Ranker().rank_atoms(atoms, task("CAF\u00c9_\u4e2d\u6587-123"))
    assert [(item.atom.atom_id, item.matched) for item in result] == [
        ("unicode", True),
        ("miss", False),
    ]


def test_explicit_requirements_add_literal_query_words_without_indexing_ids() -> None:
    atoms = [atom("id-only", "unrelated"), atom("a", "audit"), atom("b", "token")]
    result = FTS5BM25Ranker().rank_atoms(
        atoms,
        task(required_atom_ids=("token", "id-only"), required_interfaces=("audit/v1",)),
    )
    assert [(item.atom.atom_id, item.matched) for item in result] == [
        ("a", True),
        ("b", True),
        ("id-only", False),
    ]


def test_query_word_order_and_duplicates_do_not_change_ranks() -> None:
    atoms = [atom("a", "orchid"), atom("b", "audit"), atom("c", "unrelated")]
    ranker = FTS5BM25Ranker()
    assert ranker.rank_atoms(atoms, task("audit orchid audit")) == ranker.rank_atoms(
        atoms, task("orchid audit")
    )


def test_all_input_permutations_have_identical_tied_results() -> None:
    atoms = [atom("b", "orchid"), atom("a", "orchid"), atom("c", "unrelated")]
    ranker = FTS5BM25Ranker()
    expected = ranker.rank_atoms(atoms, task("orchid"))
    assert [item.atom.atom_id for item in expected] == ["a", "b", "c"]
    for order in permutations(atoms):
        assert ranker.rank_atoms(list(order), task("orchid")) == expected


def test_identical_full_json_duplicates_normalize_without_changing_bm25() -> None:
    first = atom("a", "orchid", extensions={"x-a": 1, "x-b": 2})
    duplicate = atom("a", "orchid", extensions={"x-b": 2, "x-a": 1})
    second = atom("b", "unrelated")
    ranker = FTS5BM25Ranker()
    assert ranker.rank_atoms(
        [first, duplicate, second], task("orchid")
    ) == ranker.rank_atoms([first, second], task("orchid"))


@pytest.mark.parametrize(
    "changes",
    [
        {"statement": "altered"},
        {"authority": "other"},
        {"extensions": {"x-data": "changed"}},
    ],
)
def test_same_id_with_different_full_atom_json_fails(changes: dict[str, Any]) -> None:
    first = atom("same", "orchid")
    second = (
        atom("same", "orchid", **changes)
        if "statement" not in changes
        else atom("same", "altered")
    )
    with pytest.raises(CompileError, match="^AMBIGUOUS_ATOM_ID$"):
        FTS5BM25Ranker().rank_atoms([first, second], task("orchid"))


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "candidate"},
        {"status": "revoked"},
        {"statement": 3},
        {"evidence_refs": ()},
        {"compression_class": "P9"},
        {"scope": ["path:src/a.py"]},
    ],
)
def test_malformed_or_nonformal_atoms_fail_before_ranking(
    changes: dict[str, Any],
) -> None:
    malformed = atom("bad", "orchid").model_copy(update=changes)
    with pytest.raises(CompileError, match="^INVALID_RANKING_INPUT$"):
        FTS5BM25Ranker().rank_atoms([malformed], task("orchid"))


@pytest.mark.parametrize("value", [None, {}, "not-an-atom"])
def test_non_atom_objects_are_rejected(value: Any) -> None:
    with pytest.raises(CompileError, match="^INVALID_RANKING_INPUT$"):
        FTS5BM25Ranker().rank_atoms([value], task())


@pytest.mark.parametrize("nested", [{1: "changed"}, {1: "lost", "1": "kept"}])
@pytest.mark.parametrize("duplicate", [False, True])
def test_original_extension_keys_cannot_be_rewritten_before_validation(
    nested: dict[Any, str], duplicate: bool
) -> None:
    malformed = atom("same", "orchid").model_copy(
        update={"extensions": {"x-data": nested}}
    )
    atoms = [malformed]
    if duplicate:
        atoms.insert(
            0,
            atom(
                "same",
                "orchid",
                extensions={"x-data": {"1": nested.get("1", "changed")}},
            ),
        )
    with pytest.raises(CompileError, match="^INVALID_RANKING_INPUT$"):
        FTS5BM25Ranker().rank_atoms(atoms, task("orchid"))


@pytest.mark.parametrize("duplicate", [False, True])
def test_unknown_nested_model_fields_cannot_disappear_before_validation(
    duplicate: bool,
) -> None:
    valid = atom("same", "orchid")
    malformed = valid.model_copy(
        update={"validity": valid.validity.model_copy(update={"extra": "bad"})}
    )
    with pytest.raises(CompileError, match="^INVALID_RANKING_INPUT$"):
        FTS5BM25Ranker().rank_atoms(
            [valid, malformed] if duplicate else [malformed], task("orchid")
        )


def test_valid_nested_extension_containers_and_full_atom_remain_unchanged() -> None:
    original = atom(
        "nested",
        "orchid",
        extensions={"x-data": {"items": [1, "one", None, True, {"nested": [2.5]}]}},
    )
    result = FTS5BM25Ranker().rank_atoms([original], task("orchid"))
    assert result[0].atom == original
    assert result[0].atom.extensions["x-data"]["items"] == (
        1,
        "one",
        None,
        True,
        {"nested": (2.5,)},
    )


def test_per_call_isolation_returns_only_current_inputs_and_empty_input() -> None:
    ranker = FTS5BM25Ranker()
    ranker.rank_atoms([atom("previous", "orchid")], task("orchid"))
    result = ranker.rank_atoms([atom("current", "orchid")], task("orchid"))
    assert [item.atom.atom_id for item in result] == ["current"]
    assert ranker.rank_atoms([], task("orchid")) == []


def test_connections_close_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    original = sqlite3.connect
    connections: list[sqlite3.Connection] = []

    def connect(database: str) -> sqlite3.Connection:
        assert database == ":memory:"
        connection = original(database)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    ranker = FTS5BM25Ranker()
    ranker.rank_atoms([atom("a", "orchid")], task("orchid"))
    ranker.rank_atoms([], task())
    assert len(connections) == 2
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_connect_failure_is_safe_compile_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(database: str) -> sqlite3.Connection:
        raise sqlite3.OperationalError("private database details")

    monkeypatch.setattr(sqlite3, "connect", fail)
    with pytest.raises(CompileError, match="^RANKING_UNAVAILABLE$") as caught:
        FTS5BM25Ranker().rank_atoms([atom("a", "orchid")], task("orchid"))
    assert caught.value.__suppress_context__ is True


def test_missing_fts5_fails_safely_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = sqlite3.connect(":memory:")
    connection.set_authorizer(lambda *_: sqlite3.SQLITE_DENY)
    monkeypatch.setattr(sqlite3, "connect", lambda _: connection)
    with pytest.raises(CompileError, match="^RANKING_UNAVAILABLE$"):
        FTS5BM25Ranker().rank_atoms([atom("a", "orchid")], task())
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_ranker_is_frozen_and_digest_binds_sqlite_and_service_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranker = FTS5BM25Ranker()
    assert ranker.config_digest == FTS5BM25Ranker().config_digest
    assert ranker.config_digest.startswith("sha256:")
    assert ranker.config_digest != FTS5BM25Ranker(version="2.0.0").config_digest
    before = ranker.config_digest
    monkeypatch.setattr(sqlite3, "sqlite_version", "changed")
    assert FTS5BM25Ranker().config_digest != before
    with pytest.raises(FrozenInstanceError):
        mutable: Any = ranker
        mutable.version = "changed"
