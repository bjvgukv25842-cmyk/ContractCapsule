"""Exact composition and effect-time admission for the trusted twin host."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from contractcapsule.compile.validation import stamp
from contractcapsule.models.view import CompiledView, compile_request_projection
from contractcapsule.swap.trees import RunnerError
from contractcapsule.swap.twin_models import AdmissionCheck
from contractcapsule.validate.approvals import Approval, ApprovalVerifier
from contractcapsule.validate.artifacts import core_projection
from contractcapsule.validate.integrity import ValidationService
from contractcapsule.validate.models import BoundExecution
from contractcapsule.validate.reports import IndependentReport
from contractcapsule.validate.run_models import identity


@dataclass(frozen=True)
class ExecutionPolicy:
    """Host policy capability; configuration changes require a new bound attempt.

    The callback is a current local revocation read, not remote atomicity.
    """

    configuration_digest: str
    is_revoked: Callable[[Approval], bool]

    def check(self, approval: Approval) -> None:
        value = self.is_revoked(approval)
        if type(value) is not bool or value:
            raise RunnerError("execution policy denied")


def utc_stamp(now: datetime) -> str:
    if (
        type(now) is not datetime
        or now.tzinfo is None
        or now.utcoffset() != timedelta(0)
    ):
        raise RunnerError("explicit UTC clock required")
    return now.isoformat(timespec="microseconds").replace("+00:00", "Z")


def compile_lock(service: ValidationService) -> dict:
    value = compile_request_projection(service.request)
    value["expected_manifest_digest"] = service.request.expected_manifest_digest
    return value


def check_requests(
    bound: BoundExecution, services: tuple[ValidationService, ValidationService]
) -> None:
    expected = bound.request
    for service, root in zip(services, (expected.old, expected.new), strict=True):
        request = service.request
        for field in (
            "task",
            "principal",
            "budget",
            "model_id",
            "tokenizer_profile",
            "renderer_version",
        ):
            if getattr(request, field) != getattr(expected, field):
                raise RunnerError("compile request mismatch")
        members = [core_projection(p.capsule) for p in request.capsules]
        if members.count(core_projection(root.capsule)) != 1:
            raise RunnerError("compile root absent")
        other = expected.new if root is expected.old else expected.old
        if core_projection(other.capsule) in members:
            raise RunnerError("opposite candidate in compile collection")
        locked_commit = request.runtime_config.get(
            "source_commit", expected.source_commit
        )
        if locked_commit != expected.source_commit:
            raise RunnerError("compile source commit mismatch")
    old, new = (s.request for s in services)
    if old.runtime_config != new.runtime_config or old.as_of != new.as_of:
        raise RunnerError("compile configuration mismatch")


def validate_view(
    service: ValidationService, view: CompiledView
) -> tuple[IndependentReport, ...]:
    capsules = [p.capsule for p in service.request.capsules]
    reports: list[IndependentReport] = []
    for capsule in capsules:
        for report in (
            service.validate_integrity(capsule),
            service.validate_evidence(capsule),
        ):
            service.verify_report(report, [capsule])
            reports.append(report)
    compression = service.validate_compression(view, capsules)
    service.verify_report(compression, capsules, view=view)
    reports.append(compression)
    return tuple(reports)


def admission(
    bound: BoundExecution,
    approval: Approval,
    verifier: ApprovalVerifier,
    policy: ExecutionPolicy,
    now: datetime,
    services: tuple[ValidationService, ValidationService],
    views: tuple[CompiledView, CompiledView],
) -> AdmissionCheck:
    stamp = utc_stamp(now)
    verifier.verify_execution(approval, bound, now=now)
    policy.check(approval)
    reports = tuple(
        r
        for service, view in zip(services, views, strict=True)
        for r in validate_view(service, view)
    )
    return AdmissionCheck.model_validate(
        {
            "checked_at": stamp,
            "policy_configuration": policy.configuration_digest,
            "approval_digest": identity(approval.model_dump(mode="json")),
            "reports": tuple(r.model_dump() for r in reports),
        }
    )


def service_configuration(service: ValidationService) -> dict:
    compiler = service.compiler
    return {
        "services": [
            stamp(name, component).model_dump(mode="json")
            for name, component in (
                ("ranker", compiler.ranker),
                ("tokenizer", compiler.counter),
                ("renderer", compiler.renderer),
                ("evidence", compiler.evidence),
            )
        ],
        "permission": compiler.authorizer.context_digest(
            service.request.task, service.request.principal
        ),
        "freshness": compiler.freshness.context_digest(),
    }
