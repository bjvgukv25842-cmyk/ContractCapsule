"""Independent preservation checks from verified cores, never compiler flags."""

import math
from dataclasses import replace

from contractcapsule.compile.budget import account_tokens, rendered_content
from contractcapsule.compile.compiler import ViewCompiler
from contractcapsule.compile.errors import CompileError
from contractcapsule.compile.manifest import build_manifest
from contractcapsule.compile.renderers import NeutralViewRenderer
from contractcapsule.compile.session import Compilation
from contractcapsule.compile.validation import expansion_ids, original_values
from contractcapsule.models.view import (
    CompiledView,
    CompileRequest,
    EvidenceMaterial,
    RankedAtom,
    TokenAccounting,
    ValidationReport,
    compile_request_projection,
    view_manifest_digest,
)
from contractcapsule.resolve.eligibility import AdmissionResult
from contractcapsule.resolve.graph import ResolvedGraph
from contractcapsule.resolve.policies import snapshot_digest


def _ranked(
    compiler: ViewCompiler, graph: ResolvedGraph, request: CompileRequest
) -> tuple[RankedAtom, ...]:
    ranked = compiler.ranker.rank_atoms(list(graph.atoms.values()), request.task)
    if type(ranked) is not list or len(ranked) != len(graph.atoms):
        raise CompileError("RANKING_FAILED")
    for item in ranked:
        RankedAtom.model_validate(original_values(item))
        if item.atom != graph.atoms.get(item.atom.atom_id) or not math.isfinite(
            item.score
        ):
            raise CompileError("RANKING_FAILED")
    if {item.atom.atom_id for item in ranked} != graph.atoms.keys():
        raise CompileError("RANKING_FAILED")
    return tuple(ranked)


def _membership(
    view: CompiledView,
    graph: ResolvedGraph,
    request: CompileRequest,
    ranked: tuple[RankedAtom, ...],
) -> set[str]:
    decisions = view.manifest.decisions
    expected = {(owner.key, key) for key in graph.atoms for owner in graph.owners[key]}
    if {(d.capsule.key, d.atom_id) for d in decisions} != expected:
        raise CompileError("MEMBERSHIP_INVALID")
    selected = {d.atom_id for d in decisions if d.outcome == "selected"}
    mandatory = {
        key for key, atom in graph.atoms.items() if atom.compression_class == "P0_EXACT"
    }
    mandatory.update(
        item.atom.atom_id
        for item in ranked
        if item.matched and item.atom.compression_class == "P1_STRUCTURED"
    )
    mandatory.update(graph.root_atom_ids)
    mandatory.update(request.task.required_atom_ids)
    if (
        not graph.close_atoms(mandatory) <= selected
        or graph.close_atoms(selected) != selected
    ):
        raise CompileError("MANDATORY_MEMBERSHIP")
    if any((d.outcome == "selected") != (d.atom_id in selected) for d in decisions):
        raise CompileError("MEMBERSHIP_INVALID")
    if graph.conflicts_for(selected) or view.manifest.conflicts:
        raise CompileError("CONFLICT")
    refs = {owner.key: owner for key in selected for owner in graph.owners[key]}
    if tuple(sorted(refs.values(), key=lambda r: r.key)) != view.manifest.capsules:
        raise CompileError("MEMBERSHIP_INVALID")
    if set(graph.closure_links(selected)) != set(view.manifest.closure):
        raise CompileError("CLOSURE_INVALID")
    return selected


def _manifest(
    view: CompiledView,
    request: CompileRequest,
    compiler: ViewCompiler,
    graph: ResolvedGraph,
    admission: AdmissionResult,
    selected: set[str],
) -> None:
    # Reuse only the deterministic wire projection, never Compilation.run/select.
    session = Compilation(compiler, request=request, admission=admission, graph=graph)
    session.selected = selected
    session.tokens = view.manifest.tokens  # independently recounted before this call
    session.reasons = {d.atom_id: d.reason for d in view.manifest.decisions}
    session.expanded = expansion_ids(request, compiler.renderer)
    session.services = session._service_snapshot()
    session.metadata = {
        "task_id": request.task.task_id,
        "tenant": request.task.tenant,
        "repository": request.task.repository,
        "as_of": request.as_of,
        "task_digest": snapshot_digest(request.task.model_dump(mode="json")),
        "request_digest": snapshot_digest(compile_request_projection(request)),
        "model_id": request.model_id,
        "tokenizer_profile": request.tokenizer_profile,
        "renderer_version": request.renderer_version,
    }
    if build_manifest(session, ValidationReport(valid=True)) != view.manifest:
        raise CompileError("MANIFEST_INVALID")
    if (
        request.expected_manifest_digest is not None
        and view_manifest_digest(view.manifest) != request.expected_manifest_digest
    ):
        raise CompileError("REPLAY_MISMATCH")


def check_compression(
    view: CompiledView,
    request: CompileRequest,
    compiler: ViewCompiler,
    graph: ResolvedGraph,
    sources: dict[str, tuple[EvidenceMaterial, ...]],
    admission: AdmissionResult,
) -> TokenAccounting:
    if type(view) is not CompiledView:
        raise CompileError("INVALID_VIEW")
    CompiledView.model_validate(original_values(view))
    if not view.validation.valid or not view.manifest.validation.valid:
        raise CompileError("INVALID_VIEW")
    ranked = _ranked(compiler, graph, request)
    selected = _membership(view, graph, request, ranked)
    material = {s.handle.handle_id: s for key in selected for s in sources[key]}
    materials = tuple(material[key] for key in sorted(material))
    if tuple(s.handle for s in materials) != view.evidence_handles:
        raise CompileError("EVIDENCE_INTEGRITY")
    expanded = expansion_ids(request, compiler.renderer)
    if expanded != view.manifest.expanded_evidence:
        raise CompileError("EVIDENCE_INTEGRITY")
    renderer = NeutralViewRenderer(expanded_handles=expanded)
    atoms = tuple(item for item in ranked if item.atom.atom_id in selected)
    sections = renderer.render(request.task, atoms, materials)
    if type(compiler.renderer) is not NeutralViewRenderer:
        raise CompileError("INVALID_CONFIGURATION")
    configured = replace(compiler.renderer, expanded_handles=expanded)
    if (
        configured.render(request.task, atoms, materials) != sections
        or rendered_content(sections) != view.content
    ):
        raise CompileError("RENDERING_FAILED")
    tokens = account_tokens(sections, compiler.counter, request.budget)
    if tokens != view.manifest.tokens or tokens.total > tokens.available:
        raise CompileError("TOKEN_ACCOUNTING_INVALID")
    _manifest(view, request, compiler, graph, admission, selected)
    # Supplemental only: the independent preservation checks above execute first.
    if compiler.compile_view(request) != view:
        raise CompileError("REPLAY_MISMATCH")
    return tokens
