"""Deterministic atom extraction and exact source-map binding for M3."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

import yaml

from contractcapsule.audit.quarantine import (
    CandidateAtom,
    EvidenceBinding,
    QuarantineError,
    TrustLevel,
    candidate_digest_for,
    scan_secrets,
)
from contractcapsule.build.ingest import SourceSnapshot
from contractcapsule.models.canonical import canonical_json_bytes


@dataclass(frozen=True, slots=True)
class _ExtractedSpan:
    statement: str
    kind: str
    start_line: int
    end_line: int
    symbol_or_heading: str


def _modality(statement: str) -> Literal["MUST", "SHOULD", "MAY", "INFORMATIVE"]:
    for value in ("MUST", "SHOULD", "MAY"):
        if re.search(rf"\b{value}\b", statement):
            return value
    return "INFORMATIVE"


def _markdown_spans(text: str) -> list[_ExtractedSpan]:
    result: list[_ExtractedSpan] = []
    current_heading = "document"
    for line_number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            continue
        heading = re.fullmatch(r"#{1,6}\s+(.+?)\s*#*", stripped)
        if heading:
            current_heading = heading.group(1).strip()
            result.append(
                _ExtractedSpan(
                    current_heading, "fact", line_number, line_number, current_heading
                )
            )
            continue
        if stripped.startswith("<!--"):
            continue
        kind = "policy" if _modality(stripped) != "INFORMATIVE" else "fact"
        result.append(
            _ExtractedSpan(stripped, kind, line_number, line_number, current_heading)
        )
    return result


def _python_spans(text: str) -> list[_ExtractedSpan]:
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        raise QuarantineError("deterministic Python parsing failed") from error
    lines = text.splitlines()
    result: list[_ExtractedSpan] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        line = lines[node.lineno - 1].strip()
        result.append(
            _ExtractedSpan(
                statement=line,
                kind="interface",
                start_line=node.lineno,
                end_line=node.lineno,
                symbol_or_heading=node.name,
            )
        )
    return sorted(
        result,
        key=lambda span: (span.start_line, span.end_line, span.symbol_or_heading),
    )


def _config_spans(text: str, parser_kind: str) -> list[_ExtractedSpan]:
    try:
        value = json.loads(text) if parser_kind == "json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise QuarantineError("deterministic configuration parsing failed") from error
    if not isinstance(value, dict):
        raise QuarantineError("configuration source must have an object root")
    lines = text.splitlines()
    result: list[_ExtractedSpan] = []
    for key in value:
        key_text = str(key)
        prefix = "" if parser_kind == "json" else r"^[\t ]*"
        locator = re.compile(
            rf"{prefix}(?:{re.escape(json.dumps(key_text))}|{re.escape(key_text)})[\t ]*:"
        )
        located = next(
            (index for index, line in enumerate(lines) if locator.search(line)), None
        )
        if located is None:
            raise QuarantineError("configuration key cannot be mapped to a source span")
        result.append(
            _ExtractedSpan(
                statement=lines[located].strip(),
                kind="fact",
                start_line=located + 1,
                end_line=located + 1,
                symbol_or_heading=key_text,
            )
        )
    return result


def _text_spans(text: str) -> list[_ExtractedSpan]:
    result: list[_ExtractedSpan] = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        statement = raw.strip()
        if not statement:
            continue
        result.append(
            _ExtractedSpan(
                statement=statement,
                kind="policy" if _modality(statement) != "INFORMATIVE" else "fact",
                start_line=line_number,
                end_line=line_number,
                symbol_or_heading=f"line:{line_number}",
            )
        )
    return result


def _extract(snapshot: SourceSnapshot) -> list[_ExtractedSpan]:
    text = snapshot.text()
    if snapshot.parser_kind == "markdown":
        return _markdown_spans(text)
    if snapshot.parser_kind == "code" and snapshot.relative_path.endswith(".py"):
        return _python_spans(text)
    if snapshot.parser_kind in {"json", "yaml"}:
        return _config_spans(text, snapshot.parser_kind)
    return _text_spans(text)


def _candidate_id(snapshot: SourceSnapshot, span: _ExtractedSpan) -> str:
    identity = {
        "snapshot_id": snapshot.snapshot_id,
        "statement": span.statement,
        "kind": span.kind,
        "start_line": span.start_line,
        "end_line": span.end_line,
        "symbol_or_heading": span.symbol_or_heading,
    }
    return (
        "candidate-" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()[:32]
    )


def extract_candidate_atoms(snapshot: SourceSnapshot) -> list[CandidateAtom]:
    """Extract deterministic candidates and register every one in quarantine."""

    if not isinstance(snapshot, SourceSnapshot):
        raise TypeError("snapshot must be a SourceSnapshot")
    if not snapshot.quarantine.is_registered_snapshot(snapshot):
        raise QuarantineError("snapshot did not pass the ingestion boundary")
    snapshot.assert_current()
    spans = _extract(snapshot)
    if not spans:
        raise QuarantineError("source produced no deterministic candidate atoms")
    candidates: list[CandidateAtom] = []
    source_trust = TrustLevel.T3 if snapshot.generated else TrustLevel.T2
    for span in spans:
        candidate_id = _candidate_id(snapshot, span)
        candidate = CandidateAtom(
            candidate_id=candidate_id,
            atom_id="atom-" + candidate_id.removeprefix("candidate-"),
            kind=span.kind,
            statement=span.statement,
            modality=_modality(span.statement),
            scope=(f"path:{snapshot.relative_path}",),
            source_snapshot_id=snapshot.snapshot_id,
            start_line=span.start_line,
            end_line=span.end_line,
            symbol_or_heading=span.symbol_or_heading,
            compression_class="P1_STRUCTURED",
            generated=snapshot.generated,
            trust_level=source_trust,
        )
        object.__setattr__(
            candidate, "_quarantine_token", snapshot.quarantine.candidate_token()
        )
        snapshot.quarantine.register_candidate(candidate)
        candidates.append(candidate)
    return candidates


def bind_evidence(atom: CandidateAtom, snapshot: SourceSnapshot) -> EvidenceBinding:
    """Bind a registered candidate to exact source bytes after drift/secret checks."""

    if not isinstance(atom, CandidateAtom) or not isinstance(snapshot, SourceSnapshot):
        raise TypeError("bind_evidence requires CandidateAtom and SourceSnapshot")
    if atom.source_snapshot_id != snapshot.snapshot_id:
        raise QuarantineError("candidate and snapshot do not match")
    if snapshot.quarantine.candidate(atom.candidate_id) != atom:
        raise QuarantineError("candidate is not the registered quarantined value")
    snapshot.assert_current()
    span = snapshot.line_span(atom.start_line, atom.end_line)
    scan_secrets(span)
    span_digest = "sha256:" + hashlib.sha256(span).hexdigest()
    identity = {
        "candidate_digest": candidate_digest_for(atom),
        "snapshot_id": snapshot.snapshot_id,
        "content_digest": snapshot.content_digest,
        "span_digest": span_digest,
        "mode": snapshot.mode,
    }
    binding = EvidenceBinding(
        binding_id="evidence-"
        + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()[:32],
        candidate_id=atom.candidate_id,
        snapshot_id=snapshot.snapshot_id,
        mode=snapshot.mode,
        content_digest=snapshot.content_digest,
        span_digest=span_digest,
        media_type=snapshot.media_type,
        captured_at=snapshot.captured_at,
        access_policy=snapshot.access_policy,
        repository=snapshot.repository,
        revision=snapshot.revision,
        path=snapshot.relative_path,
        symbol_or_heading=atom.symbol_or_heading,
        start_line=atom.start_line,
        end_line=atom.end_line,
        uri=snapshot.uri,
        source=snapshot.source,
        verification_method=snapshot.verification_method,
        source_bytes=snapshot.content,
    )
    snapshot.quarantine.register_binding(binding)
    return binding


def render_evidence(binding: EvidenceBinding, snapshot: SourceSnapshot) -> str:
    """Render an exact source span only after rebinding and secret checks."""

    if binding.snapshot_id != snapshot.snapshot_id:
        raise QuarantineError("binding and snapshot do not match")
    snapshot.assert_current()
    start = binding.start_line or 1
    end = binding.end_line or len(snapshot.lines())
    span = snapshot.line_span(start, end)
    actual = "sha256:" + hashlib.sha256(span).hexdigest()
    if actual != binding.span_digest:
        raise QuarantineError("evidence span digest mismatch")
    scan_secrets(span)
    return span.decode("utf-8", errors="strict")
