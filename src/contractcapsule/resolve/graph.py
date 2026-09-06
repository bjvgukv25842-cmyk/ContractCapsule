"""Verified two-level provider and atom graph assembly."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import combinations
from types import MappingProxyType

from contractcapsule.compile.errors import CompileError
from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.models.core import Atom, DependencyEdge, DependencyGraph
from contractcapsule.models.view import (
    CapsuleRef,
    ClosureLink,
    Conflict,
    ProviderWitness,
    TaskContext,
)
from contractcapsule.resolve.closure import dependency_closure
from contractcapsule.resolve.conflicts import detect_conflicts
from contractcapsule.resolve.eligibility import AdmissionResult
from contractcapsule.resolve.policies import snapshot_digest
from contractcapsule.resolve.versions import (
    constraint_terms,
    parse_interface,
    satisfies,
)
from contractcapsule.storage.registry import PublishedCapsule

_PRIVATE = "__ccs_m4__:"


def _presence(ref: CapsuleRef) -> str:
    return _PRIVATE + "presence:" + ref.key


def _unit(ref: CapsuleRef) -> str:
    return _PRIVATE + "unit:" + ref.key


def _ref(publication: PublishedCapsule) -> CapsuleRef:
    manifest = publication.capsule.control_manifest
    return CapsuleRef(
        capsule_id=manifest.capsule_id,
        version=manifest.version,
        digest=manifest.content_digest,
    )


def _requirement(value: str) -> tuple[str, str]:
    family, separator, constraint = value.partition("@")
    if not separator or "@" in constraint:
        raise CompileError("INVALID_VERSION_CONSTRAINT")
    parsed, _ = parse_interface(family + "/v0")
    constraint_terms(constraint)
    return parsed, constraint


@dataclass(frozen=True)
class ResolvedGraph:
    """Internal verified graph; private capsule nodes never become rendered atoms."""

    atoms: Mapping[str, Atom]
    owners: Mapping[str, tuple[CapsuleRef, ...]]
    publications: Mapping[str, PublishedCapsule] = field(repr=False)
    graph: DependencyGraph
    root_atom_ids: frozenset[str]
    providers: tuple[ProviderWitness, ...]
    config_digest: str
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        for name in ("atoms", "owners", "publications"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def _closed_nodes(self, selected: set[str]) -> set[str]:
        if not selected <= self.atoms.keys():
            raise CompileError("MISSING_ATOM")
        closed = dependency_closure(selected, self.graph)
        markers = {
            node
            for publication in self.publications.values()
            for node in (_presence(_ref(publication)), _unit(_ref(publication)))
        }
        if closed - self.atoms.keys() - markers:
            raise CompileError("MISSING_DEPENDENCY")
        return closed

    def close_atoms(self, selected: set[str]) -> set[str]:
        return self._closed_nodes(selected) & self.atoms.keys()

    def conflicts_for(self, selected: set[str]) -> tuple[Conflict, ...]:
        return tuple(detect_conflicts(self._closed_nodes(selected), self.graph))

    def closure_links(self, selected: set[str]) -> tuple[ClosureLink, ...]:
        closed = self._closed_nodes(selected)
        return tuple(
            ClosureLink(source=edge.source, target=edge.target)
            for edge in self.graph.edges
            if edge.edge_type == "requires"
            and edge.mandatory
            and edge.source in closed
            and edge.target in closed
        )


@dataclass
class _Assembly:
    atoms: dict[str, Atom] = field(default_factory=dict)
    owners: dict[str, tuple[CapsuleRef, ...]] = field(default_factory=dict)
    publications: dict[str, PublishedCapsule] = field(default_factory=dict)
    refs: dict[str, CapsuleRef] = field(default_factory=dict)
    complete: set[str] = field(default_factory=set)
    known_atoms: set[str] = field(default_factory=set)
    edges: dict[tuple[str, str, str], DependencyEdge] = field(default_factory=dict)
    providers: list[ProviderWitness] = field(default_factory=list)

    def add(
        self, source: str, target: str, kind: str = "requires", mandatory: bool = True
    ) -> None:
        key = (source, target, kind)
        previous = self.edges.get(key)
        self.edges[key] = DependencyEdge.model_validate(
            {
                "source": source,
                "target": target,
                "edge_type": kind,
                "mandatory": mandatory or (previous is not None and previous.mandatory),
                "version_constraint": None,
            }
        )

    def inventory(self, admission: AdmissionResult) -> None:
        for item in sorted(admission.items, key=lambda item: _ref(item.published).key):
            reference = _ref(item.published)
            self.refs[reference.key] = reference
            self.publications[reference.key] = item.published
            payload = item.published.capsule.semantic_payload.atoms
            ids = {atom.atom_id for atom in payload}
            self.known_atoms.update(ids)
            if ids and ids <= set(item.atom_ids):
                self.complete.add(reference.key)
            for atom in payload:
                if atom.atom_id in item.atom_ids:
                    self._admit_atom(atom, reference)
        names = self.known_atoms | {ref.capsule_id for ref in self.refs.values()}
        if any(name.startswith(_PRIVATE) for name in names):
            raise CompileError("INVALID_GRAPH")

    def _admit_atom(self, atom: Atom, reference: CapsuleRef) -> None:
        previous = self.atoms.get(atom.atom_id)
        if previous is not None and canonical_json_bytes(
            previous.model_dump(mode="json")
        ) != canonical_json_bytes(atom.model_dump(mode="json")):
            raise CompileError("DUPLICATE_ATOM")
        self.atoms[atom.atom_id] = atom
        owners = {ref.key: ref for ref in self.owners.get(atom.atom_id, ())}
        owners[reference.key] = reference
        self.owners[atom.atom_id] = tuple(owners[key] for key in sorted(owners))
        # Presence activates dependencies/conflicts; only an explicit unit loads siblings.
        self.add(atom.atom_id, _presence(reference))
        self.add(_unit(reference), atom.atom_id)

    def _payload(self, reference: CapsuleRef) -> tuple[str, ...]:
        return tuple(
            sorted(
                atom.atom_id
                for atom in self.publications[
                    reference.key
                ].capsule.semantic_payload.atoms
            )
        )

    def witness(
        self, consumer: CapsuleRef | None, requirement: str, provider: CapsuleRef
    ) -> None:
        self.providers.append(
            ProviderWitness(
                consumer=consumer,
                requirement=requirement,
                provider=provider,
                atom_ids=self._payload(provider),
            )
        )

    @staticmethod
    def unique(candidates: list[CapsuleRef], missing: str) -> CapsuleRef:
        if not candidates:
            raise CompileError(missing)
        if len(candidates) != 1:
            raise CompileError("AMBIGUOUS_PROVIDER")
        return candidates[0]

    def roots(self, task: TaskContext) -> frozenset[str]:
        roots: set[str] = set()
        for requirement in task.required_interfaces:
            parse_interface(requirement)
            candidates = [
                ref
                for key, ref in self.refs.items()
                if key in self.complete
                and requirement
                in self.publications[key].capsule.control_manifest.provides
            ]
            provider = self.unique(candidates, "MISSING_INTERFACE")
            roots.update(self._payload(provider))
            self.witness(None, requirement, provider)
        if not set(task.required_atom_ids) <= self.atoms.keys():
            raise CompileError("MISSING_ATOM")
        return frozenset(roots)

    def locked(self, consumer: CapsuleRef, provider: CapsuleRef) -> bool:
        locks = self.publications[
            consumer.key
        ].capsule.tests_integrity.lock.capsule_dependencies
        return any(
            (lock.capsule_id, lock.version, lock.digest)
            == (provider.capsule_id, provider.version, provider.digest)
            for lock in locks
        )

    def matching(self, declaration: str) -> list[CapsuleRef]:
        family, constraint = _requirement(declaration)
        return [
            ref
            for key, ref in self.refs.items()
            if any(
                parse_interface(value)[0] == family
                for value in self.publications[key].capsule.control_manifest.provides
            )
            and satisfies(ref.version, constraint)
        ]

    def manifests(self) -> None:
        for key, consumer in self.refs.items():
            manifest = self.publications[key].capsule.control_manifest
            for requirement in sorted(set(manifest.requires)):
                candidates = [
                    provider
                    for provider in self.matching(requirement)
                    if provider.key in self.complete and self.locked(consumer, provider)
                ]
                provider = self.unique(candidates, "MISSING_DEPENDENCY")
                self.add(_presence(consumer), _unit(provider))
                self.witness(consumer, requirement, provider)
            for declaration in manifest.conflicts:
                for provider in self.matching(declaration):
                    self.add(_presence(consumer), _presence(provider), "conflicts")
        for left, right in combinations(self.refs.values(), 2):
            if left.capsule_id == right.capsule_id:
                self.add(_presence(left), _presence(right), "conflicts")

    def nodes(self, name: str) -> tuple[str, ...]:
        if name.startswith(_PRIVATE):
            raise CompileError("INVALID_GRAPH")
        refs = tuple(
            _presence(ref) for ref in self.refs.values() if ref.capsule_id == name
        )
        if refs and name in self.known_atoms:
            raise CompileError("AMBIGUOUS_GRAPH_NODE")
        return refs or (name,)

    def node_owners(self, node: str) -> tuple[CapsuleRef, ...]:
        if node in self.owners:
            return self.owners[node]
        return tuple(ref for ref in self.refs.values() if node == _presence(ref))

    def _required_target(
        self, source: str, target: str, declaring: CapsuleRef | None = None
    ) -> str:
        consumers = (declaring,) if declaring is not None else self.node_owners(source)
        providers = self.node_owners(target)
        for consumer in consumers:
            for provider in providers:
                if consumer != provider and not self.locked(consumer, provider):
                    raise CompileError("MISSING_DEPENDENCY")
                if consumer != provider:
                    self.providers.append(
                        ProviderWitness(
                            consumer=consumer,
                            requirement=f"requires:{source}->{target}",
                            provider=provider,
                            atom_ids=self._payload(provider)
                            if target.startswith(_PRIVATE)
                            else (target,),
                        )
                    )
        if target.startswith(_PRIVATE):
            provider = providers[0]
            if provider.key not in self.complete:
                raise CompileError("MISSING_DEPENDENCY")
            return _unit(provider)
        return target

    def explicit(self, edge: DependencyEdge, declaring: CapsuleRef) -> None:
        if edge.version_constraint is not None:
            constraint_terms(edge.version_constraint)
        sources, targets = self.nodes(edge.source), self.nodes(edge.target)
        payload = self.publications[declaring.key].capsule.semantic_payload.atoms
        if edge.source not in {
            declaring.capsule_id,
            *(atom.atom_id for atom in payload),
        }:
            raise CompileError("INVALID_GRAPH")
        if edge.source == declaring.capsule_id:
            sources = (_presence(declaring),)
        if not self.node_owners(sources[0]) and edge.source not in self.known_atoms:
            raise CompileError("INVALID_GRAPH")
        for source in sources:
            if not self.node_owners(source):
                continue
            for target in self._targets_for(source, targets, edge, declaring):
                if not self._version_matches(target, edge):
                    if edge.edge_type == "requires" and edge.mandatory:
                        raise CompileError("MISSING_DEPENDENCY")
                    continue
                resolved = (
                    self._required_target(source, target, declaring)
                    if edge.edge_type == "requires" and edge.mandatory
                    else target
                )
                self.add(source, resolved, edge.edge_type, edge.mandatory)

    def _targets_for(
        self,
        source: str,
        targets: tuple[str, ...],
        edge: DependencyEdge,
        declaring: CapsuleRef,
    ) -> tuple[str, ...]:
        if not (
            edge.edge_type == "requires"
            and edge.mandatory
            and targets[0].startswith(_PRIVATE)
        ):
            return targets
        candidates = [
            self.node_owners(target)[0]
            for target in targets
            if self.node_owners(target)[0].key in self.complete
            and self._version_matches(target, edge)
            and all(
                consumer == self.node_owners(target)[0]
                or self.locked(consumer, self.node_owners(target)[0])
                for consumer in (declaring,)
            )
        ]
        provider = self.unique(candidates, "MISSING_DEPENDENCY")
        return (_presence(provider),)

    def _version_matches(self, target: str, edge: DependencyEdge) -> bool:
        if edge.version_constraint is None or edge.edge_type not in {
            "requires",
            "conflicts",
        }:
            return True
        matches = tuple(
            satisfies(ref.version, edge.version_constraint)
            for ref in self.node_owners(target)
        )
        return any(matches) if edge.edge_type == "conflicts" else all(matches)

    def atomic_edges(self) -> None:
        for atom in self.atoms.values():
            for target in atom.requires_atoms:
                if target.startswith(_PRIVATE):
                    raise CompileError("INVALID_GRAPH")
                self.add(atom.atom_id, self._required_target(atom.atom_id, target))
            for target in atom.conflicts_with:
                if target.startswith(_PRIVATE):
                    raise CompileError("INVALID_GRAPH")
                self.add(atom.atom_id, target, "conflicts")
        for publication in self.publications.values():
            for edge in publication.capsule.dependency_graph.edges:
                self.explicit(edge, _ref(publication))


def resolve_graph(admission: AdmissionResult, task: TaskContext) -> ResolvedGraph:
    assembly = _Assembly()
    assembly.inventory(admission)
    roots = assembly.roots(task)
    assembly.manifests()
    assembly.atomic_edges()
    graph = DependencyGraph(
        edges=tuple(assembly.edges[key] for key in sorted(assembly.edges))
    )
    witnesses = {
        canonical_json_bytes(witness.model_dump(mode="json")): witness
        for witness in assembly.providers
    }
    providers = tuple(witnesses[key] for key in sorted(witnesses))
    return ResolvedGraph(
        atoms=dict(sorted(assembly.atoms.items())),
        owners=dict(sorted(assembly.owners.items())),
        publications=assembly.publications,
        graph=graph,
        root_atom_ids=roots,
        providers=providers,
        config_digest=snapshot_digest(
            {"version": "1.0.0", "profile": "CCS-2.1-m4-collective-interfaces-v1"}
        ),
    )
