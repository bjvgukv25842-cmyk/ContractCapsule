"""Synthetic context-driven Docker fixture, published through real M3 authority."""

import secrets
import subprocess
from datetime import datetime, timedelta

from contractcapsule.build.publish import (
    _LOAD_AND_ISSUE_RECEIPT,
    _loader_attestation,
    _write_package,
)
from contractcapsule.compile.budget import LocalTokenCounter
from contractcapsule.models.canonical import capsule_wire_dict
from contractcapsule.swap.attempts import AttemptStore
from contractcapsule.swap.docker_runner import DockerRunner
from contractcapsule.swap.twin_run import TwinRunner
from contractcapsule.swap.twin_validation import ExecutionPolicy
from contractcapsule.validate.approvals import ApprovalAuthority
from contractcapsule.validate.artifacts import LocalArtifactResolver
from contractcapsule.validate.contracts import parse_execution_contract
from contractcapsule.validate.integrity import ValidationService
from contractcapsule.validate.journal import RecordJournal
from contractcapsule.validate.models import ReplacementRequest
from tests.integration.test_compile_view import pipeline
from tests.integration.test_twin_run import config
from tests.m2_helpers import capsule_with_digest
from tests.m4_helpers import M4Fixture
from tests.m5_helpers import digest, profile_for
from tests.unit.test_eligibility import AS_OF

EXECUTOR = b"""import json, re
from pathlib import Path
view = json.loads(Path('/inputs/view.json').read_text())
value = re.search(r'CONFIG_VALUE=(\\d+)', view['content']).group(1)
assert not Path('/inputs/old_final').exists()
assert not Path('/runner/tests/behavioral/target.py').exists()
assert not Path('/runner/tests/behavioral/sentinel.py').exists()
Path('/workspace/src/config.txt').write_text(value + '\\n')
print('{"check_id":"target","observation":true}')
"""


def programs():
    expressions = {
        "precondition": "read('initial', 'src/config.txt') == '0\\n'",
        "static": "read('current', 'src/config.txt').strip().isdigit()",
        "behavioral": "read('current', 'src/config.txt') in {'1\\n', '2\\n'}",
        "target": "read('current', 'src/config.txt') == '2\\n'",
        "invariant": "read('current', 'src/audit.txt') == 'enabled\\n'",
        "spillover": "read('current', 'billing/value.txt') != read('initial', 'billing/value.txt')",
        "differential": "read('old_final', 'src/config.txt') == '1\\n' and read('new_final', 'src/config.txt') == '2\\n'",
    }
    result = {
        "executor": EXECUTOR,
        "sentinel": b"raise RuntimeError('checker secret')\n",
    }
    for name, expression in expressions.items():
        result[name] = (
            "import json\nfrom pathlib import Path\n"
            "def read(state, path): return (Path('/inputs') / state / path).read_text()\n"
            f"print(json.dumps({{'check_id': {name!r}, 'observation': {expression}}}))\n"
        ).encode()
    return result


def git(root, *args):
    return (
        subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)
        .decode()
        .strip()
    )


