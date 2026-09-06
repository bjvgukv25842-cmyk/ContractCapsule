"""M4 local admission tests; no ranker/compiler evidence is claimed here."""

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from contractcapsule.compile.errors import CompileError
from contractcapsule.models.base import Principal
from contractcapsule.models.core import Atom, Capsule
from contractcapsule.models.view import CapsuleRef, TaskContext
from contractcapsule.resolve.eligibility import EligibilityResolver
from contractcapsule.resolve.policies import (
    AccessGrant,
    FreshnessRecord,
    RecordedFreshnessChecker,
    StaticEligibilityAuthorizer,
)
from contractcapsule.resolve.scope import atom_scope_matches, path_matches, paths_match
from contractcapsule.storage.registry import PublishedCapsule
from tests.m4_helpers import M4Fixture

AS_OF = "2030-01-01T00:00:00Z"
READER = Principal("reader")


def access_grant(**changes: object) -> AccessGrant:
    data: dict[str, object] = {
        "principal_id": "reader",
        "tenant": "example",
        "authorities": ("*",),
        "capsule_ids": ("*",),
        "access_policies": ("team-auth", "team-other"),
        "max_sensitivity": "restricted",
    }
    data.update(changes)
    return AccessGrant.model_validate(data)


def freshness_for(publication: PublishedCapsule) -> RecordedFreshnessChecker:
    manifest = publication.capsule.control_manifest
    ref = CapsuleRef(
        capsule_id=manifest.capsule_id,
        version=manifest.version,
        digest=manifest.content_digest,
    )
    return RecordedFreshnessChecker(
        records=tuple(
            FreshnessRecord(
                capsule=ref,
                evidence_id=evidence.evidence_id,
                content_digest=evidence.content_digest,
                checked_at=evidence.captured_at,
                valid_until="2099-01-01T00:00:00Z",
            )
            for evidence in publication.capsule.evidence_plane.records
        )
    )


@pytest.fixture
def fixture(tmp_path: Path) -> M4Fixture:
    return M4Fixture.create(tmp_path)


def resolver_for(
    fixture: M4Fixture, publication: PublishedCapsule, **changes: Any
) -> EligibilityResolver:
    config: dict[str, Any] = {
        "registry": fixture.registry,
        "authorizer": StaticEligibilityAuthorizer(grants=(access_grant(),)),
        "freshness": freshness_for(publication),
        "as_of": AS_OF,
    }
    config.update(changes)
    return EligibilityResolver(**config)


def task_context(**changes: object) -> TaskContext:
    data: dict[str, object] = {
        "task_id": "task-1",
        "tenant": "example",
        "repository": "example/api",
        "paths": ("src/auth/token.py",),
        "environment": "prod",
        "text": "token",
    }
    data.update(changes)
    return TaskContext.model_validate(data)


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("src/auth/**", "src/auth", True),
        ("src/**/token.py", "src/token.py", True),
        ("**/token.py", "token.py", True),
        ("src/*/token.py", "src/auth/token.py", True),
        ("src/*/token.py", "src/auth/deep/token.py", False),
        ("src/auth", "src/auth/token.py", False),
        ("src/auth/**", "prefix/src/auth/token.py", False),
        ("src/auth/**", "src/authentication/token.py", False),
        ("src/*.py", "src/a.PY", False),
        ("src/a*b*c.py", "src/abc.py", True),
    ],
)
def test_path_matching_is_anchored_segment_globbing(
    pattern: str, path: str, expected: bool
) -> None:
    assert path_matches(pattern, path) is expected


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "/src",
        "C:src",
        "src\\a",
        "src\x00a",
        "src/./a",
        "../a",
        "src//a",
        "src/",
        "src/?.py",
        "src/[ab].py",
        "src/a**b",
        "***",
    ],
)
def test_invalid_scope_patterns_fail_closed(bad: str) -> None:
    with pytest.raises(CompileError, match="^INVALID_SCOPE$"):
        path_matches(bad, "src/a.py")


