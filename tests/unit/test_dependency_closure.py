"""Two-level mandatory closure and verified provider ownership."""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from contractcapsule.audit.quarantine import ValidatedAtom
from contractcapsule.compile.errors import CompileError
from contractcapsule.models.core import DependencyEdge, DependencyGraph
from contractcapsule.models.view import CapsuleRef, Conflict, TaskContext
from contractcapsule.resolve.closure import dependency_closure
from contractcapsule.resolve.conflicts import detect_conflicts
from contractcapsule.resolve.eligibility import AdmissionResult, EligibilityResolver
from contractcapsule.resolve.graph import resolve_graph
from contractcapsule.resolve.policies import (
    RecordedFreshnessChecker,
    StaticEligibilityAuthorizer,
)
from contractcapsule.storage.registry import PublishedCapsule
from tests.m4_helpers import M4Fixture
from tests.unit.test_eligibility import (
    AS_OF,
    READER,
    access_grant,
    freshness_for,
    task_context,
)


def edge(
    source: str,
    target: str,
    kind: str = "requires",
    mandatory: bool = True,
    constraint: str | None = None,
) -> DependencyEdge:
    return DependencyEdge.model_validate(
        {
            "source": source,
            "target": target,
            "edge_type": kind,
            "mandatory": mandatory,
            "version_constraint": constraint,
        }
    )


def test_selected_set_is_closed() -> None:
    graph = DependencyGraph(edges=(edge("a", "b"), edge("b", "c"), edge("c", "a")))
    selected = {"a"}
    assert dependency_closure(selected, graph) == {"a", "b", "c"}
    assert selected == {"a"}


def test_optional_and_metadata_edges_never_force_membership() -> None:
    graph = DependencyGraph(
        edges=(
            edge("a", "b", "optional"),
            edge("b", "a", "optional"),
            edge("a", "c", mandatory=False),
            edge("a", "d", "provides"),
            edge("a", "e", "replaces"),
        )
    )
    assert dependency_closure({"a"}, graph) == {"a"}


def test_conflicts_are_symmetric_deduplicated_and_include_self() -> None:
    graph = DependencyGraph(
        edges=(
            edge("b", "a", "conflicts"),
            edge("a", "b", "conflicts"),
            edge("a", "a", "conflicts"),
            edge("a", "z", "conflicts"),
        )
    )
    assert detect_conflicts({"a", "b"}, graph) == [
        Conflict(source="a", target="a", reason="DECLARED_CONFLICT"),
        Conflict(source="a", target="b", reason="DECLARED_CONFLICT"),
    ]


@pytest.fixture
def fixture(tmp_path: Path) -> M4Fixture:
    return M4Fixture.create(tmp_path)


def admit(
    fixture: M4Fixture,
    publications: tuple[PublishedCapsule, ...],
    task: TaskContext | None = None,
) -> AdmissionResult:
    resolver = EligibilityResolver(
        registry=fixture.registry,
        authorizer=StaticEligibilityAuthorizer(grants=(access_grant(),)),
        freshness=RecordedFreshnessChecker(
            records=tuple(
                record for pub in publications for record in freshness_for(pub).records
            )
        ),
        as_of=AS_OF,
    )
    return resolver.resolve(publications, task or task_context(), READER)


def ref(publication: PublishedCapsule) -> CapsuleRef:
    manifest = publication.capsule.control_manifest
    return CapsuleRef(
        capsule_id=manifest.capsule_id,
        version=manifest.version,
        digest=manifest.content_digest,
    )


def dependencies(
    requirements: tuple[str, ...],
    providers: tuple[PublishedCapsule, ...],
    graph_edges: tuple[DependencyEdge, ...] = (),
) -> Callable[[dict[str, Any]], None]:
    def amend(raw: dict[str, Any]) -> None:
        raw["control_manifest"]["requires"] = requirements
        raw["tests_integrity"]["lock"]["capsule_dependencies"] = [
            ref(item).model_dump(mode="json") for item in providers
        ]
        raw["dependency_graph"]["edges"] = [
            item.model_dump(mode="json") for item in graph_edges
        ]

    return amend


