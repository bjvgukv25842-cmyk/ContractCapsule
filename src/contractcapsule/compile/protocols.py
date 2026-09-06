"""Explicit replaceable service boundaries; none grants authority by default."""

from typing import Protocol

from contractcapsule.models.base import Principal
from contractcapsule.models.core import Atom, Capsule
from contractcapsule.models.view import EvidenceMaterial, RankedAtom, TaskContext
from contractcapsule.storage.registry import PublishedCapsule


class EligibilityAuthorizer(Protocol):
    @property
    def version(self) -> str: ...

    def authorize(
        self,
        capsule: Capsule,
        atom: Atom | None,
        task: TaskContext,
        principal: Principal,
    ) -> bool: ...

    def context_digest(self, task: TaskContext, principal: Principal) -> str: ...


class FreshnessChecker(Protocol):
    @property
    def version(self) -> str: ...

    def check(self, capsule: Capsule, atom: Atom | None, as_of: str) -> bool: ...

    def context_digest(self) -> str: ...


class AtomRanker(Protocol):
    @property
    def version(self) -> str: ...

    def rank_atoms(self, atoms: list[Atom], task: TaskContext) -> list[RankedAtom]: ...


class TokenCounter(Protocol):
    @property
    def profile(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def config_digest(self) -> str: ...

    def count(self, text: str) -> int: ...


class EvidenceHandleResolver(Protocol):
    @property
    def version(self) -> str: ...

    def resolve(
        self,
        capsule: PublishedCapsule,
        atom: Atom,
        principal: Principal,
        task: TaskContext,
        as_of: str,
    ) -> tuple[EvidenceMaterial, ...]: ...


class ViewRenderer(Protocol):
    @property
    def version(self) -> str: ...

    def render(
        self,
        task: TaskContext,
        atoms: tuple[RankedAtom, ...],
        evidence: tuple[EvidenceMaterial, ...],
    ) -> tuple[tuple[str, str], ...]: ...