def test_paths_validate_all_entries_even_after_a_match() -> None:
    with pytest.raises(CompileError, match="^INVALID_SCOPE$"):
        paths_match(("**", "../hidden"), ("src/a.py",))
    with pytest.raises(CompileError, match="^INVALID_SCOPE$"):
        paths_match(("**",), ("src/a.py", "/hidden"))


def test_atom_scope_dimensions_are_anded_and_values_ored() -> None:
    scope = (
        "repository:other/api",
        "repository:example/api",
        "path:src/**",
        "environment:staging",
        "environment:prod",
    )
    assert atom_scope_matches(scope, task_context())
    assert not atom_scope_matches(scope, task_context(environment="dev"))
    assert atom_scope_matches(("environment:prod",), task_context())


@pytest.mark.parametrize(
    "scope", [("unknown:prod",), ("path:",), (), ("environment:prod", "path:../a")]
)
def test_unknown_or_malformed_atom_selectors_deny(scope: tuple[str, ...]) -> None:
    with pytest.raises(CompileError, match="^INVALID_SCOPE$"):
        atom_scope_matches(scope, task_context())


def test_deep_scope_matching_does_not_recurse_or_expand_exponentially() -> None:
    assert path_matches(
        "/".join(["**"] * 300 + ["end"]), "/".join(["part"] * 300 + ["end"])
    )


def test_real_registry_publication_is_read_and_admitted(fixture: M4Fixture) -> None:
    published = fixture.publish()
    resolver = resolver_for(fixture, published)
    result = resolver.resolve((published,), task_context(), READER)
    assert result.items[0].atom_ids == ("atom-0",)
    assert result.items[0].published == fixture.registry.get(
        "com.example.policy", "1.0.0", READER
    )
    assert not result.rejected_counts


@pytest.mark.parametrize("field", ["statement", "signature", "digest", "status"])
def test_forged_publication_projection_is_rejected(
    fixture: M4Fixture, field: str
) -> None:
    published = fixture.publish()
    capsule = published.capsule
    if field == "statement":
        atom = capsule.semantic_payload.atoms[0].model_copy(
            update={"statement": "forged"}
        )
        capsule = capsule.model_copy(
            update={
                "semantic_payload": capsule.semantic_payload.model_copy(
                    update={"atoms": (atom,)}
                )
            }
        )
    elif field == "signature":
        capsule = capsule.model_copy(update={"detached_signature": None})
    elif field == "digest":
        capsule = capsule.model_copy(
            update={
                "control_manifest": capsule.control_manifest.model_copy(
                    update={"content_digest": "sha256:" + "0" * 64}
                )
            }
        )
    forged = replace(
        published,
        capsule=capsule,
        registry_status="ACTIVE" if field == "status" else "PUBLISHED",
    )
    result = resolver_for(fixture, published).resolve((forged,), task_context(), READER)
    assert not result.items
    assert sum(result.rejected_counts.values()) == 1
    assert "com.example.policy" not in repr(result)
    assert "atom-0" not in repr(result)


def test_registry_access_is_required_even_when_runtime_policy_grants(
    fixture: M4Fixture,
) -> None:
    published = fixture.publish()
    assert (
        not resolver_for(fixture, published)
        .eligible(published.capsule, task_context(), Principal("unknown"))
        .allowed
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant": "other"},
        {"repository": "other/api"},
        {"paths": ("billing/pay.py",)},
        {"environment": "staging"},
    ],
)
def test_capsule_scope_and_tenant_gates_deny(
    fixture: M4Fixture, changes: dict[str, Any]
) -> None:
    published = fixture.publish()
    assert (
        not resolver_for(fixture, published)
        .eligible(published.capsule, task_context(**changes), READER)
        .allowed
    )


def test_default_policy_and_freshness_deny(fixture: M4Fixture) -> None:
    published = fixture.publish()
    for changes in (
        {"authorizer": StaticEligibilityAuthorizer()},
        {"freshness": RecordedFreshnessChecker()},
    ):
        assert (
            not resolver_for(fixture, published, **changes)
            .eligible(published.capsule, task_context(), READER)
            .allowed
        )


