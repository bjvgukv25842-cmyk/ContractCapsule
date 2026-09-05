"""Boundary and replay contracts for M4's derived runtime objects."""

import hashlib
import json
from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError

from contractcapsule.compile.errors import CompileError
from contractcapsule.models.base import Principal
from contractcapsule.models.canonical import canonical_digest, capsule_wire_dict
from contractcapsule.models.core import Capsule
from contractcapsule.models.view import (
    CapsuleRef,
    ClosureLink,
    CompiledView,
    CompileRequest,
    Conflict,
    DecisionRecord,
    Eligibility,
    EvidenceHandle,
    EvidenceMaterial,
    ProviderWitness,
    RankedAtom,
    ServiceStamp,
    TaskContext,
    TokenAccounting,
    ValidationReport,
    ViewBudget,
    ViewManifest,
    canonical_view_manifest_bytes,
    compile_request_projection,
    view_manifest_digest,
)
from contractcapsule.storage.registry import PublishedCapsule
from tests.m2_helpers import capsule_with_digest

DIGEST = "sha256:" + "1" * 64
TIME = "2026-09-05T00:00:00Z"


def task(**changes: Any) -> TaskContext:
    values = {
        "task_id": "task",
        "tenant": "tenant",
        "repository": "repo",
        "paths": ("src/a.py",),
        "environment": "dev",
        "text": "  exact text\n",
    }
    values.update(changes)
    return TaskContext.model_validate(values)


def ref(name: str = "capsule") -> CapsuleRef:
    return CapsuleRef(capsule_id=name, version="1.0.0", digest=DIGEST)


def manifest(**changes: Any) -> ViewManifest:
    values = {
        "task_id": "task",
        "tenant": "tenant",
        "repository": "repo",
        "as_of": TIME,
        "task_digest": DIGEST,
        "permission_digest": DIGEST,
        "request_digest": DIGEST,
        "model_id": "model",
        "tokenizer_profile": "tokenizer",
        "renderer_version": "renderer",
        "tokens": TokenAccounting(
            total=3, available=10, sections={"P0": 4}, boundary_adjustment=-1
        ),
        "validation": ValidationReport(valid=True),
    }
    values.update(changes)
    return ViewManifest.model_validate(values)


def request(**changes: Any) -> CompileRequest:
    values = {
        "capsules": (PublishedCapsule(capsule_with_digest(), "PUBLISHED", TIME),),
        "task": task(),
        "principal": Principal("caller"),
        "budget": ViewBudget(model_input_tokens=10),
        "as_of": TIME,
        "model_id": "model",
        "tokenizer_profile": "tokenizer",
    }
    values.update(changes)
    return CompileRequest.model_validate(values)


def test_budget_subtracts_every_reservation_and_allows_zero() -> None:
    budget = ViewBudget(
        model_input_tokens=20,
        system_tokens=3,
        conversation_tokens=4,
        tools_tokens=5,
        safety_headroom_tokens=8,
    )
    assert budget.available == 0
    assert ViewBudget(model_input_tokens=0).available == 0


@pytest.mark.parametrize("bad", [-1, True, "10", 1.5])
def test_budget_rejects_negative_and_coerced_counts(bad: Any) -> None:
    with pytest.raises(ValidationError):
        ViewBudget(model_input_tokens=bad)


def test_budget_rejects_negative_available() -> None:
    with pytest.raises(ValidationError):
        ViewBudget(model_input_tokens=5, tools_tokens=6)


def test_task_normalizes_sets_but_preserves_text() -> None:
    value = task(
        paths=("src/z.py", "src/a.py", "src/z.py"),
        required_interfaces=("z/v1", "a/v2", "z/v1"),
        required_atom_ids=("z", "a", "z"),
    )
    assert value.paths == ("src/a.py", "src/z.py")
    assert value.required_interfaces == ("a/v2", "z/v1")
    assert value.required_atom_ids == ("a", "z")
    assert value.text == "  exact text\n"
    with pytest.raises(ValidationError):
        value.text = "changed"


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/a",
        "../a",
        "a/../b",
        "a//b",
        "a/./b",
        "C:/a",
        "a\\b",
        "a/*",
        "a/?",
        "a/[x]",
        "a\x00b",
    ],
)
def test_task_rejects_nonliteral_or_unsafe_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        task(paths=(path,))


