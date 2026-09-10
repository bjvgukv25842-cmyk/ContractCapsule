"""Request-scoped independent validation with current, privacy-safe admission."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, TypeVar, cast

from contractcapsule.compile.compiler import ViewCompiler
from contractcapsule.compile.errors import CompileError
from contractcapsule.compile.evidence import NativeEvidenceResolver
from contractcapsule.compile.renderers import NeutralViewRenderer
from contractcapsule.compile.validation import original_values, stamp, validate_request
from contractcapsule.models.core import Capsule
from contractcapsule.models.view import (
    CompiledView,
    CompileRequest,
    compile_request_projection,
)
from contractcapsule.resolve.eligibility import AdmissionResult, EligibilityResolver
from contractcapsule.resolve.graph import resolve_graph
from contractcapsule.resolve.policies import snapshot_digest
from contractcapsule.validate.artifacts import (
    LocalArtifactResolver,
    core_projection,
    publication_projection,
)
from contractcapsule.validate.compression import check_compression
from contractcapsule.validate.evidence import verified_materials
from contractcapsule.validate.journal import RecordError, RecordJournal
from contractcapsule.validate.reports import (
    CompressionReport,
    EvidenceReport,
    IndependentReport,
    IntegrityReport,
)

R = TypeVar("R", bound=IndependentReport)


@dataclass(frozen=True)
class ValidationService:
    """Host composition; reports attest this instant, never activation authority.

    Consumers revalidate immediately before effects and serialize policy updates
    with their state owner. Do not export the journal or artifact capabilities.
    """

    request: CompileRequest
    compiler: ViewCompiler
    artifacts: LocalArtifactResolver
    journal: RecordJournal
    clock: Callable[[], datetime]

    def _now(self) -> str:
        now = self.clock()
        if (
            type(now) is not datetime
            or now.tzinfo is None
            or now.utcoffset() != timedelta(0)
        ):
            raise CompileError("INVALID_CLOCK")
        return now.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def _configuration(self) -> str:
        c = self.compiler
        if (
            self.journal.registry is not c.registry
            or type(self.artifacts) is not LocalArtifactResolver
            or type(c.evidence) is not NativeEvidenceResolver
            or type(c.renderer) is not NeutralViewRenderer
            or c.evidence.registry is not c.registry
            or c.evidence.authorizer is not c.authorizer
            or c.evidence.freshness is not c.freshness
            or c.counter.model_id != self.request.model_id
            or c.counter.profile != self.request.tokenizer_profile
            or c.renderer.version != self.request.renderer_version
        ):
            raise CompileError("INVALID_CONFIGURATION")
        return snapshot_digest(
            {
                "profile": "ccs-m5-validation/1.0.0",
                "services": [
                    stamp(name, service).model_dump(mode="json")
                    for name, service in (
                        ("ranker", c.ranker),
                        ("tokenizer", c.counter),
                        ("renderer", c.renderer),
                        ("evidence", c.evidence),
                    )
                ],
                "permission": c.authorizer.context_digest(
                    self.request.task, self.request.principal
                ),
                "freshness": c.freshness.context_digest(),
                "artifacts": {
                    key: str(path) for key, path in self.artifacts.packages.items()
                },
            }
        )

    def _admit(self, now: str) -> AdmissionResult:
        c, request = self.compiler, self.request
        return EligibilityResolver(c.registry, c.authorizer, c.freshness, now).resolve(
            request.capsules, request.task, request.principal
        )

    def _current(self, historical: AdmissionResult, now: str) -> AdmissionResult:
        current = self._admit(now)
        if (
            current.items != historical.items
            or current.rejected_counts != historical.rejected_counts
        ):
            raise CompileError("CURRENT_ADMISSION_DENIED")
        return current

    def _capsules(self, capsules: list[Capsule], *, complete: bool) -> None:
        if type(capsules) is not list or not capsules:
            raise CompileError("INVALID_CAPSULE_SET")
        requested = [core_projection(pub.capsule) for pub in self.request.capsules]
        supplied = []
        for capsule in capsules:
            if type(capsule) is not Capsule:
                raise CompileError("INVALID_CAPSULE_SET")
            Capsule.model_validate(original_values(capsule))
            projection = core_projection(capsule)
            if projection not in requested:
                raise CompileError("INVALID_CAPSULE_SET")
            supplied.append(projection)
        if complete and sorted(map(snapshot_digest, supplied)) != sorted(
            map(snapshot_digest, requested)
        ):
            raise CompileError("INVALID_CAPSULE_SET")

    def _artifacts(
        self, capsules: list[Capsule], admission: AdmissionResult
    ) -> list[dict[str, str]]:
        import hashlib

        verified = {
            snapshot_digest(core_projection(item.published.capsule)): item.published
            for item in admission.items
        }
        result = []
        for capsule in capsules:
            publication = verified.get(snapshot_digest(core_projection(capsule)))
            if publication is None:
                raise CompileError("CURRENT_ADMISSION_DENIED")
            artifacts = self.artifacts.resolve(publication)
            tests = capsule.tests_integrity.tests
            expected = {(t.test_id, t.path, t.kind, t.digest) for t in tests}
            actual = {(a.test_id, a.path, a.kind, a.digest) for a in artifacts}
            if (
                len(expected) != len(tests)
                or len({test.test_id for test in tests}) != len(tests)
                or len({test.path for test in tests}) != len(tests)
                or len(actual) != len(artifacts)
                or actual != expected
            ):
                raise CompileError("ARTIFACT_INTEGRITY")
            for artifact in artifacts:
                if (
                    "sha256:" + hashlib.sha256(artifact.data).hexdigest()
                    != artifact.digest
                ):
                    raise CompileError("ARTIFACT_INTEGRITY")
                result.append(
                    {
                        "capsule": snapshot_digest(publication_projection(publication)),
                        "test_id": artifact.test_id,
                        "path": artifact.path,
                        "kind": artifact.kind,
                        "digest": artifact.digest,
                    }
                )
        return result

    def _binding(
        self,
        kind: str,
        capsules: list[Capsule],
        view: CompiledView | None,
        config: str,
        artifacts: list[dict[str, str]],
    ) -> tuple[str, str]:
        request = compile_request_projection(self.request)
        request["expected_manifest_digest"] = self.request.expected_manifest_digest
        scope = snapshot_digest({"request": request, "configuration": config})
        subject = snapshot_digest(
            {
                "kind": kind,
                "scope": scope,
                "capsules": sorted(
                    snapshot_digest(core_projection(c)) for c in capsules
                ),
                "artifacts": artifacts,
                "view": None if view is None else view.model_dump(mode="json"),
            }
        )
        return scope, subject

    def _evaluate(
        self, report_type: type[R], capsules: list[Capsule], view: CompiledView | None
    ) -> R:
        now: str | None = None
        try:
            now = self._now()
            validate_request(self.request)
            config = self._configuration()
            historical = self._admit(self.request.as_of)
            current = self._current(historical, now)
            self._capsules(capsules, complete=view is not None)
            artifacts = self._artifacts(capsules, current)
            tokens = None
            if report_type is not IntegrityReport:
                graph = resolve_graph(historical, self.request.task)
                sources = verified_materials(
                    graph, self.request, self.compiler.evidence, now
                )
                if view is not None:
                    tokens = check_compression(
                        view, self.request, self.compiler, graph, sources, historical
                    )
            self._current(historical, self._now())
            if config != self._configuration():
                raise CompileError("CURRENT_ADMISSION_DENIED")
            kind = report_type.model_fields["kind"].default
            scope, subject = self._binding(kind, capsules, view, config, artifacts)
            report = report_type(
                kind=cast(Literal["integrity", "evidence", "compression"], kind),
                valid=True,
                validated_at=now,
                scope_digest=scope,
                subject_digest=subject,
                tokens=tokens,
            )
            record = self.journal.append(
                kind=kind, scope=scope, subject=subject, payload=report.payload_bytes()
            )
            return report.model_copy(update={"record": record})
        except Exception:  # noqa: BLE001 - failures never disclose prior identities.
            return self._failure(report_type, now)

    def _failure(self, report_type: type[R], now: str | None) -> R:
        kind = cast(
            Literal["integrity", "evidence", "compression"],
            report_type.model_fields["kind"].default,
        )
        report = report_type(
            kind=kind, valid=False, blockers=("VALIDATION_FAILED",), validated_at=now
        )
        try:
            record = self.journal.append(
                kind=kind,
                scope="withheld",
                subject="withheld",
                payload=report.payload_bytes(),
            )
            return report.model_copy(update={"record": record})
        except Exception:  # noqa: BLE001 - unavailable journal never permits validation.
            return report.model_copy(
                update={"blockers": ("REPORT_PERSISTENCE_FAILED",)}
            )

    def validate_integrity(self, capsule: Capsule) -> IntegrityReport:
        return self._evaluate(IntegrityReport, [capsule], None)

    def validate_evidence(self, capsule: Capsule) -> EvidenceReport:
        return self._evaluate(EvidenceReport, [capsule], None)

    def validate_compression(
        self, view: CompiledView, capsules: list[Capsule]
    ) -> CompressionReport:
        return self._evaluate(CompressionReport, capsules, view)

    def verify_report(
        self,
        report: IndependentReport,
        capsules: list[Capsule],
        *,
        view: CompiledView | None = None,
    ) -> None:
        """Verify stored exact bytes and current scope; effects require fresh validation."""
        try:
            if (
                type(report) not in {IntegrityReport, EvidenceReport, CompressionReport}
                or not report.valid
            ):
                raise ValueError
            original_values(report)
            validate_request(self.request)
            current = self._current(self._admit(self.request.as_of), self._now())
            self._capsules(capsules, complete=report.kind == "compression")
            if (report.kind == "compression") != (view is not None):
                raise ValueError
            scope, subject = self._binding(
                report.kind,
                capsules,
                view,
                self._configuration(),
                self._artifacts(capsules, current),
            )
            if report.scope_digest != scope or report.subject_digest != subject:
                raise ValueError
            payload = self.journal.verifier().verify(
                report.record, kind=report.kind, scope=scope, subject=subject
            )
            if payload != report.payload_bytes():
                raise ValueError
        except Exception:  # noqa: BLE001 - caller transport is never a proof by construction.
            raise RecordError("record rejected") from None