def test_grant_fragments_cannot_be_unioned(fixture: M4Fixture) -> None:
    published = fixture.publish()
    authorizer = StaticEligibilityAuthorizer(
        grants=(
            access_grant(authorities=(), access_policies=("team-auth",)),
            access_grant(authorities=("*",), access_policies=()),
        )
    )
    assert not authorizer.authorize(published.capsule, None, task_context(), READER)


@pytest.mark.parametrize(
    "change",
    [
        {"principal_id": "other"},
        {"tenant": "other"},
        {"authorities": ()},
        {"capsule_ids": ()},
        {"access_policies": ()},
        {"max_sensitivity": "public"},
    ],
)
def test_explicit_grant_dimensions_are_all_required(
    fixture: M4Fixture, change: dict[str, Any]
) -> None:
    published = fixture.publish()
    authorizer = StaticEligibilityAuthorizer(grants=(access_grant(**change),))
    assert not authorizer.authorize(published.capsule, None, task_context(), READER)


def test_policy_digest_binds_grants_principal_and_task(fixture: M4Fixture) -> None:
    policy = StaticEligibilityAuthorizer(grants=(access_grant(),))
    digest = policy.context_digest(task_context(), READER)
    assert digest != policy.context_digest(task_context(environment="dev"), READER)
    assert digest != policy.context_digest(task_context(), Principal("other"))
    assert digest != StaticEligibilityAuthorizer().context_digest(
        task_context(), READER
    )


class BrokenPolicy:
    version = "1.0.0"

    def __init__(self, decision: object) -> None:
        self.decision = decision

    def authorize(
        self,
        capsule: Capsule,
        atom: Atom | None,
        task: TaskContext,
        principal: Principal,
    ) -> Any:
        del capsule, atom, task, principal
        if isinstance(self.decision, Exception):
            raise self.decision
        return self.decision

    def context_digest(self, task: TaskContext, principal: Principal) -> str:
        del task, principal
        return "sha256:" + "1" * 64


@pytest.mark.parametrize("decision", [1, "yes", None, RuntimeError("private-details")])
def test_policy_malformed_or_exception_denies_without_message_leak(
    fixture: M4Fixture, decision: object
) -> None:
    published = fixture.publish()
    result = resolver_for(
        fixture, published, authorizer=BrokenPolicy(decision)
    ).resolve((published,), task_context(), READER)
    assert not result.items
    assert "private-details" not in repr(result)


def test_individual_atom_scope_does_not_export_denied_identity(
    fixture: M4Fixture,
) -> None:
    published = fixture.publish(
        atoms=({}, {"atom_id": "hidden-member", "scope": ("environment:dev",)})
    )
    result = resolver_for(fixture, published).resolve(
        (published,), task_context(), READER
    )
    assert result.items[0].atom_ids == ("atom-0",)
    assert len(result.items[0].published.capsule.semantic_payload.atoms) == 2
    assert "hidden-member" not in repr(result)
    assert sum(result.rejected_counts.values()) == 1


def test_atom_validity_dates_are_inclusive(fixture: M4Fixture) -> None:
    def amend(raw: dict[str, Any]) -> None:
        raw["semantic_payload"]["atoms"][0]["validity"] = {
            "from": "2030-01-01",
            "until": "2030-01-01",
        }

    published = fixture.publish(amend=amend)
    for when, expected in (
        (AS_OF, True),
        ("2030-01-01T23:59:59Z", True),
        ("2029-12-31T23:59:59Z", False),
        ("2030-01-02T00:00:00Z", False),
    ):
        result = resolver_for(fixture, published, as_of=when).eligible(
            published.capsule, task_context(), READER
        )
        assert bool(result.atom_ids) is expected


@pytest.mark.parametrize(
    ("provided", "required", "allowed"),
    [
        (("auth/v2",), ("auth/v2", "audit/v1"), True),
        ((), ("audit/v1",), True),
        (("auth/v1",), ("auth/v2",), False),
        (("auth/v1", "auth/v2"), ("auth/v2",), True),
        (("auth/v02",), (), False),
        (("auth/v-1",), (), False),
        (("/v1",), (), False),
        (("auth/v2",), ("broken",), False),
    ],
)
def test_local_interface_compatibility_is_not_collective_coverage(
    fixture: M4Fixture,
    provided: tuple[str, ...],
    required: tuple[str, ...],
    allowed: bool,
) -> None:
    published = fixture.publish(provides=provided)
    assert (
        resolver_for(fixture, published)
        .eligible(published.capsule, task_context(required_interfaces=required), READER)
        .allowed
        is allowed
    )


