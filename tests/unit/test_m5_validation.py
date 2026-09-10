"""Independent M5 gates against real publications and a lying compiler."""

import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from contractcapsule.compile.budget import LocalTokenCounter
from contractcapsule.models.view import ValidationReport
from contractcapsule.validate.artifacts import LocalArtifactResolver
from contractcapsule.validate.integrity import ValidationService
from contractcapsule.validate.journal import RecordError, RecordJournal, RecordRef
from tests.integration.test_compile_view import pipeline
from tests.m4_helpers import M4Fixture
from tests.unit.test_eligibility import AS_OF


@pytest.fixture(scope="module")
def counter():
    return LocalTokenCounter("offline-test-model")


def setup(root, counter):
    fixture = M4Fixture.create(root)
    pub = fixture.publish(
        atoms=(
            {
                "atom_id": "hard",
                "statement": "Audit always.\n",
                "compression_class": "P0_EXACT",
            },
            {"atom_id": "work", "statement": "token policy.\n"},
        )
    )
    compiler, request = pipeline(fixture, (pub,), counter)
    journal = RecordJournal(fixture.registry, b"j" * 32)
    service = ValidationService(
        request,
        compiler,
        LocalArtifactResolver(
            {
                pub.capsule.control_manifest.content_digest: root / "publication-1",
            }
        ),
        journal,
        lambda: datetime.fromisoformat(AS_OF),
    )
    return service, pub, compiler.compile_view(request)


def test_real_views_have_persisted_independent_reports(tmp_path: Path, counter):
    service, pub, view = setup(tmp_path, counter)
    assert view.validation.valid
    for report in (
        service.validate_integrity(pub.capsule),
        service.validate_evidence(pub.capsule),
        service.validate_compression(view, [pub.capsule]),
    ):
        assert report.valid, report
        assert report.record is not None
        restored = RecordJournal(service.compiler.registry, b"j" * 32)
        payload = restored.verifier().verify(
            report.record,
            kind=report.kind,
            scope=report.scope_digest,
            subject=report.subject_digest,
        )
        assert payload == report.payload_bytes()


@pytest.mark.parametrize("change", ["p0", "p1", "content", "handle", "cost"])
def test_lying_compiler_cannot_certify_its_own_tamper(tmp_path, counter, change):
    service, pub, view = setup(tmp_path, counter)
    if change in {"p0", "p1"}:
        removed = "hard" if change == "p0" else "work"
        decisions = tuple(
            d.model_copy(update={"outcome": "excluded"}) if d.atom_id == removed else d
            for d in view.manifest.decisions
        )
        view = view.model_copy(
            update={
                "manifest": view.manifest.model_copy(update={"decisions": decisions})
            }
        )
    elif change == "content":
        view = view.model_copy(update={"content": view.content + "INJECTED"})
    elif change == "handle":
        view = view.model_copy(update={"evidence_handles": ()})
    else:
        tokens = view.manifest.tokens.model_copy(
            update={"total": 0, "sections": {}, "boundary_adjustment": 0}
        )
        view = view.model_copy(
            update={"manifest": view.manifest.model_copy(update={"tokens": tokens})}
        )
    with patch.object(type(service.compiler), "compile_view", return_value=view):
        report = service.validate_compression(view, [pub.capsule])
    assert not report.valid
    assert report.blockers
    assert not hasattr(report, "activation_receipt")


def test_current_clock_cannot_reuse_historical_validity(tmp_path, counter):
    service, pub, view = setup(tmp_path, counter)
    assert service.validate_compression(view, [pub.capsule]).valid
    future = replace(
        service, clock=lambda: datetime.fromisoformat("2099-01-01T00:00:01+00:00")
    )
    report = future.validate_compression(view, [pub.capsule])
    assert not report.valid
    assert report.subject_digest is None
    assert report.tokens is None
    assert "hard" not in report.model_dump_json()


