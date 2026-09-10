"""Read and check source bindings independently of the compiler session."""

import hashlib

from contractcapsule.compile.errors import CompileError
from contractcapsule.compile.evidence import NativeEvidenceResolver, _source_span
from contractcapsule.compile.validation import original_values
from contractcapsule.models.view import CompileRequest, EvidenceMaterial
from contractcapsule.resolve.graph import ResolvedGraph


def verified_materials(
    graph: ResolvedGraph,
    request: CompileRequest,
    resolver: NativeEvidenceResolver,
    now: str,
) -> dict[str, tuple[EvidenceMaterial, ...]]:
    result = {}
    for atom_id, atom in graph.atoms.items():
        sources = {}
        for owner in graph.owners[atom_id]:
            publication = graph.publications[owner.key]
            materials = resolver.resolve(
                publication, atom, request.principal, request.task, now
            )
            records = {
                record.evidence_id: record
                for record in publication.capsule.evidence_plane.records
            }
            if type(materials) is not tuple or {
                m.handle.evidence_id for m in materials
            } != set(atom.evidence_refs):
                raise CompileError("EVIDENCE_INTEGRITY")
            for material in materials:
                EvidenceMaterial.model_validate(original_values(material))
                handle = material.handle
                record = records[handle.evidence_id]
                excerpt, span = _source_span(record, material.full_text.encode("utf-8"))
                members = tuple(
                    sorted(
                        key
                        for key in record.atom_ids
                        if owner in graph.owners.get(key, ())
                    )
                )
                actual_digest = (
                    "sha256:"
                    + hashlib.sha256(material.full_text.encode("utf-8")).hexdigest()
                )
                if (
                    handle.capsule != owner
                    or handle.atom_ids != members
                    or handle.content_digest != record.content_digest
                    or handle.content_digest != actual_digest
                    or handle.mode != record.mode
                    or handle.span_digest != span
                    or handle.resolver_version != resolver.version
                    or material.excerpt != excerpt
                ):
                    raise CompileError("EVIDENCE_INTEGRITY")
                sources[handle.handle_id] = material
        result[atom_id] = tuple(sources[key] for key in sorted(sources))
    return result