def test_collective_roots_force_complete_payload_not_metadata(
    fixture: M4Fixture,
) -> None:
    auth = fixture.publish(
        provides=("auth/v2",),
        atoms=(
            {"atom_id": "auth", "compression_class": "P2_EVIDENCE"},
            {"atom_id": "auth-sibling", "compression_class": "P3_SUMMARY"},
        ),
    )
    audit = fixture.publish(
        capsule_id="com.example.audit",
        provides=("audit/v1",),
        atoms=({"atom_id": "audit"},),
    )
    task = task_context(required_interfaces=("auth/v2", "audit/v1"))
    graph = resolve_graph(admit(fixture, (auth, audit), task), task)
    assert graph.root_atom_ids == {"auth", "auth-sibling", "audit"}
    assert graph.atoms["auth"].compression_class == "P2_EVIDENCE"
    assert {w.requirement for w in graph.providers} == {"auth/v2", "audit/v1"}
    with pytest.raises(CompileError, match="^MISSING_INTERFACE$"):
        resolve_graph(admit(fixture, (auth,), task), task)


def test_partial_and_zero_atom_providers_are_unusable(fixture: M4Fixture) -> None:
    publication = fixture.publish(
        provides=("auth/v2",),
        atoms=(
            {"atom_id": "public"},
            {"atom_id": "denied", "scope": ("environment:dev",)},
        ),
    )
    task = task_context(required_interfaces=("auth/v2",))
    with pytest.raises(CompileError, match="^MISSING_INTERFACE$") as failure:
        resolve_graph(admit(fixture, (publication,), task), task)
    assert "denied" not in str(failure.value)


def test_unrelated_lock_cannot_choose_ambiguous_root(fixture: M4Fixture) -> None:
    one = fixture.publish(provides=("auth/v2",), atoms=({"atom_id": "one"},))
    two = fixture.publish(
        capsule_id="com.example.second",
        provides=("auth/v2",),
        atoms=({"atom_id": "two"},),
    )
    consumer = fixture.publish(
        capsule_id="com.example.consumer",
        atoms=({"atom_id": "consumer"},),
        amend=dependencies(("auth@>=1",), (one,)),
    )
    task = task_context(required_interfaces=("auth/v2",))
    with pytest.raises(CompileError, match="^AMBIGUOUS_PROVIDER$"):
        resolve_graph(admit(fixture, (one, two, consumer), task), task)


def test_consumer_lock_and_release_not_interface_version(fixture: M4Fixture) -> None:
    provider = fixture.publish(
        version="3.2.0+build",
        provides=("auth/v99",),
        atoms=({"atom_id": "provider"}, {"atom_id": "sibling"}),
    )
    consumer = fixture.publish(
        capsule_id="com.example.consumer",
        atoms=({"atom_id": "consumer"},),
        amend=dependencies(("auth@>=3,<4",), (provider,)),
    )
    graph = resolve_graph(admit(fixture, (consumer, provider)), task_context())
    assert graph.close_atoms({"consumer"}) == {"consumer", "provider", "sibling"}
    assert graph.close_atoms({"provider"}) == {"provider"}
    assert graph.providers[0].consumer == ref(consumer)
    assert graph.providers[0].provider == ref(provider)
    assert graph.providers[0].atom_ids == ("provider", "sibling")
    assert graph.closure_links({"consumer"})


@pytest.mark.parametrize(
    "lock_fault", ["missing", "digest", "version", "wrong-consumer"]
)
def test_consumer_lock_is_exact_and_owned(fixture: M4Fixture, lock_fault: str) -> None:
    provider = fixture.publish(provides=("auth/v2",), atoms=({"atom_id": "provider"},))

    def amend(raw: dict[str, Any]) -> None:
        dependencies(("auth@>=1",), (provider,))(raw)
        locks = raw["tests_integrity"]["lock"]["capsule_dependencies"]
        if lock_fault in {"missing", "wrong-consumer"}:
            locks.clear()
        elif lock_fault == "digest":
            locks[0]["digest"] = "sha256:" + "0" * 64
        else:
            locks[0]["version"] = "2.0.0"

    consumer = fixture.publish(
        capsule_id="com.example.consumer", atoms=({"atom_id": "consumer"},), amend=amend
    )
    unrelated = fixture.publish(
        capsule_id="com.example.unrelated",
        atoms=({"atom_id": "other"},),
        amend=dependencies((), (provider,)),
    )
    with pytest.raises(CompileError, match="^MISSING_DEPENDENCY$"):
        resolve_graph(admit(fixture, (provider, consumer, unrelated)), task_context())