@pytest.mark.parametrize(
    "changes",
    [
        {"paths": ()},
        {"paths": ["a"]},
        {"risk": "unknown"},
        {"unknown": "value"},
        {"tenant": ""},
    ],
)
def test_task_rejects_impossible_scope_or_unknown_fields(changes: Any) -> None:
    with pytest.raises(ValidationError):
        task(**changes)


def test_request_config_is_recursively_frozen_and_detached() -> None:
    config = {"nested": {"values": [1, 2]}}
    value = request(runtime_config=config)
    config["nested"]["values"].append(3)
    assert value.runtime_config["nested"]["values"] == (1, 2)
    with pytest.raises(TypeError):
        value.runtime_config["nested"]["other"] = 2
    with pytest.raises(TypeError):
        request().runtime_config["new"] = 1  # type: ignore[index]
    projection = compile_request_projection(value)
    assert projection["runtime_config"] == {"nested": {"values": [1, 2]}}
    assert projection["principal"] == {"principal_id": "caller"}
    json.dumps(projection, allow_nan=False)


@pytest.mark.parametrize(
    "config",
    [{"x": float("nan")}, {"x": float("inf")}, {1: "not-string"}, {"x": object()}],
)
def test_request_rejects_non_json_runtime_config(config: Any) -> None:
    with pytest.raises(ValidationError):
        request(runtime_config=config)


@pytest.mark.parametrize(
    "changes",
    [
        {"principal": {"principal_id": "caller"}},
        {"capsules": ({"capsule": {}},)},
        {"as_of": "2026-02-30T00:00:00Z"},
        {"as_of": "2026-09-05"},
    ],
)
def test_request_requires_nominal_objects_and_real_timestamp(changes: Any) -> None:
    with pytest.raises(ValidationError):
        request(**changes)


def test_request_does_not_confuse_nominal_publication_with_authority() -> None:
    published = PublishedCapsule(capsule_with_digest(), "PUBLISHED", TIME)
    value = request(capsules=(published,))
    assert value.capsules[0] is published
    assert value.principal == Principal("caller")


def test_request_projection_omits_rebuildable_data_and_publication_time() -> None:
    first = request()
    published = first.capsules[0]
    raw = capsule_wire_dict(published.capsule)
    raw["derived_artifacts"] = {"cache": "changed"}
    raw["runtime_sidecar"] = {"observations": ["changed"]}
    changed = Capsule.model_validate_json(json.dumps(raw))
    second = request(
        capsules=(PublishedCapsule(changed, "PUBLISHED", "2026-09-06T00:00:00Z"),)
    )
    assert compile_request_projection(first) == compile_request_projection(second)
    raw["detached_signature"]["value"] = "base64:AQ=="
    signed = Capsule.model_validate_json(json.dumps(raw))
    third = request(capsules=(PublishedCapsule(signed, "PUBLISHED", TIME),))
    assert compile_request_projection(first) != compile_request_projection(third)
    raw["semantic_payload"]["atoms"][0]["statement"] = "Changed exact rule."
    revised = capsule_with_digest(raw)
    fourth = request(capsules=(PublishedCapsule(revised, "PUBLISHED", TIME),))
    assert compile_request_projection(first) != compile_request_projection(fourth)


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed": False, "atom_ids": ("a",)},
        {"allowed": True, "blockers": ("denied",)},
    ],
)
def test_eligibility_rejects_contradictory_admission(changes: Any) -> None:
    with pytest.raises(ValidationError):
        Eligibility(**changes)


