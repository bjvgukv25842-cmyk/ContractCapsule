"""Public canonical data model for CCS-2.1 M2."""

from contractcapsule.models.base import Principal
from contractcapsule.models.canonical import canonical_digest
from contractcapsule.models.core import (
    Capsule,
    CASEvidence,
    CompressionPolicy,
    ControlManifest,
    DependencyGraph,
    EvidencePlane,
    ExternalImmutableEvidence,
    GitImmutableEvidence,
    ReplacementContract,
    SemanticPayload,
    TestsIntegrity,
)

__all__ = [
    "CASEvidence",
    "Capsule",
    "CompressionPolicy",
    "ControlManifest",
    "DependencyGraph",
    "EvidencePlane",
    "ExternalImmutableEvidence",
    "GitImmutableEvidence",
    "Principal",
    "ReplacementContract",
    "SemanticPayload",
    "TestsIntegrity",
    "canonical_digest",
]