def test_freshness_exact_binding_and_time_window(fixture: M4Fixture) -> None:
    published = fixture.publish()
    original = freshness_for(published)
    record = original.records[0]
    assert original.check(published.capsule, None, AS_OF)
    changes = (
        {"evidence_id": "other"},
        {"content_digest": "sha256:" + "0" * 64},
        {"checked_at": "2031-01-01T00:00:00Z"},
        {"valid_until": "2029-01-01T00:00:00Z"},
    )
    for change in changes:
        checker = RecordedFreshnessChecker(records=(record.model_copy(update=change),))
        assert not checker.check(published.capsule, None, AS_OF)
    assert not original.check(published.capsule, None, "2000-01-01T00:00:00Z")


def test_freshness_rejects_duplicate_and_reversed_records(fixture: M4Fixture) -> None:
    record = freshness_for(fixture.publish()).records[0]
    with pytest.raises((ValueError, CompileError)):
        RecordedFreshnessChecker(records=(record, record))
    with pytest.raises(ValidationError):
        FreshnessRecord.model_validate(
            {
                **record.model_dump(),
                "checked_at": "2099-01-01T00:00:00Z",
                "valid_until": "2000-01-01T00:00:00Z",
            }
        )


def test_freshness_atom_checks_only_referenced_evidence(fixture: M4Fixture) -> None:
    published = fixture.publish(atoms=({}, {}))
    checker = RecordedFreshnessChecker(records=freshness_for(published).records[:1])
    assert checker.check(
        published.capsule, published.capsule.semantic_payload.atoms[0], AS_OF
    )
    assert not checker.check(published.capsule, None, AS_OF)


def test_p4_ttl_expiry_is_not_revived_by_freshness_attestation(
    fixture: M4Fixture,
) -> None:
    published = fixture.publish(atoms=({"compression_class": "P4_TRANSIENT"},))
    captured = datetime.fromisoformat(
        published.capsule.evidence_plane.records[0].captured_at
    )
    for elapsed, expected in (
        (timedelta(days=7), True),
        (timedelta(days=7, microseconds=1), False),
    ):
        when = (captured + elapsed).isoformat().replace("+00:00", "Z")
        result = resolver_for(fixture, published, as_of=when).eligible(
            published.capsule, task_context(), READER
        )
        assert bool(result.atom_ids) is expected


def test_resolve_is_stable_and_deduplicates_identical_projection(
    fixture: M4Fixture,
) -> None:
    published = fixture.publish()
    changed = replace(
        published,
        published_at="different",
        capsule=published.capsule.model_copy(
            update={
                "derived_artifacts": {"cache": "rebuildable"},
                "runtime_sidecar": {"trace": 1},
            }
        ),
    )
    resolver = resolver_for(fixture, published)
    first = resolver.resolve((published, changed), task_context(), READER)
    second = resolver.resolve((changed, published), task_context(), READER)
    assert first == second
    assert len(first.items) == 1
    with pytest.raises(TypeError):
        first.rejected_counts["not-allowed"] = 1  # type: ignore[index]


def test_conflicting_duplicate_identity_does_not_admit_either(
    fixture: M4Fixture,
) -> None:
    published = fixture.publish()
    forged = replace(
        published,
        capsule=published.capsule.model_copy(update={"detached_signature": None}),
    )
    result = resolver_for(fixture, published).resolve(
        (published, forged), task_context(), READER
    )
    assert not result.items
    assert "com.example.policy" not in repr(result)


class ChangingPolicy(BrokenPolicy):
    def __init__(self) -> None:
        super().__init__(True)
        self.calls = 0

    def context_digest(self, task: TaskContext, principal: Principal) -> str:
        self.calls += 1
        return "sha256:" + ("1" if self.calls == 1 else "2") * 64


