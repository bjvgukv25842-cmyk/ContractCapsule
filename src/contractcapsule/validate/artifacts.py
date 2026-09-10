"""Configured local package byte snapshots."""

import hashlib
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from contractcapsule.models import Capsule
from contractcapsule.models.canonical import capsule_wire_dict
from contractcapsule.package import load_capsule
from contractcapsule.storage.registry import PublishedCapsule
from contractcapsule.validate.models import Artifact


def publication_projection(publication: PublishedCapsule) -> dict[str, Any]:
    return {
        "capsule": core_projection(publication.capsule),
        "registry_status": publication.registry_status,
    }


def core_projection(capsule: Capsule) -> dict[str, Any]:
    raw = capsule_wire_dict(capsule)
    raw.pop("derived_artifacts")
    raw.pop("runtime_sidecar")
    return raw


def read_regular(root: Path, relative: str) -> bytes:
    """Open without following links; bytes, never a later mutable path, are used."""
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = relative.split("/")
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = child
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("nonregular artifact")
            return stream.read()
    finally:
        os.close(directory)


@dataclass(frozen=True)
class LocalArtifactResolver:
    packages: Mapping[str, Path]

    def __init__(self, packages: Mapping[str, Path]) -> None:
        object.__setattr__(self, "packages", MappingProxyType(dict(packages)))

    def resolve(self, publication: PublishedCapsule) -> tuple[Artifact, ...]:
        root = self.packages[publication.capsule.control_manifest.content_digest]
        loaded = load_capsule(root)
        if core_projection(loaded) != core_projection(publication.capsule):
            raise ValueError("package differs from Registry")
        artifacts = []
        for test in loaded.tests_integrity.tests:
            data = read_regular(root, test.path)
            if "sha256:" + hashlib.sha256(data).hexdigest() != test.digest:
                raise ValueError("artifact bytes changed")
            artifacts.append(
                Artifact(
                    test_id=test.test_id,
                    path=test.path,
                    kind=test.kind,
                    digest=test.digest,
                    data=data,
                )
            )
        return tuple(artifacts)