@pytest.mark.parametrize("valid,blockers", [(True, ("failed",)), (False, ())])
def test_validation_report_is_valid_exactly_when_blockers_are_absent(
    valid: bool, blockers: tuple[str, ...]
) -> None:
    with pytest.raises(ValidationError):
        ValidationReport(valid=valid, blockers=blockers)


def test_ranked_atom_preserves_core_order_statement_and_digest() -> None:
    capsule = capsule_with_digest()
    before = canonical_digest(capsule)
    atom = capsule.semantic_payload.atoms[0]
    ranked = RankedAtom(atom=atom, score=0.0, matched=False)
    request(capsules=(PublishedCapsule(capsule, "PUBLISHED", TIME),))
    assert ranked.atom is atom
    assert ranked.atom.statement == "Production access tokens expire within 15 minutes."
    assert ranked.atom.scope == ("environment:prod", "path:src/auth/**")
    assert canonical_digest(capsule) == before
    with pytest.raises(ValidationError):
        RankedAtom(atom=atom, score=float("nan"), matched=True)


@pytest.mark.parametrize("score", [True, 1, "0.5"])
def test_ranked_atom_rejects_score_type_coercion(score: Any) -> None:
    with pytest.raises(ValidationError):
        RankedAtom(
            atom=capsule_with_digest().semantic_payload.atoms[0],
            score=score,
            matched=True,
        )


def test_evidence_identity_is_canonical_and_contains_no_location() -> None:
    fields = {
        "capsule": ref(),
        "evidence_id": "evidence",
        "atom_ids": ("z", "a"),
        "mode": "CAS",
        "content_digest": DIGEST,
        "span_digest": None,
        "resolver_version": "1",
    }
    handle = EvidenceHandle.model_validate(fields)
    other = EvidenceHandle.model_validate(fields | {"atom_ids": ("a", "z")})
    assert handle.handle_id == other.handle_id
    assert handle.handle_id.startswith("sha256:")
    assert len(handle.handle_id) == 71
    assert ref().key == "capsule@1.0.0#" + DIGEST
    material = EvidenceMaterial(
        handle=handle, excerpt="exact\n", full_text="full exact\n"
    )
    assert material.excerpt == "exact\n"
    with pytest.raises(ValidationError):
        EvidenceHandle.model_validate(fields | {"path": "private/secret"})


def test_manifest_canonical_bytes_ignore_set_permutations_and_preserve_reasons() -> (
    None
):
    a, b = ref("a"), ref("b")
    decisions = (
        DecisionRecord(capsule=b, atom_id="z", outcome="excluded", reason="  exact\n"),
        DecisionRecord(capsule=a, atom_id="a", outcome="selected", reason="required"),
    )
    providers = (
        ProviderWitness(consumer=None, requirement="z/v1", provider=b, atom_ids=("z",)),
        ProviderWitness(
            consumer=a, requirement="a/v1", provider=b, atom_ids=("a", "z")
        ),
    )
    services = (
        ServiceStamp(name="z", version="1", config_digest=DIGEST),
        ServiceStamp(name="a", version="1", config_digest=DIGEST),
    )
    first = manifest(
        capsules=(b, a),
        decisions=decisions,
        providers=providers,
        services=services,
        expanded_evidence=("z", "a"),
        closure=(
            ClosureLink(source="z", target="a"),
            ClosureLink(source="a", target="b"),
        ),
        conflicts=(Conflict(source="z", target="a", reason="conflict"),),
    )
    second = manifest(
        capsules=(a, b),
        decisions=decisions[::-1],
        providers=providers[::-1],
        services=services[::-1],
        expanded_evidence=("a", "z"),
        closure=first.closure[::-1],
        conflicts=(Conflict(source="a", target="z", reason="conflict"),),
    )
    actual = canonical_view_manifest_bytes(first)
    assert actual == canonical_view_manifest_bytes(second)
    assert view_manifest_digest(first) == "sha256:" + hashlib.sha256(actual).hexdigest()
    decoded = json.loads(actual)
    assert [item["capsule_id"] for item in decoded["capsules"]] == ["a", "b"]
    assert decoded["decisions"][1]["reason"] == "  exact\n"
    assert decoded["conflicts"] == [
        {"source": "a", "target": "z", "reason": "conflict"}
    ]
    assert decoded["profile"] == "CCS-2.1-m4-collective-interfaces-v1"


