from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import BaseModel, ValidationError

from contractcapsule.models import (
    Capsule,
    EvidencePlane,
    ReplacementContract,
    SemanticPayload,
)
from tests.m2_helpers import sample_capsule_data

SCHEMA_ROOT = Path(__file__).parents[2] / "schemas"
PORTABLE_DOI_URI_PATTERN = (
    r"^doi:10\.[0-9]{4,9}/"
    r"[^\u0009-\u000D\u001C-\u0020\u0085\u00A0\u1680"
    r"\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]+"
    r"$(?![\u000A\u000D\u2028\u2029])"
)
PORTABLE_URN_URI_PATTERN = (
    r"^urn:[a-z0-9][a-z0-9-]{0,31}:"
    r"[^\u0009-\u000D\u001C-\u0020\u0085\u00A0\u1680"
    r"\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]+"
    r"$(?![\u000A\u000D\u2028\u2029])"
)


def _schema_accepts(filename: str, value: Any) -> bool:
    schema = json.loads((SCHEMA_ROOT / filename).read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return not any(validator.iter_errors(value))


def _python_accepts(model: type[BaseModel], value: Any) -> bool:
    try:
        model.model_validate_json(
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        )
    except ValidationError:
        return False
    return True


def _external_uri_patterns(filename: str) -> tuple[str, ...]:
    schema = json.loads((SCHEMA_ROOT / filename).read_text(encoding="utf-8"))
    uri_schema = schema["$defs"]["ExternalImmutableEvidence"]["properties"]["uri"]
    return tuple(branch["pattern"] for branch in uri_schema["anyOf"])


def _assert_module_and_root_parity(
    data: dict[str, Any],
    *,
    module_name: str,
    module_schema: str,
    module_model: type[BaseModel],
    expected: bool,
) -> None:
    module_value = data[module_name]
    module_schema_ok = _schema_accepts(module_schema, module_value)
    module_python_ok = _python_accepts(module_model, module_value)
    root_schema_ok = _schema_accepts("capsule.schema.json", data)
    root_python_ok = _python_accepts(Capsule, data)

    assert module_schema_ok == module_python_ok == expected
    assert root_schema_ok == root_python_ok == expected


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        pytest.param([], False, id="audit-empty-scope"),
        pytest.param(["path:src/auth/**"], True, id="legal-single-scope"),
    ],
)
def test_atom_scope_has_module_and_root_schema_python_parity(
    scope: list[str], expected: bool
) -> None:
    data = sample_capsule_data()
    data["semantic_payload"]["atoms"][0]["scope"] = scope

    _assert_module_and_root_parity(
        data,
        module_name="semantic_payload",
        module_schema="semantic-payload.schema.json",
        module_model=SemanticPayload,
        expected=expected,
    )


