from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from contractcapsule.models import Capsule
from contractcapsule.models.canonical import (
    CANONICAL_PROFILE,
    canonical_digest,
    canonical_json_bytes,
    capsule_wire_dict,
    identity_projection,
    signature_input,
)
from contractcapsule.models.schema import (
    CapsuleSchemaValidationError,
    schema_documents,
    validate_capsule_document,
)
from tests.m2_helpers import ZERO_DIGEST, capsule_with_digest, sample_capsule_data

ROOT_MODULES = (
    "control_manifest",
    "semantic_payload",
    "evidence_plane",
    "dependency_graph",
    "replacement_contract",
    "compression_policy",
    "tests_integrity",
)


def validate_model(data: dict[str, object]) -> Capsule:
    return Capsule.model_validate_json(json.dumps(data, ensure_ascii=False))


def test_all_seven_core_modules_are_required_and_valid() -> None:
    capsule = capsule_with_digest()
    assert tuple(identity_projection(capsule)["core"]) == ROOT_MODULES
    assert identity_projection(capsule)["profile"] == CANONICAL_PROFILE

    for module in ROOT_MODULES:
        invalid = sample_capsule_data()
        del invalid[module]
        with pytest.raises(ValidationError):
            validate_model(invalid)


@pytest.mark.parametrize(
    ("module", "field"),
    [
        ("control_manifest", "authority"),
        ("semantic_payload", "atoms"),
        ("evidence_plane", "records"),
        ("dependency_graph", "edges"),
        ("replacement_contract", "protected_invariants"),
        ("compression_policy", "classes"),
        ("tests_integrity", "lock"),
    ],
)
def test_security_critical_fields_have_no_defaults(module: str, field: str) -> None:
    invalid = sample_capsule_data()
    del invalid[module][field]
    with pytest.raises(ValidationError):
        validate_model(invalid)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("control_manifest", "lifecycle"), "MAYBE"),
        (("control_manifest", "version"), "v2"),
        (("control_manifest", "content_digest"), "abc"),
        (("semantic_payload", "atoms", 0, "compression_class"), "P5"),
        (("evidence_plane", "records", 0, "mode"), "LOCAL"),
    ],
)
def test_invalid_enums_version_and_digest_fail_closed(
    path: tuple[object, ...], value: object
) -> None:
    invalid = sample_capsule_data()
    cursor: object = invalid
    for part in path[:-1]:
        cursor = cursor[part]  # type: ignore[index]
    cursor[path[-1]] = value  # type: ignore[index]
    with pytest.raises(ValidationError):
        validate_model(invalid)


def test_unknown_fields_are_rejected_but_namespaced_extensions_are_allowed() -> None:
    invalid = sample_capsule_data()
    invalid["control_manifest"]["mystery"] = "no"
    with pytest.raises(ValidationError):
        validate_model(invalid)

    invalid = sample_capsule_data()
    invalid["control_manifest"]["extensions"] = {"unsafe": True}
    with pytest.raises(ValidationError):
        validate_model(invalid)

    valid = sample_capsule_data()
    valid["control_manifest"]["extensions"] = {"x-example-policy": {"level": 2}}
    validate_model(valid)

    omitted = sample_capsule_data()
    del omitted["control_manifest"]["extensions"]
    del omitted["semantic_payload"]["extensions"]
    validate_model(omitted)


def test_models_are_deeply_immutable() -> None:
    capsule = capsule_with_digest()
    with pytest.raises(ValidationError):
        capsule.control_manifest.authority = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        capsule.control_manifest.extensions["x-new"] = True  # type: ignore[index]
    with pytest.raises(AttributeError):
        capsule.semantic_payload.atoms.append("bad")  # type: ignore[attr-defined]


def test_static_capsule_schema_and_python_model_accept_the_same_valid_object() -> None:
    data = sample_capsule_data()
    schema_path = Path(__file__).parents[2] / "schemas/capsule.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(data)
    validate_model(data)


def test_all_static_schema_documents_exactly_match_the_python_models() -> None:
    schema_root = Path(__file__).parents[2] / "schemas"
    documents = schema_documents()
    assert {path.name for path in schema_root.glob("*.schema.json")} == set(documents)
    for filename, expected in documents.items():
        actual = json.loads((schema_root / filename).read_text(encoding="utf-8"))
        assert actual == expected


