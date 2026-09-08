"""One deterministic compilation transaction; no persistent state or activation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from importlib.metadata import version as distribution_version
from typing import TYPE_CHECKING

from contractcapsule.compile.budget import account_tokens, rendered_content
from contractcapsule.compile.errors import CompileError
from contractcapsule.compile.evidence import NativeEvidenceResolver, _source_span
from contractcapsule.compile.renderers import NeutralViewRenderer
from contractcapsule.compile.validation import (
    expansion_ids,
    original_values,
    scan,
    stamp,
)
from contractcapsule.models.view import (
    CompiledView,
    CompileRequest,
    Conflict,
    EvidenceMaterial,
    RankedAtom,
    ServiceStamp,
    TokenAccounting,
    ValidationReport,
    compile_request_projection,
    view_manifest_digest,
)
from contractcapsule.resolve.eligibility import AdmissionResult, EligibilityResolver
from contractcapsule.resolve.graph import ResolvedGraph, resolve_graph
from contractcapsule.resolve.policies import snapshot_digest

if TYPE_CHECKING:
    from contractcapsule.compile.compiler import ViewCompiler

_SAFE_CODES = frozenset(
    {
        "INVALID_REQUEST",
        "INVALID_CONFIGURATION",
        "SECRET_DETECTED",
        "COMPILATION_FAILED",
        "INVALID_POLICY_SNAPSHOT",
        "POLICY_SNAPSHOT_CHANGED",
        "MISSING_ATOM",
        "MISSING_DEPENDENCY",
        "MISSING_INTERFACE",
        "AMBIGUOUS_PROVIDER",
        "INVALID_VERSION_CONSTRAINT",
        "INVALID_GRAPH",
        "DUPLICATE_ATOM",
        "AMBIGUOUS_GRAPH_NODE",
        "CONFLICT",
        "RANKING_FAILED",
        "RANKING_UNAVAILABLE",
        "EVIDENCE_UNAVAILABLE",
        "EVIDENCE_UNAUTHORIZED",
        "EVIDENCE_INTEGRITY",
        "TOKENIZER_UNAVAILABLE",
        "TOKENIZER_INTEGRITY",
        "RENDERING_FAILED",
        "P0_OVERFLOW",
        "P1_OVERFLOW",
        "EXPANSION_OVERFLOW",
        "REPLAY_MISMATCH",
        "SERVICE_SNAPSHOT_CHANGED",
        "FINAL_PRESERVATION_FAILED",
    }
)


@dataclass
class Compilation:
    compiler: ViewCompiler
    request: CompileRequest | None = None
    admission: AdmissionResult | None = None
    graph: ResolvedGraph | None = None
    services: tuple[ServiceStamp, ...] = ()
    ranked: tuple[RankedAtom, ...] = ()
    evidence: dict[str, tuple[EvidenceMaterial, ...]] = field(default_factory=dict)
    selected: set[str] = field(default_factory=set)
    reasons: dict[str, str] = field(default_factory=dict)
    expanded: tuple[str, ...] = ()
    tokens: TokenAccounting = field(
        default_factory=lambda: TokenAccounting(
            total=0,
            available=0,
            sections={},
            boundary_adjustment=0,
        )
    )
    content: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    conflicts: tuple[Conflict, ...] = ()

    def _service_snapshot(self) -> tuple[ServiceStamp, ...]:
        compiler = self.compiler
        services = tuple(
            stamp(name, service)
            for name, service in (
                ("ranker", compiler.ranker),
                ("tokenizer", compiler.counter),
                ("renderer", compiler.renderer),
                ("evidence", compiler.evidence),
            )
        )
        version = distribution_version("semantic-version")
        return services + (
            ServiceStamp(
                name="semver",
                version=version,
                config_digest=snapshot_digest(
                    {
                        "library": "semantic-version",
                        "version": version,
                        "constraint": "comma-conjunction;==,!=,>=,<=,>,<;numeric-shorthand",
                        "precedence": "truncate-prerelease;exact-build-metadata-locks",
                        "interface": "exact-vN;release-version-independent",
                    }
                ),
            ),
        )

    def _configure(self, request: CompileRequest) -> EligibilityResolver:
        compiler = self.compiler
        if (
            type(compiler.evidence) is not NativeEvidenceResolver
            or compiler.evidence.registry is not compiler.registry
            or compiler.evidence.authorizer is not compiler.authorizer
            or compiler.evidence.freshness is not compiler.freshness
            or compiler.counter.model_id != request.model_id
            or compiler.counter.profile != request.tokenizer_profile
            or compiler.renderer.version != request.renderer_version
        ):
            raise CompileError("INVALID_CONFIGURATION")
        self.expanded = expansion_ids(request, compiler.renderer)
        self.services = self._service_snapshot()
        return EligibilityResolver(
            compiler.registry,
            compiler.authorizer,
            compiler.freshness,
            request.as_of,
        )

    def _sources(
        self, graph: ResolvedGraph, request: CompileRequest
    ) -> dict[str, tuple[EvidenceMaterial, ...]]:
        result: dict[str, tuple[EvidenceMaterial, ...]] = {}
        for atom_id, atom in graph.atoms.items():
            materials: dict[str, EvidenceMaterial] = {}
            for owner in graph.owners[atom_id]:
                sources = self.compiler.evidence.resolve(
                    graph.publications[owner.key],
                    atom,
                    request.principal,
                    request.task,
                    request.as_of,
                )
                if type(sources) is not tuple or not sources:
                    raise CompileError("EVIDENCE_INTEGRITY")
                for source in sources:
                    self._verify_source(source, atom_id, owner.key)
                    self._verify_binding(source, graph, owner.key)
                    materials[source.handle.handle_id] = source
                if {source.handle.evidence_id for source in sources} != set(
                    atom.evidence_refs
                ):
                    raise CompileError("EVIDENCE_INTEGRITY")
            result[atom_id] = tuple(materials[key] for key in sorted(materials))
        return result

    def _verify_binding(
        self, source: EvidenceMaterial, graph: ResolvedGraph, owner: str
    ) -> None:
        records = {
            record.evidence_id: record
            for record in graph.publications[owner].capsule.evidence_plane.records
        }
        record = records.get(source.handle.evidence_id)
        if record is None:
            raise CompileError("EVIDENCE_INTEGRITY")
        members = tuple(
            sorted(
                atom_id
                for atom_id in record.atom_ids
                if any(ref.key == owner for ref in graph.owners.get(atom_id, ()))
            )
        )
        excerpt, span_digest = _source_span(record, source.full_text.encode("utf-8"))
        if (
            source.handle.atom_ids != members
            or source.handle.content_digest != record.content_digest
            or source.handle.mode != record.mode
            or source.handle.span_digest != span_digest
            or source.handle.resolver_version != self.compiler.evidence.version
            or source.excerpt != excerpt
        ):
            raise CompileError("EVIDENCE_INTEGRITY")

    @staticmethod
    def _verify_source(source: EvidenceMaterial, atom_id: str, owner: str) -> None:
        import hashlib

        if type(source) is not EvidenceMaterial:
            raise CompileError("EVIDENCE_INTEGRITY")
        EvidenceMaterial.model_validate(original_values(source))
        if (
            source.handle.capsule.key != owner
            or atom_id not in source.handle.atom_ids
            or "sha256:" + hashlib.sha256(source.full_text.encode()).hexdigest()
            != source.handle.content_digest
        ):
            raise CompileError("EVIDENCE_INTEGRITY")
        if source.handle.span_digest is not None and (
            "sha256:" + hashlib.sha256(source.excerpt.encode()).hexdigest()
            != source.handle.span_digest
        ):
            raise CompileError("EVIDENCE_INTEGRITY")
        scan(source.model_dump(mode="json"))

    def _rank(self, graph: ResolvedGraph, request: CompileRequest) -> None:
        try:
            results = self.compiler.ranker.rank_atoms(
                list(graph.atoms.values()), request.task
            )
            if type(results) is not list or len(results) != len(graph.atoms):
                raise CompileError("RANKING_FAILED")
            seen: set[str] = set()
            for result in results:
                if type(result) is not RankedAtom:
                    raise CompileError("RANKING_FAILED")
                RankedAtom.model_validate(original_values(result))
                atom_id = result.atom.atom_id
                if (
                    atom_id in seen
                    or result.atom != graph.atoms.get(atom_id)
                    or not math.isfinite(result.score)
                ):
                    raise CompileError("RANKING_FAILED")
                seen.add(atom_id)
            self.ranked = tuple(results)
        except Exception:  # noqa: BLE001 - ranker faults cannot disclose rejected payloads.
            raise CompileError("RANKING_FAILED") from None

    def _render(
        self, selected: set[str], *, expanded: bool = False
    ) -> tuple[str, TokenAccounting]:
        assert self.request is not None
        atoms = tuple(item for item in self.ranked if item.atom.atom_id in selected)
        sources = {
            source.handle.handle_id: source
            for atom_id in sorted(selected)
            for source in self.evidence[atom_id]
        }
        ids = self.expanded if expanded else ()
        if not set(ids) <= sources.keys():
            raise CompileError("EVIDENCE_UNAVAILABLE")
        for handle_id in ids:
            source = sources[handle_id]
            refreshed = self.compiler.evidence.expand(
                source.handle,
                self.request.principal,
                self.request.task,
                self.request.as_of,
            )
            if refreshed != source:
                raise CompileError("EVIDENCE_INTEGRITY")
        material = tuple(sources[key] for key in sorted(sources))
        renderer = self.compiler.renderer
        if type(renderer) is NeutralViewRenderer:
            renderer = replace(renderer, expanded_handles=ids)
        sections = renderer.render(self.request.task, atoms, material)
        expected = NeutralViewRenderer(expanded_handles=ids).render(
            self.request.task, atoms, material
        )
        if sections != expected:
            raise CompileError("RENDERING_FAILED")
        return rendered_content(sections), account_tokens(
            sections, self.compiler.counter, self.request.budget
        )

    def _mandatory(self, seeds: set[str], reason: str, overflow: str) -> None:
        assert self.graph is not None
        closed = self.graph.close_atoms(self.selected | seeds)
        self.conflicts = self.graph.conflicts_for(closed)
        if self.conflicts:
            raise CompileError("CONFLICT")
        for atom_id in closed - self.selected:
            self.reasons[atom_id] = (
                reason if atom_id in seeds else "DEPENDENCY_REQUIRED"
            )
        self.selected = closed
        self.content, self.tokens = self._render(closed)
        if self.tokens.total > self.tokens.available:
            raise CompileError(overflow)

    def _select(self, request: CompileRequest, graph: ResolvedGraph) -> None:
        self.reasons = {atom_id: "NOT_RELEVANT" for atom_id in graph.atoms}
        p0 = {
            key
            for key, atom in graph.atoms.items()
            if atom.compression_class == "P0_EXACT"
        }
        self._mandatory(p0, "P0_REQUIRED", "P0_OVERFLOW")
        p1 = {
            item.atom.atom_id
            for item in self.ranked
            if item.matched and item.atom.compression_class == "P1_STRUCTURED"
        }
        self._mandatory(
            p1 | set(request.task.required_atom_ids) | set(graph.root_atom_ids),
            "TASK_REQUIRED",
            "P1_OVERFLOW",
        )
        # Stable sorting preserves the ranker's order within each fixed class.
        for item in sorted(self.ranked, key=lambda item: item.atom.compression_class):
            atom_id = item.atom.atom_id
            if atom_id in self.selected or not item.matched:
                continue
            closed = graph.close_atoms(self.selected | {atom_id})
            self.conflicts = graph.conflicts_for(closed)
            if self.conflicts:
                raise CompileError("CONFLICT")
            content, tokens = self._render(closed)
            if tokens.total > tokens.available:
                self.reasons[atom_id] = "BUDGET_EXCLUDED"
                continue
            for added in closed - self.selected:
                self.reasons[added] = (
                    "RELEVANT" if added == atom_id else "DEPENDENCY_REQUIRED"
                )
            self.selected, self.content, self.tokens = closed, content, tokens
        if self.expanded:
            self.content, self.tokens = self._render(self.selected, expanded=True)
            if self.tokens.total > self.tokens.available:
                raise CompileError("EXPANSION_OVERFLOW")

    def run(self, request: CompileRequest) -> CompiledView:
        self.metadata = {
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
        self.request = request
        resolver = self._configure(request)
        self.admission = resolver.resolve(
            request.capsules, request.task, request.principal
        )
        graph = resolve_graph(self.admission, request.task)
        self.graph = graph
        self.evidence = self._sources(graph, request)
        graph.close_atoms(
            set(graph.root_atom_ids) | set(request.task.required_atom_ids)
        )
        self._rank(graph, request)
        self._select(request, graph)
        self._final_checks(resolver, graph, request)
        result = self._result(ValidationReport(valid=True))
        if (
            request.expected_manifest_digest is not None
            and view_manifest_digest(result.manifest)
            != request.expected_manifest_digest
        ):
            raise CompileError("REPLAY_MISMATCH")
        return result

    def _final_checks(
        self,
        resolver: EligibilityResolver,
        graph: ResolvedGraph,
        request: CompileRequest,
    ) -> None:
        if (
            snapshot_digest(compile_request_projection(request))
            != self.metadata["request_digest"]
        ):
            raise CompileError("INVALID_REQUEST")
        if (
            graph.close_atoms(self.selected) != self.selected
            or not graph.root_atom_ids <= self.selected
            or not set(request.task.required_atom_ids) <= self.selected
            or graph.conflicts_for(self.selected)
        ):
            raise CompileError("FINAL_PRESERVATION_FAILED")
        if self.evidence != self._sources(graph, request):
            raise CompileError("EVIDENCE_INTEGRITY")
        if self.services != self._service_snapshot():
            raise CompileError("SERVICE_SNAPSHOT_CHANGED")
        if self.admission != resolver.resolve(
            request.capsules, request.task, request.principal
        ):
            raise CompileError("POLICY_SNAPSHOT_CHANGED")

    def failure(self, code: str) -> CompiledView:
        safe = code if code in _SAFE_CODES else "COMPILATION_FAILED"
        return self._result(ValidationReport(valid=False, blockers=(safe,)))

    def _result(self, report: ValidationReport) -> CompiledView:
        from contractcapsule.compile.manifest import build_manifest

        manifest = build_manifest(self, report)
        handles = {
            source.handle.handle_id: source.handle
            for atom_id in self.selected
            for source in self.evidence.get(atom_id, ())
        }
        return CompiledView(
            content=self.content if report.valid else "",
            manifest=manifest,
            validation=report,
            evidence_handles=tuple(handles[key] for key in sorted(handles))
            if report.valid
            else (),
        )
