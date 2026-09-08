"""B-zone audit projection: participating identities and admitted decisions only."""

from __future__ import annotations

from typing import TYPE_CHECKING

from contractcapsule.models.view import (
    DecisionRecord,
    ServiceStamp,
    TokenAccounting,
    ValidationReport,
    ViewManifest,
)
from contractcapsule.resolve.policies import snapshot_digest

if TYPE_CHECKING:
    from contractcapsule.compile.session import Compilation

_COMPILER_VERSION = "0.1.2"


def build_manifest(
    session: Compilation, report: ValidationReport, *, redact: bool = False
) -> ViewManifest:
    admission, graph = session.admission, session.graph
    empty_digest = "sha256:" + "0" * 64
    metadata = {
        "task_id": "invalid-request",
        "tenant": "invalid-request",
        "repository": "invalid-request",
        "as_of": "1970-01-01T00:00:00Z",
        "task_digest": empty_digest,
        "request_digest": empty_digest,
        "model_id": "invalid-request",
        "tokenizer_profile": "invalid-request",
        "renderer_version": "invalid-request",
    }
    metadata.update(session.metadata)
    if redact:
        return _withheld_manifest(session, report, metadata)
    participating = (
        {}
        if graph is None
        else {
            ref.key: ref
            for atom_id in session.selected
            for ref in graph.owners[atom_id]
        }
    )
    decisions = (
        ()
        if graph is None
        else tuple(
            DecisionRecord(
                capsule=ref,
                atom_id=atom_id,
                outcome="selected" if atom_id in session.selected else "excluded",
                reason=session.reasons.get(atom_id, "COMPILATION_BLOCKED"),
            )
            for atom_id in graph.atoms
            for ref in graph.owners[atom_id]
        )
    )
    services = list(session.services)
    services.append(_compiler_stamp())
    if graph is not None:
        services.append(
            ServiceStamp(
                name="graph", version=graph.version, config_digest=graph.config_digest
            )
        )
    if admission is not None:
        services.append(
            ServiceStamp(
                name="eligibility",
                version="1.0.0",
                config_digest=snapshot_digest(
                    {
                        "permission": admission.permission_digest,
                        "freshness": admission.freshness_digest,
                    }
                ),
            )
        )
    providers = (
        ()
        if graph is None
        else tuple(
            witness
            for witness in graph.providers
            if (witness.consumer is None or witness.consumer.key in participating)
            and set(witness.atom_ids) <= session.selected
            and (
                not witness.requirement.startswith("requires:")
                or witness.requirement in _realized_requirements(session)
            )
        )
    )
    # Contradictory selected versions have no valid participating identity projection.
    refs = tuple(participating.values())
    if len({ref.capsule_id for ref in refs}) != len(refs):
        refs = ()
    return ViewManifest.model_validate(
        {
            **metadata,
            "compiler_version": _COMPILER_VERSION,
            "permission_digest": admission.permission_digest
            if admission
            else empty_digest,
            "capsules": refs,
            "decisions": decisions,
            "providers": providers,
            "conflicts": session.conflicts,
            "closure": graph.closure_links(session.selected)
            if graph and report.valid
            else (),
            "rejected_counts": admission.rejected_counts if admission else {},
            "services": tuple(services),
            "expanded_evidence": session.expanded if report.valid else (),
            "tokens": session.tokens,
            "validation": report,
        }
    )


def _compiler_stamp() -> ServiceStamp:
    return ServiceStamp(
        name="compiler",
        version=_COMPILER_VERSION,
        config_digest=snapshot_digest(
            {
                "profile": "CCS-2.1-m4-collective-interfaces-v1",
                "version": _COMPILER_VERSION,
            }
        ),
    )


def _withheld_manifest(
    session: Compilation, report: ValidationReport, metadata: dict[str, str]
) -> ViewManifest:
    # Retain transaction evidence internally, never export an invalidated snapshot.
    return ViewManifest.model_validate(
        {
            **metadata,
            "compiler_version": _COMPILER_VERSION,
            "request_digest": "sha256:" + "0" * 64,
            "permission_digest": "sha256:" + "0" * 64,
            "services": (_compiler_stamp(),),
            "rejected_counts": {
                "AUTHORIZATION_SNAPSHOT_INVALIDATED": len(session.admission.items)
                if session.admission is not None
                else 0,
            },
            "tokens": TokenAccounting(
                total=0,
                available=session.tokens.available,
                sections={},
                boundary_adjustment=0,
            ),
            "validation": report,
        }
    )


def _realized_requirements(session: Compilation) -> set[str]:
    if session.graph is None:
        return set()
    return {
        f"requires:{link.source}->{link.target.replace('__ccs_m4__:unit:', '__ccs_m4__:presence:', 1)}"
        for link in session.graph.closure_links(session.selected)
    }