def test_clearing_compiler_blockers_is_not_validation(tmp_path, counter):
    service, pub, _ = setup(tmp_path, counter)
    request = service.request.model_copy(
        update={
            "budget": service.request.budget.model_copy(
                update={"model_input_tokens": 1}
            )
        }
    )
    service = replace(service, request=request)
    failed = service.compiler.compile_view(request)
    assert not failed.validation.valid
    cleared = failed.model_copy(
        update={
            "validation": ValidationReport(valid=True),
            "manifest": failed.manifest.model_copy(
                update={"validation": ValidationReport(valid=True)}
            ),
        }
    )
    with patch.object(type(service.compiler), "compile_view", return_value=cleared):
        assert not service.validate_compression(cleared, [pub.capsule]).valid


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_digest", "sha256:" + "1" * 64),
        ("permission_digest", "sha256:" + "1" * 64),
        ("task_id", "other-task"),
        ("services", ()),
        ("providers", ()),
    ],
)
def test_lying_compiler_cannot_forge_manifest(tmp_path, counter, field, value):
    service, pub, _ = setup(tmp_path, counter)
    task = service.request.task.model_copy(update={"required_atom_ids": ("hard",)})
    service = replace(
        service, request=service.request.model_copy(update={"task": task})
    )
    view = service.compiler.compile_view(service.request)
    if field == "providers":
        # A spurious provider must also fail in an otherwise provider-free view.
        from contractcapsule.models.view import ProviderWitness

        value = (
            ProviderWitness(
                consumer=None,
                requirement="fake/v1",
                provider=view.manifest.capsules[0],
                atom_ids=("hard",),
            ),
        )
    view = view.model_copy(
        update={"manifest": view.manifest.model_copy(update={field: value})}
    )
    with patch.object(type(service.compiler), "compile_view", return_value=view):
        assert not service.validate_compression(view, [pub.capsule]).valid


def test_clock_may_advance_during_validation(tmp_path, counter):
    service, pub, view = setup(tmp_path, counter)
    times = iter(
        [datetime.fromisoformat(AS_OF), datetime.fromisoformat("2030-01-01T00:00:01Z")]
    )
    service = replace(service, clock=lambda: next(times))
    assert service.validate_compression(view, [pub.capsule]).valid


@pytest.mark.parametrize(
    "mutation",
    [
        "record",
        "timestamp",
        "subject",
        "tokens",
        "task",
        "principal",
        "view",
        "key",
        "kind",
    ],
)
def test_report_transport_and_foreign_scopes_are_not_authority(
    tmp_path, counter, mutation
):
    from contractcapsule.models.base import Principal

    service, pub, view = setup(tmp_path, counter)
    report = service.validate_compression(view, [pub.capsule])
    assert report.valid
    service.verify_report(report, [pub.capsule], view=view)
    if mutation == "record":
        report = report.model_copy(
            update={
                "record": RecordRef(record_id="unknown", digest=report.record.digest)
            }
        )
    elif mutation == "timestamp":
        report = report.model_copy(update={"validated_at": "2031-01-01T00:00:00Z"})
    elif mutation == "subject":
        report = report.model_copy(update={"subject_digest": "sha256:" + "1" * 64})
    elif mutation == "tokens":
        report = report.model_copy(update={"tokens": None})
    elif mutation == "task":
        task = service.request.task.model_copy(update={"task_id": "other"})
        service = replace(
            service, request=service.request.model_copy(update={"task": task})
        )
    elif mutation == "principal":
        service = replace(
            service,
            request=service.request.model_copy(
                update={"principal": Principal("stranger")}
            ),
        )
    elif mutation == "view":
        view = view.model_copy(update={"content": "forged"})
    elif mutation == "key":
        service = replace(
            service, journal=RecordJournal(service.compiler.registry, b"wrong-key" * 4)
        )
    else:
        report = report.model_copy(update={"kind": "integrity"})
    with pytest.raises(RecordError, match="^record rejected$"):
        service.verify_report(report, [pub.capsule], view=view)


