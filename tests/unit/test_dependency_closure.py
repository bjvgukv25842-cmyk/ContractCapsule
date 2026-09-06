"""Two-level mandatory closure and verified provider ownership."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

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