@pytest.mark.parametrize(
    ("field", "values", "expected"),
    [
        pytest.param("target_effects", [], False, id="audit-empty-target-effects"),
        pytest.param(
            "target_effects",
            ["access token TTL changes from 30m to 15m"],
            True,
            id="legal-single-target-effect",
        ),
        pytest.param(
            "protected_invariants",
            [],
            False,
            id="empty-protected-invariants",
        ),
        pytest.param(
            "protected_invariants",
            ["refresh flow remains compatible"],
            True,
            id="legal-single-protected-invariant",
        ),
    ],
)
def test_replacement_contract_lists_have_module_and_root_schema_python_parity(
    field: str, values: list[str], expected: bool
) -> None:
    data = sample_capsule_data()
    data["replacement_contract"][field] = values

    _assert_module_and_root_parity(
        data,
        module_name="replacement_contract",
        module_schema="replacement-contract.schema.json",
        module_model=ReplacementContract,
        expected=expected,
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("../secret", False, id="audit-leading-parent-segment"),
        pytest.param("/etc/passwd", False, id="absolute"),
        pytest.param("docs/../secret", False, id="interior-parent-segment"),
        pytest.param("docs\\secret", False, id="backslash-platform-separator"),
        pytest.param("C:/secret", False, id="drive-prefix"),
        pytest.param("", False, id="empty"),
        pytest.param("docs//secret", False, id="double-separator"),
        pytest.param("docs/secret/", False, id="trailing-empty-segment"),
        pytest.param("docs/./secret", False, id="dot-segment"),
        pytest.param("docs/\x00/secret", False, id="nul"),
        pytest.param("docs/security/auth.md", True, id="legal-relative"),
        pytest.param("src/auth/**", True, id="legal-wildcard"),
        pytest.param("docs/C:notes", True, id="legal-nonleading-drive-text"),
        pytest.param("docs/.\n", True, id="legal-dot-plus-newline-text"),
        pytest.param("docs/..\n", True, id="legal-double-dot-plus-newline-text"),
    ],
)
def test_git_path_has_module_and_root_schema_python_parity(
    path: str, expected: bool
) -> None:
    data = sample_capsule_data(evidence_modes=("GIT_IMMUTABLE",))
    data["evidence_plane"]["records"][0]["path"] = path

    _assert_module_and_root_parity(
        data,
        module_name="evidence_plane",
        module_schema="evidence-plane.schema.json",
        module_model=EvidencePlane,
        expected=expected,
    )


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        pytest.param(
            "http://example.com/evidence",
            False,
            id="audit-http-scheme",
        ),
        pytest.param(
            "https://example.com/evidence",
            True,
            id="legal-canonical-https",
        ),
        pytest.param(
            "HTTPS://example.com/evidence",
            True,
            id="legal-uppercase-https-scheme",
        ),
        pytest.param(
            "\x00 HTTPS://example.com/evidence",
            True,
            id="legal-leading-c0-space-normalization",
        ),
        pytest.param(
            "\tht\nt\rpS:\r/\t/example.com/evidence",
            True,
            id="legal-scheme-control-removal",
        ),
        pytest.param(
            "doi:10.1234/example.evidence",
            True,
            id="legal-doi",
        ),
        pytest.param(
            "doi:10.1234/example\ufeffevidence",
            True,
            id="legal-doi-byte-order-mark-non-whitespace",
        ),
        pytest.param(
            "doi:10.1234/example\u0085evidence",
            False,
            id="doi-next-line-is-python-whitespace",
        ),
        pytest.param(
            "doi:10.1234/example\u2003evidence",
            False,
            id="doi-em-space-is-python-whitespace",
        ),
        pytest.param(
            "doi:10.1234/example\n",
            False,
            id="doi-trailing-newline-is-not-absolute-end",
        ),
        pytest.param(
            "urn:isbn:9780141036144",
            True,
            id="legal-urn",
        ),
        pytest.param(
            "urn:isbn:9780\ufeff141036144",
            True,
            id="legal-urn-byte-order-mark-non-whitespace",
        ),
        pytest.param(
            "urn:isbn:9780\u0085141036144",
            False,
            id="urn-next-line-is-python-whitespace",
        ),
        pytest.param(
            "urn:isbn:9780\u1680141036144",
            False,
            id="urn-ogham-space-is-python-whitespace",
        ),
        pytest.param(
            "urn:isbn:9780141036144\n",
            False,
            id="urn-trailing-newline-is-not-absolute-end",
        ),
    ],
)
def test_external_uri_lexical_rules_have_module_and_root_schema_python_parity(
    uri: str, expected: bool
) -> None:
    data = sample_capsule_data(evidence_modes=("EXTERNAL_IMMUTABLE",))
    data["evidence_plane"]["records"][0]["uri"] = uri

    _assert_module_and_root_parity(
        data,
        module_name="evidence_plane",
        module_schema="evidence-plane.schema.json",
        module_model=EvidencePlane,
        expected=expected,
    )


@pytest.mark.parametrize(
    "filename", ["evidence-plane.schema.json", "capsule.schema.json"]
)
def test_external_uri_schema_patterns_avoid_engine_dependent_whitespace_shorthand(
    filename: str,
) -> None:
    doi_pattern, urn_pattern = _external_uri_patterns(filename)[1:]

    for pattern in (doi_pattern, urn_pattern):
        assert r"\s" not in pattern
        assert r"\S" not in pattern


@pytest.mark.parametrize(
    "filename", ["evidence-plane.schema.json", "capsule.schema.json"]
)
def test_external_uri_schema_uses_exact_portable_doi_and_urn_patterns(
    filename: str,
) -> None:
    assert _external_uri_patterns(filename)[1:] == (
        PORTABLE_DOI_URI_PATTERN,
        PORTABLE_URN_URI_PATTERN,
    )


@pytest.mark.parametrize(
    "uri",
    [
        "https://EXAMPLE.com/evidence",
        "https://example.com/evidence?mutable=yes",
        "https://example.com/evidence/",
    ],
)
def test_external_uri_parser_only_semantics_remain_python_enforced(uri: str) -> None:
    data = sample_capsule_data(evidence_modes=("EXTERNAL_IMMUTABLE",))
    data["evidence_plane"]["records"][0]["uri"] = uri

    module_schema_ok = _schema_accepts(
        "evidence-plane.schema.json", data["evidence_plane"]
    )
    module_python_ok = _python_accepts(EvidencePlane, data["evidence_plane"])
    root_schema_ok = _schema_accepts("capsule.schema.json", data)
    root_python_ok = _python_accepts(Capsule, data)

    assert module_schema_ok is True
    assert root_schema_ok is True
    assert module_python_ok is False
    assert root_python_ok is False