def test_manifest_rejects_duplicate_capsule_and_decision_identities() -> None:
    with pytest.raises(ValidationError):
        manifest(capsules=(ref(), ref()))
    changed = CapsuleRef(capsule_id="capsule", version="2.0.0", digest=DIGEST)
    with pytest.raises(ValidationError):
        manifest(capsules=(ref(), changed))
    decision = DecisionRecord(
        capsule=ref(), atom_id="a", outcome="selected", reason="first"
    )
    with pytest.raises(ValidationError):
        manifest(decisions=(decision, decision))


@pytest.mark.parametrize(
    "fields",
    [
        {"total": 2, "available": 3, "sections": {"x": 1}, "boundary_adjustment": 0},
        {"total": 1, "available": 3, "sections": {"x": -1}, "boundary_adjustment": 2},
        {"total": True, "available": 3, "sections": {}, "boundary_adjustment": 1},
    ],
)
def test_token_accounting_rejects_impossible_counts(fields: Any) -> None:
    with pytest.raises(ValidationError):
        TokenAccounting(**fields)


def test_manifest_count_maps_are_frozen() -> None:
    value = manifest(rejected_counts={"denied": 1})
    with pytest.raises(TypeError):
        value.rejected_counts["denied"] = 2  # type: ignore[index]
    with pytest.raises(TypeError):
        value.tokens.sections["P0"] = 0  # type: ignore[index]
    with pytest.raises(ValidationError):
        manifest(rejected_counts={"denied": True})


def test_invalid_view_must_have_empty_content_and_matching_report() -> None:
    invalid = ValidationReport(valid=False, blockers=("budget_overflow",))
    failed = manifest(
        validation=invalid,
        tokens=TokenAccounting(
            total=12, available=10, sections={"P0": 12}, boundary_adjustment=0
        ),
    )
    value = CompiledView(content="", manifest=failed, validation=invalid)
    assert value.content == ""
    with pytest.raises(ValidationError):
        CompiledView(content="partial", manifest=failed, validation=invalid)
    with pytest.raises(ValidationError):
        CompiledView(
            content="", manifest=failed, validation=ValidationReport(valid=True)
        )
    with pytest.raises(ValidationError):
        CompiledView(
            content="",
            manifest=failed,
            validation=ValidationReport(valid=False, blockers=("different",)),
        )


def test_valid_view_rejects_overbudget_accounting() -> None:
    over = manifest(
        tokens=TokenAccounting(
            total=11, available=10, sections={"P0": 11}, boundary_adjustment=0
        )
    )
    with pytest.raises(ValidationError):
        CompiledView(
            content="exact", manifest=over, validation=ValidationReport(valid=True)
        )
    assert (
        CompiledView(
            content="exact",
            manifest=manifest(),
            validation=ValidationReport(valid=True),
        ).content
        == "exact"
    )


def test_compile_error_contains_only_a_safe_code() -> None:
    error = CompileError("budget_overflow")
    assert str(error) == "budget_overflow"
    assert error.code == "budget_overflow"
    assert error.args == ("budget_overflow",)
    for value in ("", "private/path", "bad\nmessage", "has spaces", 12):
        with pytest.raises(ValueError):
            CompileError(value)  # type: ignore[arg-type]


def test_request_rejects_nominal_subclasses() -> None:
    class PretendPrincipal(Principal):
        pass

    class PretendPublication(PublishedCapsule):
        pass

    with pytest.raises(ValidationError):
        request(principal=PretendPrincipal("caller"))
    with pytest.raises(ValidationError):
        request(
            capsules=(PretendPublication(capsule_with_digest(), "PUBLISHED", TIME),)
        )
    published = request().capsules[0]
    assert replace(published, registry_status="REVOKED").registry_status == "REVOKED"