@pytest.mark.parametrize("field", ["scope", "subject", "kind", "payload", "signature"])
def test_persistent_record_rejects_database_tampering(tmp_path, counter, field):
    service, pub, view = setup(tmp_path, counter)
    report = service.validate_compression(view, [pub.capsule])
    assert report.record
    with sqlite3.connect(service.compiler.registry.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE m5_records SET kind='forged'")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM m5_records")
        # Simulate a corrupt host database, bypassing the append-only API/triggers.
        connection.execute("DROP TRIGGER m5_records_no_update")
        replacement = b"forged" if field in {"payload", "signature"} else "forged"
        connection.execute(f"UPDATE m5_records SET {field}=?", (replacement,))
    with pytest.raises(RecordError):
        service.verify_report(report, [pub.capsule], view=view)


def test_current_revocation_withholds_identities_and_token_measurement(
    tmp_path, counter
):
    from contractcapsule.resolve.policies import StaticEligibilityAuthorizer

    service, pub, view = setup(tmp_path, counter)
    report = service.validate_compression(view, [pub.capsule])
    denied = StaticEligibilityAuthorizer()
    compiler = replace(
        service.compiler,
        authorizer=denied,
        evidence=replace(service.compiler.evidence, authorizer=denied),
    )
    service = replace(service, compiler=compiler)
    invalid = service.validate_compression(view, [pub.capsule])
    assert not invalid.valid
    assert (
        invalid.tokens is None
        and invalid.scope_digest is None
        and invalid.subject_digest is None
    )
    assert "com.example" not in invalid.model_dump_json()
    with pytest.raises(RecordError):
        service.verify_report(report, [pub.capsule], view=view)
    assert invalid.record is not None
    assert (
        service.journal.verifier().verify(
            invalid.record, kind="compression", scope="withheld", subject="withheld"
        )
        == invalid.payload_bytes()
    )


@pytest.mark.parametrize("change", ["dependency", "root", "closure", "provider"])
def test_independent_graph_checks_with_real_dependency_and_root(
    tmp_path, counter, change
):
    fixture = M4Fixture.create(tmp_path)

    def amend(raw):
        raw["semantic_payload"]["atoms"][0]["requires_atoms"] = ["dependency"]

    pub = fixture.publish(
        provides=("policy/v1",),
        atoms=(
            {"atom_id": "work", "statement": "token policy.\n"},
            {
                "atom_id": "dependency",
                "statement": "unmatched background.\n",
                "compression_class": "P3_SUMMARY",
            },
        ),
        amend=amend,
    )
    compiler, request = pipeline(fixture, (pub,), counter)
    if change in {"root", "provider"}:
        request = request.model_copy(
            update={
                "task": request.task.model_copy(
                    update={"text": "absent", "required_interfaces": ("policy/v1",)}
                )
            }
        )
    service = ValidationService(
        request,
        compiler,
        LocalArtifactResolver(
            {pub.capsule.control_manifest.content_digest: tmp_path / "publication-1"}
        ),
        RecordJournal(fixture.registry, b"j" * 32),
        lambda: datetime.fromisoformat(AS_OF),
    )
    view = compiler.compile_view(request)
    assert service.validate_compression(view, [pub.capsule]).valid
    if change in {"dependency", "root"}:
        removed = "dependency" if change == "dependency" else "work"
        decisions = tuple(
            d.model_copy(update={"outcome": "excluded"}) if d.atom_id == removed else d
            for d in view.manifest.decisions
        )
        view = view.model_copy(
            update={
                "manifest": view.manifest.model_copy(update={"decisions": decisions})
            }
        )
    else:
        field = "closure" if change == "closure" else "providers"
        view = view.model_copy(
            update={"manifest": view.manifest.model_copy(update={field: ()})}
        )
    with patch.object(type(compiler), "compile_view", return_value=view):
        assert not service.validate_compression(view, [pub.capsule]).valid


