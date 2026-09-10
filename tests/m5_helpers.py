"""Synthetic programs authored before genuine M3 loader/permit publication."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from contractcapsule.build.publish import (
    _LOAD_AND_ISSUE_RECEIPT,
    _loader_attestation,
    _write_package,
)
from contractcapsule.models.canonical import capsule_wire_dict
from contractcapsule.storage.registry import PublishedCapsule
from tests.m2_helpers import capsule_with_digest
from tests.m4_helpers import M4Fixture


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def profile_for(old: PublishedCapsule, contract: dict[str, Any]) -> dict[str, Any]:
    checks = []
    for role, path, phase in (
        ("precondition", "preconditions", "pre"),
        ("static", "verification/static", "post"),
        ("behavioral", "verification/behavioral", "post"),
        ("target", "target_effects", "post"),
        ("invariant", "protected_invariants", "post"),
        ("spillover", "forbidden_spillover", "post"),
        ("differential", "verification/differential", "pair"),
    ):
        values: Any = contract
        for part in path.split("/"):
            values = values[part]
        check: dict[str, Any] = {
            "check_id": role,
            "role": role,
            "phase": phase,
            "clause_path": path + "/0",
            "clause_sha256": digest(values[0].encode()),
            "test_id": role,
            "artifact_ids": [role],
            "argv": [],
            "subject_probes": [],
        }
        if phase == "pair":
            check["pair_expected"] = True
        else:
            check.update(
                old_expected=role not in {"target", "spillover"},
                new_expected=role != "spillover",
            )
        checks.append(check)
    manifest = old.capsule.control_manifest
    return {
        "profile": "ccs-m5-execution/1.0.0",
        "replaces_ref": {
            "capsule_id": manifest.capsule_id,
            "version": manifest.version,
            "digest": manifest.content_digest,
        },
        "accepts_interfaces": list(manifest.provides),
        "checks": checks,
        "executor": {"test_id": "executor", "artifact_ids": ["executor"], "argv": []},
        "runner": {
            "image_digest": "sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203",
            "platform": "linux/arm64",
            "profile": "ccs-m5-docker/1.0.0",
            "cpu_limit": 1,
            "memory_bytes": 1073741824,
            "process_limit": 128,
            "timeout_seconds": 300,
            "stdout_limit_bytes": 4194304,
            "stderr_limit_bytes": 4194304,
            "output_tree_limit_bytes": 67108864,
            "output_tree_file_limit": 10000,
        },
        "repetitions": 3,
    }


@dataclass
class M5Fixture:
    base: M4Fixture
    old: PublishedCapsule
    new: PublishedCapsule
    package: Path

    @classmethod
    def create(
        cls,
        root: Path,
        amend: Callable[[dict[str, Any]], None] | None = None,
        programs: dict[str, bytes] | None = None,
    ) -> M5Fixture:
        base = M4Fixture.create(root)
        old = base.publish(provides=("policy/v1",))
        atom = base.harness.promote_source()
        draft = base.harness.build_draft(
            validated_atom=atom, capsule_id="com.example.next", version="2.0.0"
        )
        raw = capsule_wire_dict(draft.capsule)
        raw["control_manifest"]["scope"] = capsule_wire_dict(old.capsule)[
            "control_manifest"
        ]["scope"]
        raw["control_manifest"]["provides"] = ["policy/v2"]
        contract = raw["replacement_contract"]
        old_name = f"{old.capsule.control_manifest.capsule_id}@1.0.0"
        contract.update(
            replaces=old_name,
            preconditions=["initial valid"],
            target_effects=["target changed"],
            protected_invariants=["invariant"],
            forbidden_spillover=["billing/**"],
            allowed_scope=["src/**"],
            verification={
                "static": ["static label"],
                "behavioral": ["behavior label"],
                "differential": ["pair label"],
            },
            activation={
                "risk": "high",
                "approval_required": True,
                "safe_boundary": "before-next-agent-action",
            },
            rollback={"pointer": old_name, "compensating_action": None},
        )
        contract["extensions"]["x-m5-execution"] = profile_for(old, contract)
        names = [
            check["role"]
            for check in contract["extensions"]["x-m5-execution"]["checks"]
        ]
        contents = {
            name: f"# synthetic {name}\nprint('observation')\n".encode()
            for name in [*names, "executor", "probe"]
        }
        contents.update(programs or {})
        for name, data in contents.items():
            kind = "static" if name in {"static", "precondition"} else "behavioral"
            path = f"tests/{kind}/{name}.py"
            raw["tests_integrity"]["tests"].append(
                {"test_id": name, "kind": kind, "path": path, "digest": digest(data)}
            )
            raw["tests_integrity"]["artifact_checksums"].append(
                {"path": path, "digest": digest(data)}
            )
        if amend:
            amend(raw)
        capsule = capsule_with_digest(raw)
        package = root / "m5-authored"
        blobs = {
            binding.content_digest: binding.source_bytes
            for binding in atom.evidence_bindings
        }
        _write_package(package, capsule, blobs)
        for test in capsule.tests_integrity.tests:
            name = Path(test.path).stem
            if name in contents:
                target = package / test.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents[name])
        (package / "integrity/checksums.sha256").write_text(
            "".join(
                f"{item.digest}  {item.path}\n"
                for item in capsule.tests_integrity.artifact_checksums
            )
        )
        store = base.harness.store
        loaded, receipt = _LOAD_AND_ISSUE_RECEIPT(
            package, package, store._loader_identity, store._loader_capability()
        )
        attestation = _loader_attestation(
            loaded, package, receipt, store._loader_identity, store._loader_capability()
        )
        permit = store.issue_publication_permit(
            loaded, (atom,), base.harness.principal, loader_attestation=attestation
        )
        new = base.registry.publish(
            loaded, base.harness.principal, publication_permit=permit
        )
        return cls(base, old, new, package)