def test_atom_requirement_does_not_force_siblings(fixture: M4Fixture) -> None:
    provider = fixture.publish(atoms=({"atom_id": "target"}, {"atom_id": "sibling"}))
    consumer = fixture.publish(
        capsule_id="com.example.consumer",
        atoms=({"atom_id": "source"},),
        amend=dependencies((), (provider,), (edge("source", "target"),)),
    )
    graph = resolve_graph(admit(fixture, (consumer, provider)), task_context())
    assert graph.close_atoms({"source"}) == {"source", "target"}
    assert graph.close_atoms({"target"}) == {"target"}
    assert graph.providers[0].consumer == ref(consumer)
    assert graph.providers[0].provider == ref(provider)
    assert graph.providers[0].atom_ids == ("target",)


def test_reachable_missing_requirement_is_safe(fixture: M4Fixture) -> None:
    publication = fixture.publish(
        amend=dependencies((), (), (edge("atom-0", "hidden"),))
    )
    graph = resolve_graph(admit(fixture, (publication,)), task_context())
    assert graph.close_atoms(set()) == set()
    with pytest.raises(CompileError, match="^MISSING_DEPENDENCY$"):
        graph.close_atoms({"atom-0"})
    with pytest.raises(CompileError, match="^MISSING_ATOM$"):
        graph.close_atoms({"hidden"})


def test_competing_versions_conflict_only_when_selected(fixture: M4Fixture) -> None:
    one = fixture.publish(atoms=({"atom_id": "one"},))
    two = fixture.publish(version="2.0.0", atoms=({"atom_id": "two"},))
    graph = resolve_graph(admit(fixture, (one, two)), task_context())
    assert not graph.conflicts_for({"one"})
    assert len(graph.conflicts_for({"one", "two"})) == 1


def test_different_duplicate_atom_content_is_rejected(fixture: M4Fixture) -> None:
    one = fixture.publish()
    two = fixture.publish(
        capsule_id="com.example.two", atoms=({"statement": "Different rule.\n"},)
    )
    with pytest.raises(CompileError, match="^DUPLICATE_ATOM$"):
        resolve_graph(admit(fixture, (one, two)), task_context())


def test_graph_input_permutations_are_stable(fixture: M4Fixture) -> None:
    one = fixture.publish(provides=("auth/v2",), atoms=({"atom_id": "one"},))
    two = fixture.publish(
        capsule_id="com.example.two",
        atoms=({"atom_id": "two"},),
        amend=dependencies(("auth@>=1",), (one,)),
    )
    task = task_context(required_interfaces=("auth/v2",))
    left = resolve_graph(admit(fixture, (one, two), task), task)
    right = resolve_graph(admit(fixture, (two, one), task), task)
    assert left == right


def test_capsule_edge_chooses_only_consumer_locked_release(fixture: M4Fixture) -> None:
    one = fixture.publish(atoms=({"atom_id": "one"},))
    two = fixture.publish(
        version="2.0.0", atoms=({"atom_id": "two"}, {"atom_id": "sibling"})
    )
    consumer = fixture.publish(
        capsule_id="com.example.consumer",
        atoms=({"atom_id": "source"},),
        amend=dependencies(
            (), (two,), (edge("source", "com.example.policy", constraint=">=2"),)
        ),
    )
    graph = resolve_graph(admit(fixture, (one, two, consumer)), task_context())
    assert graph.close_atoms({"source"}) == {"source", "two", "sibling"}
    assert graph.providers[0].consumer == ref(consumer)
    assert graph.providers[0].provider == ref(two)
    assert graph.providers[0].atom_ids == ("sibling", "two")


def test_unknown_dotted_target_remains_a_missing_obligation(fixture: M4Fixture) -> None:
    publication = fixture.publish(
        amend=dependencies((), (), (edge("com.example.policy", "com.example.absent"),))
    )
    graph = resolve_graph(admit(fixture, (publication,)), task_context())
    assert graph.close_atoms(set()) == set()
    with pytest.raises(CompileError, match="^MISSING_DEPENDENCY$"):
        graph.close_atoms({"atom-0"})