@pytest.mark.parametrize("module", ROOT_MODULES)
def test_static_schema_and_python_model_both_reject_missing_module(module: str) -> None:
    data = sample_capsule_data()
    del data[module]
    schema_path = Path(__file__).parents[2] / "schemas/capsule.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(data)
    with pytest.raises(ValidationError):
        validate_model(data)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["control_manifest"]["scope"].update(repositories=[]),
        lambda data: data["semantic_payload"]["atoms"][0].update(confidence=2.0),
        lambda data: data["compression_policy"]["classes"].pop(),
        lambda data: data["compression_policy"]["classes"][0].update(
            rendering="not-exact"
        ),
        lambda data: data["tests_integrity"].update(tests=[]),
    ],
)
def test_schema_and_python_share_representative_semantic_constraints(mutation) -> None:
    data = sample_capsule_data()
    mutation(data)
    schema_path = Path(__file__).parents[2] / "schemas/capsule.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(data)
    with pytest.raises(ValidationError):
        validate_model(data)


def test_authoritative_schema_validation_includes_cross_record_invariants() -> None:
    duplicate = sample_capsule_data()
    second = copy.deepcopy(duplicate["semantic_payload"]["atoms"][0])
    second["statement"] = "same ID but different content"
    duplicate["semantic_payload"]["atoms"].append(second)
    with pytest.raises(CapsuleSchemaValidationError):
        validate_capsule_document(duplicate)

    contradictory = sample_capsule_data()
    candidate = copy.deepcopy(contradictory["semantic_payload"]["atoms"][0])
    candidate["atom_id"] = "auth.candidate"
    candidate["status"] = "candidate"
    candidate["evidence_refs"] = []
    contradictory["semantic_payload"]["atoms"].append(candidate)
    contradictory["evidence_plane"]["records"][0]["atom_ids"] = [
        "auth.candidate"
    ]
    with pytest.raises(CapsuleSchemaValidationError):
        validate_capsule_document(contradictory)


def test_digest_is_deterministic_formatted_and_independent_of_declared_digest() -> None:
    data = sample_capsule_data()
    first = validate_model(data)
    data["control_manifest"]["content_digest"] = "sha256:" + ("f" * 64)
    second = validate_model(data)
    digest = canonical_digest(first)
    assert digest == canonical_digest(first)
    assert digest == canonical_digest(second)
    assert digest.startswith("sha256:") and len(digest) == 71


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("control_manifest", "authority"), "other-authority"),
        (("control_manifest", "scope", "paths", 0), "src/security/**"),
        (("control_manifest", "lifecycle"), "VALIDATED"),
        (("control_manifest", "extensions", "x-policy-tier"), "high"),
        (("semantic_payload", "atoms", 0, "statement"), "Changed statement"),
        (("evidence_plane", "records", 0, "content_digest"), "sha256:" + ("9" * 64)),
        (("evidence_plane", "records", 0, "access_policy"), "security-only"),
        (("dependency_graph", "edges", 0, "mandatory"), False),
        (("replacement_contract", "target_effects", 0), "different effect"),
        (("compression_policy", "classes", 1, "rendering"), "structured_verbatim"),
        (("tests_integrity", "lock", "compiler_version"), "0.2.0"),
        (("tests_integrity", "signature_policy", "key_id"), "rotated-key"),
    ],
)
def test_every_representative_core_change_changes_identity(
    path: tuple[object, ...], replacement: object
) -> None:
    original_data = sample_capsule_data()
    changed_data = copy.deepcopy(original_data)
    cursor: object = changed_data
    for part in path[:-1]:
        cursor = cursor[part]  # type: ignore[index]
    cursor[path[-1]] = replacement  # type: ignore[index]
    if path == ("tests_integrity", "signature_policy", "key_id"):
        changed_data["detached_signature"]["key_id"] = replacement
    assert canonical_digest(validate_model(original_data)) != canonical_digest(
        validate_model(changed_data)
    )


def test_derived_sidecars_and_detached_signature_do_not_change_identity() -> None:
    original = sample_capsule_data()
    changed = copy.deepcopy(original)
    changed["detached_signature"]["value"] = "base64:AQ=="
    changed["detached_signature"]["envelope"] = {"x-transport": "changed"}
    changed["derived_artifacts"] = {"embeddings": [99], "cache": "changed"}
    changed["runtime_sidecar"] = {"logs": ["changed"], "timestamp": "later"}
    assert canonical_digest(validate_model(original)) == canonical_digest(
        validate_model(changed)
    )


def test_array_order_is_identity_relevant() -> None:
    original = sample_capsule_data()
    changed = copy.deepcopy(original)
    changed["control_manifest"]["scope"]["environments"].reverse()
    assert canonical_digest(validate_model(original)) != canonical_digest(
        validate_model(changed)
    )