class TwinFixture:
    def __init__(self, root, *, high=False, program_changes=None, profile_change=None):
        self.base = M4Fixture.create(root)
        self.root = root
        self.source = root / "source-repository"
        self.source.mkdir()
        git(self.source, "init", "-q")
        git(self.source, "config", "user.email", "synthetic@example.invalid")
        git(self.source, "config", "user.name", "Synthetic fixture")
        git(self.source, "config", "remote.origin.url", "example/api")
        for path, text in {
            "src/config.txt": "0\n",
            "src/audit.txt": "enabled\n",
            "billing/value.txt": "protected\n",
        }.items():
            target = self.source / path
            target.parent.mkdir(exist_ok=True)
            target.write_text(text)
        git(self.source, "add", "src", "billing")
        git(self.source, "commit", "-qm", "synthetic initial state")
        self.commit = "sha1:" + git(self.source, "rev-parse", "HEAD")
        self.old = self.base.publish(
            provides=("policy/v1",),
            atoms=({"statement": "CONFIG_VALUE=1\n", "compression_class": "P0_EXACT"},),
        )
        self.programs = programs() | (program_changes or {})
        self.new = self._publish(high, profile_change)
        self.artifacts = LocalArtifactResolver(
            {
                self.old.capsule.control_manifest.content_digest: root
                / "publication-1",
                self.new.capsule.control_manifest.content_digest: root / "twin-package",
            }
        )
        counter = LocalTokenCounter("offline-test-model")
        compiler, old_request = pipeline(self.base, (self.old, self.new), counter)
        task = old_request.task.model_copy(
            update={
                "paths": ("src/config.txt",),
                "text": "Apply CONFIG_VALUE to src/config.txt.",
                "required_interfaces": ("policy/v1",),
                "risk": "high" if high else "low",
            }
        )
        old_request = old_request.model_copy(
            update={"capsules": (self.old,), "task": task}
        )
        new_request = old_request.model_copy(update={"capsules": (self.new,)})
        self.request = ReplacementRequest(
            operation_id="synthetic-operation",
            principal=old_request.principal,
            old=self.old,
            new=self.new,
            task=task,
            source_repository=task.repository,
            source_commit=self.commit,
            budget=old_request.budget,
            model_id=old_request.model_id,
            tokenizer_profile=old_request.tokenizer_profile,
            renderer_version=old_request.renderer_version,
        )
        self.now = datetime.fromisoformat(AS_OF)
        self.clock = lambda: self.now
        self.journal = RecordJournal(self.base.registry, secrets.token_bytes(32))
        self.attempts = AttemptStore(
            self.base.registry.database_path, secrets.token_bytes(32)
        )
        self.old_validation = ValidationService(
            old_request, compiler, self.artifacts, self.journal, self.clock
        )
        self.new_validation = ValidationService(
            new_request, compiler, self.artifacts, self.journal, self.clock
        )
        self.bound = parse_execution_contract(
            self.request, self.base.registry, self.artifacts
        )
        self.authority = ApprovalAuthority("synthetic", secrets.token_bytes(32))
        self.approval = self.authority.issue_execution(
            self.bound,
            issued_at=self.now,
            expires_at=self.now + timedelta(hours=1),
            synthetic=True,
        )
        self.revoked = False
        self.policy = ExecutionPolicy(
            digest(b"synthetic local policy v1"), lambda _: self.revoked
        )
        self.runner = TwinRunner(
            request=self.request,
            registry=self.base.registry,
            artifacts=self.artifacts,
            old_validation=self.old_validation,
            new_validation=self.new_validation,
            runner=DockerRunner(self.bound.profile.runner),
            approval_verifier=self.authority.verifier(),
            execution_policy=self.policy,
            journal=self.journal,
            attempt_store=self.attempts,
            repositories={"example/api": self.source},
            clock=self.clock,
        )

    def _publish(self, high, profile_change):
        atom = self.base._promote(
            1, {"statement": "CONFIG_VALUE=2\n", "compression_class": "P0_EXACT"}
        )
        draft = self.base.harness.build_draft(
            validated_atom=atom, capsule_id="com.example.next", version="2.0.0"
        )
        raw = capsule_wire_dict(draft.capsule)
        raw["control_manifest"]["scope"] = capsule_wire_dict(self.old.capsule)[
            "control_manifest"
        ]["scope"]
        raw["control_manifest"]["provides"] = ["policy/v1"]
        contract = raw["replacement_contract"]
        old_name = "com.example.policy@1.0.0"
        contract.update(
            replaces=old_name,
            preconditions=["initial valid"],
            target_effects=["target changed"],
            protected_invariants=["audit remains enabled"],
            forbidden_spillover=["billing/**"],
            allowed_scope=["src/**"],
            verification={
                "static": ["static label"],
                "behavioral": ["behavior label"],
                "differential": ["pair label"],
            },
            activation={
                "risk": "high" if high else "low",
                "approval_required": high,
                "safe_boundary": "before-next-agent-action",
            },
            rollback={"pointer": old_name, "compensating_action": None},
        )
        profile = profile_for(self.old, contract)
        profile.update(
            runner=config().model_dump(mode="json"), repetitions=3 if high else 1
        )
        if profile_change:
            profile_change(profile)
        contract["extensions"]["x-m5-execution"] = profile
        for name, data in self.programs.items():
            kind = "static" if name in {"static", "precondition"} else "behavioral"
            path = f"tests/{kind}/{name}.py"
            raw["tests_integrity"]["tests"].append(
                {"test_id": name, "kind": kind, "path": path, "digest": digest(data)}
            )
            raw["tests_integrity"]["artifact_checksums"].append(
                {"path": path, "digest": digest(data)}
            )
        capsule = capsule_with_digest(raw)
        package = self.root / "twin-package"
        _write_package(
            package,
            capsule,
            {b.content_digest: b.source_bytes for b in atom.evidence_bindings},
        )
        for test in capsule.tests_integrity.tests:
            if test.test_id in self.programs:
                path = package / test.path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(self.programs[test.test_id])
        (package / "integrity/checksums.sha256").write_text(
            "".join(
                f"{item.digest}  {item.path}\n"
                for item in capsule.tests_integrity.artifact_checksums
            )
        )
        store = self.base.harness.store
        loaded, receipt = _LOAD_AND_ISSUE_RECEIPT(
            package, package, store._loader_identity, store._loader_capability()
        )
        attestation = _loader_attestation(
            loaded, package, receipt, store._loader_identity, store._loader_capability()
        )
        permit = store.issue_publication_permit(
            loaded, (atom,), self.base.harness.principal, loader_attestation=attestation
        )
        return self.base.registry.publish(
            loaded, self.base.harness.principal, publication_permit=permit
        )