@pytest.mark.parametrize(
    "graph_edge,code",
    [
        (edge("unknown", "atom-0"), "INVALID_GRAPH"),
        (edge("atom-0", "__ccs_m4__:unit:forged"), "INVALID_GRAPH"),
        (edge("atom-0", "atom-0", constraint="^1"), "INVALID_VERSION_CONSTRAINT"),
        (
            edge("atom-0", "atom-0", "provides", constraint="^1"),
            "INVALID_VERSION_CONSTRAINT",
        ),
        (edge("atom-0", "atom-0", constraint=">2"), "MISSING_DEPENDENCY"),
    ],
)
def test_invalid_explicit_edges_fail_safely(
    fixture: M4Fixture, graph_edge: DependencyEdge, code: str
) -> None:
    publication = fixture.publish(amend=dependencies((), (), (graph_edge,)))
    with pytest.raises(CompileError, match=f"^{code}$"):
        resolve_graph(admit(fixture, (publication,)), task_context())


def test_atom_capsule_name_collision_is_not_guessed(fixture: M4Fixture) -> None:
    publication = fixture.publish(
        atoms=({"atom_id": "com.example.policy"},),
        amend=dependencies((), (), (edge("com.example.policy", "absent"),)),
    )
    with pytest.raises(CompileError, match="^AMBIGUOUS_GRAPH_NODE$"):
        resolve_graph(admit(fixture, (publication,)), task_context())


def test_reserved_atom_namespace_is_rejected(fixture: M4Fixture) -> None:
    publication = fixture.publish(atoms=({"atom_id": "__ccs_m4__:presence:forged"},))
    with pytest.raises(CompileError, match="^INVALID_GRAPH$"):
        resolve_graph(admit(fixture, (publication,)), task_context())


def test_capsule_conflict_is_realized_by_dependency_owner(fixture: M4Fixture) -> None:
    provider = fixture.publish(
        provides=("auth/v99",), version="3.0.0", atoms=({"atom_id": "provider"},)
    )
    consumer = fixture.publish(
        capsule_id="com.example.consumer",
        atoms=({"atom_id": "source"},),
        amend=dependencies(("auth@>=3",), (provider,)),
    )

    def conflict(raw: dict[str, Any]) -> None:
        raw["control_manifest"]["conflicts"] = ["auth@>=3,<4"]

    other = fixture.publish(
        capsule_id="com.example.other", atoms=({"atom_id": "other"},), amend=conflict
    )
    graph = resolve_graph(admit(fixture, (consumer, provider, other)), task_context())
    assert not graph.conflicts_for({"source"})
    assert len(graph.conflicts_for({"source", "other"})) == 1


def test_same_capsule_atom_cycle_merges_inline_and_explicit_edges(
    fixture: M4Fixture,
) -> None:
    def amend(raw: dict[str, Any]) -> None:
        raw["semantic_payload"]["atoms"][0]["requires_atoms"] = ["b"]
        raw["semantic_payload"]["atoms"][0]["conflicts_with"] = ["a"]
        raw["dependency_graph"]["edges"] = [
            edge("b", "c").model_dump(mode="json"),
            edge("c", "a").model_dump(mode="json"),
        ]

    publication = fixture.publish(
        atoms=({"atom_id": "a"}, {"atom_id": "b"}, {"atom_id": "c"}), amend=amend
    )
    graph = resolve_graph(admit(fixture, (publication,)), task_context())
    assert graph.close_atoms({"a"}) == {"a", "b", "c"}
    assert graph.conflicts_for({"a"}) == (
        Conflict(source="a", target="a", reason="DECLARED_CONFLICT"),
    )


def test_unadmitted_dependency_is_not_dropped_or_disclosed(fixture: M4Fixture) -> None:
    publication = fixture.publish(
        atoms=({"atom_id": "a"}, {"atom_id": "denied", "scope": ("environment:dev",)}),
        amend=dependencies((), (), (edge("a", "denied"),)),
    )
    graph = resolve_graph(admit(fixture, (publication,)), task_context())
    with pytest.raises(CompileError, match="^MISSING_DEPENDENCY$"):
        graph.closure_links({"a"})