def test_real_source_bytes_are_rechecked(tmp_path, counter):
    service, pub, view = setup(tmp_path, counter)
    assert service.validate_evidence(pub.capsule).valid
    record = pub.capsule.evidence_plane.records[0]
    path = service.compiler.registry._cas.object_path(record.content_digest)
    path.chmod(0o600)  # Explicit local corruption, bypassing immutable CAS APIs.
    path.write_bytes(b"changed source")
    assert not service.validate_evidence(pub.capsule).valid
    with patch.object(type(service.compiler), "compile_view", return_value=view):
        assert not service.validate_compression(view, [pub.capsule]).valid


def test_exact_m5_test_bytes_rechecked_without_execution(tmp_path, counter):
    from tests.m5_helpers import M5Fixture

    fixture = M5Fixture.create(tmp_path)
    compiler, request = pipeline(fixture.base, (fixture.new,), counter)
    service = ValidationService(
        request,
        compiler,
        LocalArtifactResolver(
            {fixture.new.capsule.control_manifest.content_digest: fixture.package}
        ),
        RecordJournal(fixture.base.registry, b"j" * 32),
        lambda: datetime.fromisoformat(AS_OF),
    )
    assert service.validate_integrity(fixture.new.capsule).valid
    target = fixture.package / "tests/behavioral/executor.py"
    target.write_bytes(b"print('tampered')")
    assert not service.validate_integrity(fixture.new.capsule).valid


@pytest.mark.parametrize("mutation", ["capsule", "request", "configuration", "journal"])
def test_operational_and_nominal_forgery_fail_closed(tmp_path, counter, mutation):
    service, pub, view = setup(tmp_path, counter)
    capsule = pub.capsule
    if mutation == "capsule":
        capsule = capsule.model_copy(
            update={
                "control_manifest": capsule.control_manifest.model_copy(
                    update={"authority": "forged"}
                )
            }
        )
    elif mutation == "request":
        service = replace(
            service,
            request=service.request.model_copy(
                update={
                    "budget": service.request.budget.model_copy(
                        update={"model_input_tokens": True}
                    )
                }
            ),
        )
    elif mutation == "configuration":
        service = replace(
            service, request=service.request.model_copy(update={"model_id": "other"})
        )
    else:
        with patch.object(RecordJournal, "append", side_effect=OSError("PRIVATE")):
            report = service.validate_compression(view, [capsule])
        assert not report.valid and report.record is None
        assert "PRIVATE" not in report.model_dump_json()
        return
    assert not service.validate_compression(view, [capsule]).valid


@pytest.mark.parametrize("removed", ["hard", "work"])
def test_self_consistent_omission_by_faulty_compiler_is_rejected(
    tmp_path, counter, removed
):
    from contractcapsule.compile.session import Compilation

    service, pub, _ = setup(tmp_path, counter)
    select = Compilation._select

    def faulty_select(session, request, graph):
        select(session, request, graph)
        session.selected.remove(removed)
        session.reasons[removed] = "BUDGET_EXCLUDED"
        session.content, session.tokens = session._render(session.selected)

    with patch.object(Compilation, "_select", faulty_select):
        forged = service.compiler.compile_view(service.request)
    assert forged.validation.valid  # A self-consistent faulty compiler success.
    assert all(
        d.outcome == "excluded"
        for d in forged.manifest.decisions
        if d.atom_id == removed
    )
    with patch.object(type(service.compiler), "compile_view", return_value=forged):
        assert not service.validate_compression(forged, [pub.capsule]).valid


def test_published_core_cannot_be_replaced_by_nominal_models(tmp_path, counter):
    from contractcapsule.storage.registry import PublishedCapsule

    service, pub, _ = setup(tmp_path, counter)
    capsule = pub.capsule.model_copy(
        update={
            "detached_signature": pub.capsule.detached_signature.model_copy(
                update={"value": "forged"}
            )
        }
    )
    fake = PublishedCapsule(capsule, "PUBLISHED", pub.published_at)
    service = replace(
        service, request=service.request.model_copy(update={"capsules": (fake,)})
    )
    assert not service.validate_integrity(capsule).valid


