"""Immutable local storage interfaces for M2."""

from contractcapsule.storage.cas import BlobRef, FilesystemCAS
from contractcapsule.storage.registry import PublishedCapsule, Registry

__all__ = ["BlobRef", "FilesystemCAS", "PublishedCapsule", "Registry"]