def test_policy_snapshot_change_fails_closed(fixture: M4Fixture) -> None:
    published = fixture.publish()
    with pytest.raises(CompileError):
        resolver_for(fixture, published, authorizer=ChangingPolicy()).resolve(
            (published,), task_context(), READER
        )


@pytest.mark.parametrize("metadata", ["not-a-digest", "sha256:" + "x" * 64])
def test_invalid_snapshot_metadata_fails_closed(
    fixture: M4Fixture, metadata: str
) -> None:
    class InvalidMetadata(BrokenPolicy):
        def context_digest(self, task: TaskContext, principal: Principal) -> str:
            return metadata

    published = fixture.publish()
    with pytest.raises(CompileError):
        resolver_for(fixture, published, authorizer=InvalidMetadata(True)).resolve(
            (published,), task_context(), READER
        )


def test_resolver_configuration_is_explicit_and_validated(fixture: M4Fixture) -> None:
    published = fixture.publish()
    for config in (
        {"as_of": "not-time"},
        {"max_sensitivity": "unknown"},
        {"registry": object()},
    ):
        with pytest.raises((ValueError, TypeError, CompileError)):
            resolver_for(fixture, published, **config)


def test_permission_snapshot_normalizes_semantic_grant_sets() -> None:
    first = access_grant(
        authorities=("a", "b"), capsule_ids=("c", "d"), access_policies=("p", "q")
    )
    second = access_grant(
        authorities=("b", "a", "a"), capsule_ids=("d", "c"), access_policies=("q", "p")
    )
    assert StaticEligibilityAuthorizer(grants=(first,)).context_digest(
        task_context(), READER
    ) == (
        StaticEligibilityAuthorizer(grants=(second, second)).context_digest(
            task_context(), READER
        )
    )


def test_forged_principal_and_task_copies_fail_closed(fixture: M4Fixture) -> None:
    published = fixture.publish()
    malformed = task_context().model_copy(update={"paths": ("../private",)})
    result = resolver_for(fixture, published).eligible(
        published.capsule, malformed, READER
    )
    assert not result.allowed


class BrokenFreshness:
    version = "1.0.0"

    def __init__(self, decision: object, *, changing: bool = False) -> None:
        self.decision = decision
        self.changing = changing
        self.calls = 0

    def check(self, capsule: Capsule, atom: Atom | None, as_of: str) -> Any:
        del capsule, atom, as_of
        if isinstance(self.decision, Exception):
            raise self.decision
        return self.decision

    def context_digest(self) -> str:
        self.calls += 1
        return "sha256:" + ("2" if self.changing and self.calls > 1 else "1") * 64


@pytest.mark.parametrize("decision", [1, "fresh", None, RuntimeError("secret-uri")])
def test_freshness_malformed_or_exception_denies_safely(
    fixture: M4Fixture, decision: object
) -> None:
    publication = fixture.publish()
    result = resolver_for(
        fixture, publication, freshness=BrokenFreshness(decision)
    ).resolve((publication,), task_context(), READER)
    assert not result.items
    assert "secret-uri" not in repr(result)


def test_freshness_snapshot_change_blocks_entire_result(fixture: M4Fixture) -> None:
    publication = fixture.publish()
    with pytest.raises(CompileError, match="^POLICY_SNAPSHOT_CHANGED$"):
        resolver_for(
            fixture, publication, freshness=BrokenFreshness(True, changing=True)
        ).resolve((publication,), task_context(), READER)


def test_invalid_service_version_is_not_accepted(fixture: M4Fixture) -> None:
    publication = fixture.publish()
    policy = BrokenPolicy(True)
    policy.version = "unknown"
    with pytest.raises(CompileError, match="^INVALID_POLICY_SNAPSHOT$"):
        resolver_for(fixture, publication, authorizer=policy).resolve(
            (publication,), task_context(), READER
        )


def test_authorization_gate_precedes_freshness_and_does_not_call_denied_atoms(
    fixture: M4Fixture,
) -> None:
    publication = fixture.publish()
    fresh = BrokenFreshness(RuntimeError("must-not-reach"))
    result = resolver_for(
        fixture, publication, freshness=fresh, authorizer=StaticEligibilityAuthorizer()
    ).eligible(publication.capsule, task_context(), READER)
    assert result.blockers == ("AUTHORIZATION_DENIED",)