def test_source_handle_identity_checked_when_native_resolver_is_fault_injected(
    tmp_path, counter
):
    from contractcapsule.compile.evidence import NativeEvidenceResolver

    service, pub, _ = setup(tmp_path, counter)
    resolve = NativeEvidenceResolver.resolve

    def wrong_span(resolver, *args):
        source, *rest = resolve(resolver, *args)
        return (source.model_copy(update={"excerpt": "forged"}), *rest)

    with patch.object(NativeEvidenceResolver, "resolve", wrong_span):
        assert not service.validate_evidence(pub.capsule).valid


def test_reusing_report_after_validity_expiry_is_rejected(tmp_path, counter):
    service, pub, view = setup(tmp_path, counter)
    report = service.validate_compression(view, [pub.capsule])
    expired = replace(
        service, clock=lambda: datetime.fromisoformat("2099-01-02T00:00:00Z")
    )
    with pytest.raises(RecordError):
        expired.verify_report(report, [pub.capsule], view=view)


def test_invalid_clock_has_no_invented_validation_timestamp(tmp_path, counter):
    service, pub, view = setup(tmp_path, counter)
    service = replace(service, clock=lambda: datetime(2030, 1, 1))  # noqa: DTZ001 - fault injection
    report = service.validate_compression(view, [pub.capsule])
    assert not report.valid
    assert report.validated_at is None


def test_duplicate_test_ids_do_not_certify_integrity(tmp_path, counter):
    from tests.m5_helpers import M5Fixture

    def duplicate(raw):
        tests = raw["tests_integrity"]["tests"]
        tests[-1]["test_id"] = tests[-2]["test_id"]

    fixture = M5Fixture.create(tmp_path, amend=duplicate)
    compiler, request = pipeline(fixture.base, (fixture.new,), counter)
    service = ValidationService(
        request,
        compiler,
        LocalArtifactResolver(
            {fixture.new.capsule.control_manifest.content_digest: fixture.package}
        ),
        RecordJournal(fixture.base.registry, b"j" * 32),
        lambda: datetime.fromisoformat(AS_OF),
    )
    assert not service.validate_integrity(fixture.new.capsule).valid


def test_hidden_core_conflict_survives_compiler_false_success(tmp_path, counter):
    from contractcapsule.resolve.graph import ResolvedGraph

    fixture = M4Fixture.create(tmp_path)

    def amend(raw):
        raw["semantic_payload"]["atoms"][0]["conflicts_with"] = ["other"]

    pub = fixture.publish(
        atoms=(
            {"atom_id": "hard", "compression_class": "P0_EXACT"},
            {"atom_id": "other", "compression_class": "P0_EXACT"},
        ),
        amend=amend,
    )
    compiler, request = pipeline(fixture, (pub,), counter)
    with patch.object(ResolvedGraph, "conflicts_for", return_value=()):
        view = compiler.compile_view(request)
    assert view.validation.valid
    service = ValidationService(
        request,
        compiler,
        LocalArtifactResolver(
            {pub.capsule.control_manifest.content_digest: tmp_path / "publication-1"}
        ),
        RecordJournal(fixture.registry, b"j" * 32),
        lambda: datetime.fromisoformat(AS_OF),
    )
    with patch.object(type(compiler), "compile_view", return_value=view):
        assert not service.validate_compression(view, [pub.capsule]).valid


def test_expected_manifest_lock_not_bypassed_by_lying_compiler(tmp_path, counter):
    service, pub, view = setup(tmp_path, counter)
    service = replace(
        service,
        request=service.request.model_copy(
            update={"expected_manifest_digest": "sha256:" + "0" * 64}
        ),
    )
    with patch.object(type(service.compiler), "compile_view", return_value=view):
        assert not service.validate_compression(view, [pub.capsule]).valid
