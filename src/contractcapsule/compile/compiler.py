"""Explicit, fail-closed composition of the M4 runtime compiler services."""

from __future__ import annotations

from dataclasses import dataclass

from contractcapsule.compile.errors import CompileError
from contractcapsule.compile.evidence import NativeEvidenceResolver
from contractcapsule.compile.protocols import (
    AtomRanker,
    EligibilityAuthorizer,
    FreshnessChecker,
    TokenCounter,
    ViewRenderer,
)
from contractcapsule.compile.validation import validate_request
from contractcapsule.models.view import CompiledView, CompileRequest
from contractcapsule.storage.registry import Registry


@dataclass(frozen=True)
class ViewCompiler:
    registry: Registry
    authorizer: EligibilityAuthorizer
    freshness: FreshnessChecker
    ranker: AtomRanker
    counter: TokenCounter
    evidence: NativeEvidenceResolver
    renderer: ViewRenderer

    def compile_view(self, request: CompileRequest) -> CompiledView:
        from contractcapsule.compile.session import Compilation

        session = Compilation(self)
        try:
            validate_request(request)
            return session.run(request)
        except CompileError as error:
            return session.failure(error.code)
        except Exception:  # noqa: BLE001 - replaceable services may never leak raw faults.
            return session.failure("COMPILATION_FAILED")


def compile_view(request: CompileRequest, *, compiler: ViewCompiler) -> CompiledView:
    return compiler.compile_view(request)