@pytest.mark.parametrize(
    "change",
    [
        {"authority": "extra-authority"},
        {"sensitivity": "restricted"},
        {"refresh_policy": "unknown"},
    ],
)
def test_atom_security_gates_leave_full_payload_but_no_denied_id(
    fixture: M4Fixture, change: dict[str, Any]
) -> None:
    def amend(raw: dict[str, Any]) -> None:
        raw["semantic_payload"]["atoms"][1].update(change)

    publication = fixture.publish(atoms=({}, {}), amend=amend)
    policy = StaticEligibilityAuthorizer(
        grants=(
            access_grant(
                authorities=("approved-project-policy",), max_sensitivity="internal"
            ),
        )
    )
    result = resolver_for(
        fixture, publication, authorizer=policy, max_sensitivity="internal"
    ).resolve((publication,), task_context(), READER)
    assert result.items[0].atom_ids == ("atom-0",)
    assert "atom-1" not in repr(result)


def test_snapshot_digest_includes_resolver_sensitivity_and_time(
    fixture: M4Fixture,
) -> None:
    publication = fixture.publish()
    baseline = resolver_for(fixture, publication).resolve(
        (publication,), task_context(), READER
    )
    narrow = resolver_for(fixture, publication, max_sensitivity="internal").resolve(
        (publication,), task_context(), READER
    )
    later = resolver_for(fixture, publication, as_of="2030-01-02T00:00:00Z").resolve(
        (publication,), task_context(), READER
    )
    assert baseline.permission_digest != narrow.permission_digest
    assert baseline.permission_digest != later.permission_digest
    assert baseline.freshness_digest != later.freshness_digest


def test_recorded_freshness_never_uses_a_validation_flag_as_attestation(
    fixture: M4Fixture,
) -> None:
    publication = fixture.publish()
    assert all(
        record.validation == "verified"
        for record in publication.capsule.evidence_plane.records
    )
    assert not RecordedFreshnessChecker().check(publication.capsule, None, AS_OF)


def test_resolver_rechecks_registry_integrity_after_publication(
    fixture: M4Fixture,
) -> None:
    publication = fixture.publish()
    record = publication.capsule.evidence_plane.records[0]
    hex_digest = record.content_digest.removeprefix("sha256:")
    blob = (
        fixture.harness.root
        / "cas"
        / "objects"
        / "sha256"
        / hex_digest[:2]
        / f"{hex_digest[2:]}.blob"
    )
    # Actual CAS corruption, not a fake Registry return value.
    assert blob.exists()
    blob.chmod(0o600)
    blob.write_bytes(b"corrupt")
    result = resolver_for(fixture, publication).eligible(
        publication.capsule, task_context(), READER
    )
    assert not result.allowed


@pytest.mark.parametrize("scope", [(None,), (1,), ("environment:prod", None)])
def test_scope_type_errors_are_safe_compile_errors(scope: tuple[Any, ...]) -> None:
    with pytest.raises(CompileError, match="^INVALID_SCOPE$"):
        atom_scope_matches(cast(tuple[str, ...], scope), task_context())


def test_signature_value_change_with_unchanged_core_digest_is_rejected(
    fixture: M4Fixture,
) -> None:
    published = fixture.publish()
    signature = published.capsule.detached_signature
    assert signature is not None
    changed = published.capsule.model_copy(
        update={
            "detached_signature": signature.model_copy(
                update={"value": "forged-envelope"}
            )
        }
    )
    result = resolver_for(fixture, published).eligible(changed, task_context(), READER)
    assert not result.allowed


