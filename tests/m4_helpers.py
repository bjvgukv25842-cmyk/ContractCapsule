"""Real M3 publication fixtures, with isolated pre-publication test authoring.

Candidate identity/scope/class edits precede evidence binding and approval.
Optional core edits apply only to an unpublished draft, which is then loaded
again and receives real loader attestation and a real Registry publication permit.
No fixture constructs proof objects or edits a published artifact in place.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from contractcapsule.audit.quarantine import ValidatedAtom
from contractcapsule.build.atomize import bind_evidence, extract_candidate_atoms
from contractcapsule.build.ingest import SourceInput, snapshot_source
from contractcapsule.build.publish import (
    BuildRequest,
    _loader_attestation,
    _validate_through_loader,
    build_capsule,
)
from contractcapsule.models.base import Principal
from contractcapsule.models.canonical import capsule_wire_dict
from contractcapsule.storage.cas import FilesystemCAS
from contractcapsule.storage.registry import PolicyDecision, PublishedCapsule, Registry
from tests.m2_helpers import TrustedM3TestHarness, capsule_with_digest


class FixtureRegistryPolicy:
    def resolve(
        self, principal: Principal, action: str, authority: str, scope: object
    ) -> PolicyDecision:
        del authority, scope
        allowed = (principal.principal_id, action) in {
            ("publisher", "publish"),
            ("reader", "read"),
        }
        return PolicyDecision(allowed, frozenset({"team-auth", "team-other"}))


@dataclass
class M4Fixture:
    harness: TrustedM3TestHarness
    registry: Registry
    serial: int = 0

    @classmethod
    def create(cls, root: Path) -> M4Fixture:
        cas = FilesystemCAS(root / "cas")
        harness = TrustedM3TestHarness.create(root, cas)
        registry = Registry(
            root / "registry.sqlite3",
            cas,
            FixtureRegistryPolicy(),
            trust_root=harness.authority.trust_root(),
        )
        return cls(harness, registry)

    def _promote(self, index: int, options: Mapping[str, Any]) -> ValidatedAtom:
        source_path = self.harness.root / f"source-{self.serial}-{index}.txt"
        source_path.write_text(options.get("statement", f"Rule {index} must hold.\n"))
        snapshot = snapshot_source(
            SourceInput(
                path=source_path,
                cas=self.harness.cas,
                quarantine=self.harness.store,
                access_policy=options.get("access_policy", "team-auth"),
                generated=True,
            ),
            self.harness.principal,
        )
        candidate = extract_candidate_atoms(snapshot)[0]
        for name, default in (
            ("atom_id", f"atom-{index}"),
            ("scope", ("path:src/**",)),
            ("compression_class", "P1_STRUCTURED"),
        ):
            object.__setattr__(candidate, name, options.get(name, default))
        binding = bind_evidence(candidate, snapshot)
        approval = self.harness.authority.issue(candidate, (binding,), "reviewer")
        return self.harness.store.promote(candidate.candidate_id, approval)

    def publish(
        self,
        *,
        capsule_id: str = "com.example.policy",
        version: str = "1.0.0",
        provides: tuple[str, ...] = (),
        atoms: tuple[Mapping[str, Any], ...] | None = None,
        amend: Callable[[dict[str, Any]], None] | None = None,
    ) -> PublishedCapsule:
        self.serial += 1
        authored = ({},) if atoms is None else atoms
        validated = tuple(
            self._promote(index, item) for index, item in enumerate(authored)
        )
        draft = build_capsule(
            BuildRequest(
                atoms=validated,
                quarantine=self.harness.store,
                capsule_id=capsule_id,
                version=version,
                tenant="example",
                authority="approved-project-policy",
                lifecycle="PUBLISHED",
                environments=("prod", "dev"),
                package_path=self.harness.root / f"draft-{self.serial}",
                detached_signature={
                    "algorithm": "m3-test-only",
                    "key_id": "m3-test-key",
                    "value": "test-envelope-not-production",
                    "envelope": {},
                },
            )
        )
        raw = capsule_wire_dict(draft.capsule)
        raw["control_manifest"]["scope"] = {
            "repositories": ["example/api"],
            "paths": ["src/**"],
            "environments": ["prod", "dev"],
        }
        raw["control_manifest"]["provides"] = list(provides)
        if amend is not None:
            amend(raw)
        capsule = capsule_with_digest(raw)
        store = self.harness.store
        blobs = {
            binding.content_digest: binding.source_bytes
            for atom in validated
            for binding in atom.evidence_bindings
        }
        loaded, path, receipt = _validate_through_loader(
            capsule,
            blobs,
            self.harness.root / f"publication-{self.serial}",
            store._loader_capability(),
            store._loader_identity,
        )
        attestation = _loader_attestation(
            loaded, path, receipt, store._loader_identity, store._loader_capability()
        )
        permit = store.issue_publication_permit(
            loaded,
            validated,
            self.harness.principal,
            loader_attestation=attestation,
        )
        return self.registry.publish(
            loaded, self.harness.principal, publication_permit=permit
        )
