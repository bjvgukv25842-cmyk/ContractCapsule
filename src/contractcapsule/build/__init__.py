"""M3 source-grounded builder APIs."""

from contractcapsule.build.atomize import (
    bind_evidence,
    extract_candidate_atoms,
    render_evidence,
)
from contractcapsule.build.ingest import SourceInput, SourceSnapshot, snapshot_source
from contractcapsule.build.publish import (
    BuildError,
    BuildRequest,
    DraftCapsule,
    build_capsule,
    publish_draft,
)

__all__ = [
    "BuildError",
    "BuildRequest",
    "DraftCapsule",
    "SourceInput",
    "SourceSnapshot",
    "bind_evidence",
    "build_capsule",
    "extract_candidate_atoms",
    "publish_draft",
    "render_evidence",
    "snapshot_source",
]