@pytest.mark.parametrize("entrypoint", ["eligible", "resolve"])
@pytest.mark.parametrize(
    ("atom_scope", "expected_ids"),
    [
        (("path:billing/**",), ()),
        (("path:src/auth/**",), ("private-member",)),
        (("environment:prod",), ("private-member",)),
    ],
)
def test_atom_and_capsule_scope_require_the_same_task_path(
    fixture: M4Fixture,
    entrypoint: str,
    atom_scope: tuple[str, ...],
    expected_ids: tuple[str, ...],
) -> None:
    def narrow_capsule(raw: dict[str, Any]) -> None:
        raw["control_manifest"]["scope"]["paths"] = ["src/auth/**"]

    publication = fixture.publish(
        atoms=({"atom_id": "private-member", "scope": atom_scope},),
        amend=narrow_capsule,
    )
    task = task_context(paths=("src/auth/token.py", "billing/pay.py"))
    resolver = resolver_for(fixture, publication)
    if entrypoint == "eligible":
        eligibility = resolver.eligible(publication.capsule, task, READER)
        assert eligibility.atom_ids == expected_ids
    else:
        result = resolver.resolve((publication,), task, READER)
        assert result.items[0].atom_ids == expected_ids
        if not expected_ids:
            assert "private-member" not in repr(result)
            assert result.rejected_counts == {"ATOM_SCOPE_DENIED": 1}


def test_scope_narrowing_preserves_original_authorization_task(
    fixture: M4Fixture,
) -> None:
    def narrow_capsule(raw: dict[str, Any]) -> None:
        raw["control_manifest"]["scope"]["paths"] = ["src/auth/**"]

    publication = fixture.publish(amend=narrow_capsule)
    task = task_context(paths=("src/auth/token.py", "billing/pay.py"))

    class OriginalTaskPolicy(BrokenPolicy):
        def authorize(
            self,
            capsule: Capsule,
            atom: Atom | None,
            candidate_task: TaskContext,
            principal: Principal,
        ) -> bool:
            return candidate_task is task

        def context_digest(
            self, candidate_task: TaskContext, principal: Principal
        ) -> str:
            assert candidate_task is task
            return super().context_digest(candidate_task, principal)

    result = resolver_for(
        fixture, publication, authorizer=OriginalTaskPolicy(True)
    ).resolve((publication,), task, READER)
    assert result.items[0].atom_ids == ("atom-0",)
    assert task.paths == ("billing/pay.py", "src/auth/token.py")


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("field", ["capsule_id", "version", "inner_capsule"])
def test_mixed_malformed_publication_identity_preserves_valid_admission(
    fixture: M4Fixture,
    field: str,
    reverse: bool,
) -> None:
    publication = fixture.publish()
    if field == "inner_capsule":
        malformed = cast(
            Capsule,
            SimpleNamespace(
                control_manifest=publication.capsule.control_manifest,
                private_content="denied-private-content",
            ),
        )
    else:
        malformed = publication.capsule.model_copy(
            update={
                "control_manifest": publication.capsule.control_manifest.model_copy(
                    update={field: 7}
                )
            }
        )
    forged = replace(publication, capsule=malformed)
    inputs = (forged, publication) if reverse else (publication, forged)
    result = resolver_for(fixture, publication).resolve(inputs, task_context(), READER)
    assert len(result.items) == 1
    assert result.items[0].published == publication
    assert result.items[0].atom_ids == ("atom-0",)
    assert result.rejected_counts == {"REGISTRY_INTEGRITY": 1}
    assert "denied-private-content" not in repr(result)


def test_ineligible_atom_never_reaches_ranker(tmp_path: Path) -> None:
    from unittest.mock import patch

    from contractcapsule.compile.budget import LocalTokenCounter
    from contractcapsule.resolve.rank import FTS5BM25Ranker
    from tests.integration.test_compile_view import pipeline

    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish(
        atoms=(
            {"atom_id": "allowed", "compression_class": "P0_EXACT"},
            {"atom_id": "denied", "statement": "token " * 20, "scope": ("path:other/**",)},
        )
    )
    compiler, request = pipeline(fixture, (pub,), LocalTokenCounter("frozen-test"))
    original = FTS5BM25Ranker.rank_atoms
    observed: list[str] = []

    def sentinel(self, atoms, task):
        observed.extend(atom.atom_id for atom in atoms)
        return original(self, atoms, task)

    with patch.object(FTS5BM25Ranker, "rank_atoms", sentinel):
        view = compiler.compile_view(request)
    assert view.validation.valid
    assert observed == ["allowed"]
    assert "denied" not in view.model_dump_json()
