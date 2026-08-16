from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from contractcapsule.models import Principal
from contractcapsule.models.canonical import canonical_digest
from contractcapsule.storage.cas import FilesystemCAS
from contractcapsule.storage.registry import PolicyDecision, Registry, VersionConflict
from tests.m2_helpers import (
    TrustedM3TestHarness,
    capsule_with_digest,
    sample_capsule_data,
)


@given(st.text(min_size=1).filter(lambda value: "\ud800" not in value))
@settings(max_examples=30)
def test_digest_is_deterministic_for_generated_statements(statement: str) -> None:
    data = sample_capsule_data()
    data["semantic_payload"]["atoms"][0]["statement"] = statement
    capsule = capsule_with_digest(data)
    assert canonical_digest(capsule) == canonical_digest(capsule)


@given(st.text(min_size=1), st.text(min_size=1))
@settings(max_examples=30)
def test_core_statement_change_is_digest_sensitive(first: str, second: str) -> None:
    assume_distinct = first != second and not any(
        "\ud800" <= char <= "\udfff" for char in first + second
    )
    if not assume_distinct:
        return
    first_data = sample_capsule_data()
    second_data = copy.deepcopy(first_data)
    first_data["semantic_payload"]["atoms"][0]["statement"] = first
    second_data["semantic_payload"]["atoms"][0]["statement"] = second
    assert canonical_digest(capsule_with_digest(first_data)) != canonical_digest(
        capsule_with_digest(second_data)
    )


@given(st.text(), st.text())
@settings(max_examples=30)
def test_derived_artifact_changes_do_not_affect_identity(first: str, second: str) -> None:
    if any("\ud800" <= char <= "\udfff" for char in first + second):
        return
    first_data = sample_capsule_data()
    second_data = copy.deepcopy(first_data)
    first_data["derived_artifacts"] = {
        "cache": first,
        "embedding": [0.1],
        "compiled_view": {"value": first},
    }
    second_data["derived_artifacts"] = {
        "cache": second,
        "embedding": [0.9],
        "compiled_view": {"value": second},
    }
    first_data["runtime_sidecar"] = {"observation": first}
    second_data["runtime_sidecar"] = {"observation": second}
    assert canonical_digest(capsule_with_digest(first_data)) == canonical_digest(
        capsule_with_digest(second_data)
    )


class PropertyResolver:
    def resolve(self, principal: Principal, action: str, authority: str, scope: object):
        del authority, scope
        return PolicyDecision(
            allowed=principal.principal_id == "publisher" and action == "publish",
            allowed_access_policies=frozenset({"team-auth"}),
        )


@given(st.text(min_size=1, alphabet=st.characters(min_codepoint=97, max_codepoint=122)))
@settings(max_examples=20)
def test_model_remains_immutable_for_generated_replacements(authority: str) -> None:
    capsule = capsule_with_digest()
    with pytest.raises(ValidationError):
        capsule.control_manifest.authority = authority  # type: ignore[misc]
    with pytest.raises(TypeError):
        capsule.control_manifest.extensions["x-generated"] = authority  # type: ignore[index]


@given(st.integers(min_value=1, max_value=5))
@settings(max_examples=10)
def test_exact_republication_never_mutates_the_record(repeats: int) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        cas = FilesystemCAS(root / "cas")
        harness = TrustedM3TestHarness.create(root, cas)
        registry = Registry(
            root / "registry.sqlite3",
            cas,
            PropertyResolver(),
            trust_root=harness.authority.trust_root(),
        )
        draft = harness.build_draft()
        first = harness.publish(draft, registry)
        counts = registry._table_counts()
        for _ in range(repeats):
            assert harness.publish(draft, registry) == first
        assert registry._table_counts() == counts


@given(st.text(min_size=1, alphabet=st.characters(min_codepoint=97, max_codepoint=122)))
@settings(max_examples=15)
def test_same_version_conflict_always_fails_closed(statement: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        cas = FilesystemCAS(root / "cas")
        harness = TrustedM3TestHarness.create(root, cas)
        registry = Registry(
            root / "registry.sqlite3",
            cas,
            PropertyResolver(),
            trust_root=harness.authority.trust_root(),
        )
        original_draft = harness.build_draft()
        if statement == original_draft.capsule.semantic_payload.atoms[0].statement:
            return
        harness.publish(original_draft, registry)
        changed_draft = harness.build_draft(source_bytes=(statement + "\n").encode())
        with pytest.raises(VersionConflict):
            harness.publish(changed_draft, registry)