def test_unicode_is_not_normalized() -> None:
    nfc = sample_capsule_data()
    nfd = copy.deepcopy(nfc)
    nfc["semantic_payload"]["atoms"][0]["statement"] = "caf\u00e9"
    nfd["semantic_payload"]["atoms"][0]["statement"] = "cafe\u0301"
    assert canonical_digest(validate_model(nfc)) != canonical_digest(validate_model(nfd))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (333333333.33333329, b"333333333.3333333"),
        (1e30, b"1e+30"),
        (4.50, b"4.5"),
        (2e-3, b"0.002"),
        (1e-27, b"1e-27"),
        (-0.0, b"0"),
    ],
)
def test_jcs_numeric_vectors(value: float, expected: bytes) -> None:
    assert canonical_json_bytes(value) == expected


def test_jcs_uses_utf16_key_order() -> None:
    value = {"\ufb33": 1, "\U0001f600": 2}
    encoded = canonical_json_bytes(value)
    assert encoded.index("\U0001f600".encode()) < encoded.index("\ufb33".encode())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes(value)


def test_non_string_jcs_object_key_is_rejected_without_coercion() -> None:
    with pytest.raises(TypeError, match="keys must be strings"):
        canonical_json_bytes({1: "not-canonical"})


def test_content_digest_can_be_replaced_without_recursive_instability() -> None:
    capsule = capsule_with_digest()
    first = canonical_digest(capsule)
    wire = capsule_wire_dict(capsule)
    wire["control_manifest"]["content_digest"] = ZERO_DIGEST
    assert canonical_digest(validate_model(wire)) == first


def test_future_signature_input_is_domain_separated_and_digest_only() -> None:
    digest = "sha256:" + ("a" * 64)
    assert signature_input(digest) == b"CCS-2.1-signature-v1\0" + digest.encode("ascii")


def test_detached_signature_metadata_must_match_identity_bound_policy() -> None:
    invalid = sample_capsule_data()
    invalid["detached_signature"]["key_id"] = "other-key"
    with pytest.raises(ValidationError, match="signature policy"):
        validate_model(invalid)


def test_published_signature_declaration_and_envelope_must_agree() -> None:
    declared_without_envelope = sample_capsule_data()
    declared_without_envelope["detached_signature"] = None
    with pytest.raises(ValidationError, match="signature"):
        validate_model(declared_without_envelope)

    unsigned_published = sample_capsule_data()
    unsigned_published["control_manifest"]["integrity"]["signature"] = None
    unsigned_published["detached_signature"] = None
    with pytest.raises(ValidationError, match="PUBLISHED.*signature"):
        validate_model(unsigned_published)


def test_evidence_bindings_must_be_reciprocal() -> None:
    invalid = sample_capsule_data()
    second = copy.deepcopy(invalid["semantic_payload"]["atoms"][0])
    second["atom_id"] = "auth.candidate"
    second["status"] = "candidate"
    second["evidence_refs"] = []
    invalid["semantic_payload"]["atoms"].append(second)
    invalid["evidence_plane"]["records"][0]["atom_ids"] = ["auth.candidate"]

    with pytest.raises(ValidationError, match="reciprocal"):
        validate_model(invalid)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("control_manifest", "scope", "paths", 0), "../outside/**"),
        (("control_manifest", "scope", "paths", 0), "/etc/**"),
        (("replacement_contract", "allowed_scope", 0), "C:/Windows/**"),
        (("replacement_contract", "forbidden_spillover", 0), "../billing/**"),
        (("evidence_plane", "records", 0, "path"), "./docs/security/auth.md"),
        (("evidence_plane", "records", 0, "path"), "docs//security/auth.md"),
        (("evidence_plane", "records", 0, "path"), "docs/./security/auth.md"),
    ],
)
def test_security_paths_are_literal_repository_relative(
    path: tuple[object, ...], value: str
) -> None:
    invalid = sample_capsule_data(evidence_modes=("GIT_IMMUTABLE",))
    cursor: object = invalid
    for part in path[:-1]:
        cursor = cursor[part]  # type: ignore[index]
    cursor[path[-1]] = value  # type: ignore[index]
    with pytest.raises(ValidationError):
        validate_model(invalid)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("control_manifest", "version"), "1.0.0-01"),
        (("semantic_payload", "atoms", 0, "validity", "from"), "2026-99-99"),
        (
            ("evidence_plane", "records", 0, "captured_at"),
            "2026-99-99T99:99:99Z",
        ),
    ],
)
def test_versions_dates_and_timestamps_are_semantically_valid(
    path: tuple[object, ...], value: str
) -> None:
    invalid = sample_capsule_data()
    cursor: object = invalid
    for part in path[:-1]:
        cursor = cursor[part]  # type: ignore[index]
    cursor[path[-1]] = value  # type: ignore[index]
    with pytest.raises(ValidationError):
        validate_model(invalid)
