"""Deterministic lexical ranking of already-admitted formal atoms."""

import hashlib
import re
import sqlite3
import unicodedata
from contextlib import closing
from dataclasses import dataclass

from pydantic import TypeAdapter

from contractcapsule.compile.errors import CompileError
from contractcapsule.models.base import SemVer
from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.models.core import Atom, Validity
from contractcapsule.models.view import RankedAtom, TaskContext

_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_CREATE = (
    "CREATE VIRTUAL TABLE atoms USING fts5("
    "atom_id UNINDEXED, statement, tokenize='unicode61')"
)
_INSERT = "INSERT INTO atoms(atom_id, statement) VALUES (?, ?)"
_MATCH = "SELECT atom_id, bm25(atoms) FROM atoms WHERE atoms MATCH ?"


def _validated_atom(atom: Atom) -> Atom:
    try:
        if type(atom) is not Atom or set(vars(atom)) != set(Atom.model_fields):
            raise ValueError("invalid atom type or fields")
        if type(atom.validity) is not Validity or set(vars(atom.validity)) != set(
            Validity.model_fields
        ):
            raise ValueError("invalid validity type or fields")
        # Validate original data before serializers can rewrite keys or omit fields.
        values = dict(vars(atom))
        validity = dict(vars(atom.validity))
        validity["from"] = validity.pop("from_")
        values["validity"] = validity
        checked = Atom.model_validate(values)
        if checked.status != "validated":
            raise ValueError("formal atom required")
        return checked
    except (TypeError, ValueError, AttributeError):
        raise CompileError("INVALID_RANKING_INPUT") from None


def _unique_atoms(atoms: list[Atom]) -> list[Atom]:
    if type(atoms) is not list:
        raise CompileError("INVALID_RANKING_INPUT")
    unique: dict[str, Atom] = {}
    canonical: dict[str, bytes] = {}
    for atom in atoms:
        checked = _validated_atom(atom)
        data = canonical_json_bytes(checked.model_dump(mode="json", by_alias=True))
        if checked.atom_id in canonical and canonical[checked.atom_id] != data:
            raise CompileError("AMBIGUOUS_ATOM_ID")
        canonical[checked.atom_id] = data
        unique[checked.atom_id] = checked
    return [unique[key] for key in sorted(unique)]


def _literal_query(task: TaskContext) -> str:
    try:
        if type(task) is not TaskContext:
            raise ValueError("invalid task type")
        checked = TaskContext.model_validate(
            task.model_dump(mode="python", warnings="error")
        )
    except (TypeError, ValueError, AttributeError):
        raise CompileError("INVALID_RANKING_INPUT") from None
    text = " ".join(
        (checked.text, *checked.required_atom_ids, *checked.required_interfaces)
    )
    return " OR ".join(f'"{word}"' for word in sorted(set(_WORDS.findall(text))))


def _scores(atoms: list[Atom], query: str) -> dict[str, float]:
    try:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.execute(_CREATE)
            connection.executemany(
                _INSERT, [(atom.atom_id, atom.statement) for atom in atoms]
            )
            if not query:
                return {}
            return dict(connection.execute(_MATCH, (query,)).fetchall())
    except sqlite3.Error:
        raise CompileError("RANKING_UNAVAILABLE") from None


@dataclass(frozen=True)
class FTS5BM25Ranker:
    """Stateless B-zone service; the caller must admit candidates before ranking."""

    version: str = "1.0.0"

    def __post_init__(self) -> None:
        try:
            TypeAdapter(SemVer).validate_python(self.version, strict=True)
        except (TypeError, ValueError):
            raise CompileError("INVALID_CONFIGURATION") from None

    @property
    def config_digest(self) -> str:
        config = {
            "profile": "CCS-2.1-m4-fts5-bm25-v1",
            "version": self.version,
            "sqlite_version": sqlite3.sqlite_version,
            "unicode_version": unicodedata.unidata_version,
            "schema": _CREATE,
            "insert": _INSERT,
            "match": _MATCH,
            "words": _WORDS.pattern,
            "word_flags": _WORDS.flags,
            "query": "text+required_atom_ids+required_interfaces;sorted-unique;literal-OR",
            "insertion": "atom_id-ascending;canonical-full-atom-duplicate-equality",
            "ordering": "compression_class,matched-desc,score-asc,atom_id",
            "unmatched": 0.0,
        }
        return "sha256:" + hashlib.sha256(canonical_json_bytes(config)).hexdigest()

    def rank_atoms(self, atoms: list[Atom], task: TaskContext) -> list[RankedAtom]:
        candidates = _unique_atoms(atoms)
        scores = _scores(candidates, _literal_query(task))
        ranked = [
            RankedAtom(
                atom=atom,
                score=scores.get(atom.atom_id, 0.0),
                matched=atom.atom_id in scores,
            )
            for atom in candidates
        ]
        return sorted(
            ranked,
            key=lambda item: (
                item.atom.compression_class,
                not item.matched,
                item.score,
                item.atom.atom_id,
            ),
        )
