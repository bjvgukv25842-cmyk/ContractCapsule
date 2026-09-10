"""Explicit local services supplied by the trusted composition root."""

from typing import Protocol

from contractcapsule.storage.registry import PublishedCapsule
from contractcapsule.validate.models import Artifact


class ArtifactResolver(Protocol):
    def resolve(self, publication: PublishedCapsule) -> tuple[Artifact, ...]: ...
