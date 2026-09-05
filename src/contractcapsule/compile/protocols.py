"""Explicit replaceable service boundaries; none grants authority by default."""

from typing import Protocol

from contractcapsule.models.base import Principal
from contractcapsule.models.core import Atom, Capsule
from contractcapsule.models.view import EvidenceMaterial, RankedAtom, TaskContext
from contractcapsule.storage.registry import PublishedCapsule


class EligibilityAuthorizer(Protocol):
    version: str

    def authorize(
        self,
        capsule: Capsule,
        atom: Atom | None,
        task: TaskContext,
        principal: Principal,
    ) -> bool: ...

    def context_digest(self, task: TaskContext, principal: Principal) -> str: ...


class FreshnessChecker(Protocol):
    version: str

    def check(self, capsule: Capsule, atom: Atom | None, as_of: str) -> bool: ...

    def context_digest(self) -> str: ...


class AtomRanker(Protocol):
    version: str

    def rank_atoms(self, atoms: list[Atom], task: TaskContext) -> list[RankedAtom]: ...


class TokenCounter(Protocol):
    profile: str
    model_id: str
    version: str
    config_digest: str

    def count(self, text: str) -> int: ...


class EvidenceHandleResolver(Protocol):
    version: str

    def resolve(
        self,
        capsule: PublishedCapsule,
        atom: Atom,
        principal: Principal,
        task: TaskContext,
        as_of: str,
    ) -> tuple[EvidenceMaterial, ...]: ...


class ViewRenderer(Protocol):
    version: str

    def render(
        self,
        task: TaskContext,
        atoms: tuple[RankedAtom, ...],
        evidence: tuple[EvidenceMaterial, ...],
    ) -> tuple[tuple[str, str], ...]: ...