def test_optional_unknown_target_does_not_force_or_conflict(fixture: M4Fixture) -> None:
    publication = fixture.publish(
        amend=dependencies((), (), (edge("atom-0", "missing", "optional"),))
    )
    graph = resolve_graph(admit(fixture, (publication,)), task_context())
    assert graph.close_atoms({"atom-0"}) == {"atom-0"}


@pytest.mark.parametrize(
    "required,allowed",
    [((), True), (("auth/v2",), True), (("audit/v1",), False), (("auth/v1",), False)],
)
def test_singleton_interface_gate(
    fixture: M4Fixture, required: tuple[str, ...], allowed: bool
) -> None:
    publication = fixture.publish(provides=("auth/v2",))
    task = task_context(required_interfaces=required)
    admission = admit(fixture, (publication,), task)
    if allowed:
        assert resolve_graph(admission, task).root_atom_ids == (
            {"atom-0"} if required else set()
        )
    else:
        with pytest.raises(CompileError, match="^MISSING_INTERFACE$"):
            resolve_graph(admission, task)


class ReusedApprovalFixture(M4Fixture):
    """Re-publish the same genuinely approved atom under distinct capsule identities."""

    approved: ValidatedAtom | None = None

    def _promote(self, index: int, options: Mapping[str, Any]) -> ValidatedAtom:
        if self.approved is None:
            self.approved = super()._promote(index, options)
        return self.approved


def test_identical_duplicate_retains_all_real_publication_owners(
    tmp_path: Path,
) -> None:
    fixture = ReusedApprovalFixture.create(tmp_path)
    one = fixture.publish()
    two = fixture.publish(capsule_id="com.example.two")
    graph = resolve_graph(admit(fixture, (one, two)), task_context())
    assert tuple(graph.atoms) == ("atom-0",)
    assert graph.owners["atom-0"] == (ref(one), ref(two))
    assert graph.close_atoms({"atom-0"}) == {"atom-0"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("extensions", {"x-extra": "changed"}),
        ("requires_atoms", ["missing"]),
        ("conflicts_with", ["atom-0"]),
    ],
)
def test_duplicate_full_content_not_only_statement(
    tmp_path: Path, field: str, value: Any
) -> None:
    fixture = ReusedApprovalFixture.create(tmp_path)
    one = fixture.publish()

    def amend(raw: dict[str, Any]) -> None:
        if field == "extensions":
            raw["semantic_payload"]["atoms"][0][field].update(value)
        else:
            raw["semantic_payload"]["atoms"][0][field] = value

    two = fixture.publish(capsule_id="com.example.two", amend=amend)
    with pytest.raises(CompileError, match="^DUPLICATE_ATOM$"):
        resolve_graph(admit(fixture, (one, two)), task_context())


def test_zero_admitted_root_payload_is_unusable(fixture: M4Fixture) -> None:
    publication = fixture.publish(
        provides=("auth/v2",), atoms=({"scope": ("environment:dev",)},)
    )
    task = task_context(required_interfaces=("auth/v2",))
    with pytest.raises(CompileError, match="^MISSING_INTERFACE$"):
        resolve_graph(admit(fixture, (publication,), task), task)


def test_partial_dependency_provider_blocks_before_selection(
    fixture: M4Fixture,
) -> None:
    provider = fixture.publish(
        provides=("auth/v2",),
        atoms=({"atom_id": "a"}, {"atom_id": "b", "scope": ("environment:dev",)}),
    )
    consumer = fixture.publish(
        capsule_id="com.example.consumer",
        atoms=({"atom_id": "c"},),
        amend=dependencies(("auth@>=1",), (provider,)),
    )
    with pytest.raises(CompileError, match="^MISSING_DEPENDENCY$"):
        resolve_graph(admit(fixture, (consumer, provider)), task_context())


def test_required_atom_missing_is_safe(fixture: M4Fixture) -> None:
    publication = fixture.publish()
    task = task_context(required_atom_ids=("denied",))
    with pytest.raises(CompileError, match="^MISSING_ATOM$"):
        resolve_graph(admit(fixture, (publication,), task), task)


def test_multiple_locked_dependency_providers_still_ambiguous(
    fixture: M4Fixture,
) -> None:
    one = fixture.publish(provides=("auth/v1",), atoms=({"atom_id": "one"},))
    two = fixture.publish(
        capsule_id="com.example.two", provides=("auth/v2",), atoms=({"atom_id": "two"},)
    )
    consumer = fixture.publish(
        capsule_id="com.example.consumer",
        atoms=({"atom_id": "consumer"},),
        amend=dependencies(("auth@>=1",), (one, two)),
    )
    with pytest.raises(CompileError, match="^AMBIGUOUS_PROVIDER$"):
        resolve_graph(admit(fixture, (one, two, consumer)), task_context())


@pytest.mark.parametrize(
    "field,declaration",
    [("requires", "auth@^1"), ("conflicts", "auth@"), ("conflicts", "auth")],
)
def test_invalid_manifest_declaration_is_safe(
    fixture: M4Fixture, field: str, declaration: str
) -> None:
    def amend(raw: dict[str, Any]) -> None:
        raw["control_manifest"][field] = [declaration]

    publication = fixture.publish(amend=amend)
    with pytest.raises(CompileError, match="^INVALID_VERSION_CONSTRAINT$"):
        resolve_graph(admit(fixture, (publication,)), task_context())


def test_cross_capsule_atom_dependency_requires_lock(fixture: M4Fixture) -> None:
    provider = fixture.publish(atoms=({"atom_id": "target"},))
    consumer = fixture.publish(
        capsule_id="com.example.consumer",
        atoms=({"atom_id": "source"},),
        amend=dependencies((), (), (edge("source", "target"),)),
    )
    with pytest.raises(CompileError, match="^MISSING_DEPENDENCY$"):
        resolve_graph(admit(fixture, (consumer, provider)), task_context())


def test_capsule_self_cycle_forces_payload_and_terminates(fixture: M4Fixture) -> None:
    publication = fixture.publish(
        atoms=({"atom_id": "a"}, {"atom_id": "b"}),
        amend=dependencies((), (), (edge("com.example.policy", "com.example.policy"),)),
    )
    graph = resolve_graph(admit(fixture, (publication,)), task_context())
    assert graph.close_atoms({"a"}) == {"a", "b"}


def test_partial_capsule_target_cannot_be_required(fixture: M4Fixture) -> None:
    provider = fixture.publish(
        atoms=({"atom_id": "a"}, {"atom_id": "b", "scope": ("environment:dev",)})
    )
    consumer = fixture.publish(
        capsule_id="com.example.consumer",
        atoms=({"atom_id": "source"},),
        amend=dependencies((), (provider,), (edge("source", "com.example.policy"),)),
    )
    with pytest.raises(CompileError, match="^MISSING_DEPENDENCY$"):
        resolve_graph(admit(fixture, (provider, consumer)), task_context())


def test_deduplicated_atom_conflict_matches_any_selected_owner(tmp_path: Path) -> None:
    fixture = ReusedApprovalFixture.create(tmp_path)
    one = fixture.publish()
    two = fixture.publish(capsule_id="com.example.two", version="2.0.0")

    def amend(raw: dict[str, Any]) -> None:
        raw["dependency_graph"]["edges"] = [
            edge(
                "com.example.other", "atom-0", "conflicts", constraint=">=2"
            ).model_dump(mode="json")
        ]

    other = fixture.publish(capsule_id="com.example.other", amend=amend)
    graph = resolve_graph(admit(fixture, (one, two, other)), task_context())
    assert len(graph.conflicts_for({"atom-0"})) == 1


def test_capsule_edge_selects_only_complete_locked_unit(fixture: M4Fixture) -> None:
    partial = fixture.publish(
        atoms=({"atom_id": "partial", "scope": ("environment:dev",)},)
    )
    complete = fixture.publish(version="2.0.0", atoms=({"atom_id": "complete"},))
    consumer = fixture.publish(
        capsule_id="com.example.consumer",
        atoms=({"atom_id": "source"},),
        amend=dependencies(
            (), (partial, complete), (edge("source", "com.example.policy"),)
        ),
    )
    graph = resolve_graph(admit(fixture, (partial, complete, consumer)), task_context())
    assert graph.close_atoms({"source"}) == {"source", "complete"}
