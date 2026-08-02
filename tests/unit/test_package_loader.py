from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from contractcapsule.models.canonical import canonical_digest
from contractcapsule.package import CapsuleLoadError, load_capsule
from tests.m2_helpers import CAS_BYTES, CAS_DIGEST, sample_capsule_data, write_package


def test_valid_package_loads_and_matches_declared_digest(tmp_path: Path) -> None:
    package, _ = write_package(
        tmp_path,
        sample_capsule_data(
            evidence_modes=("CAS", "GIT_IMMUTABLE", "EXTERNAL_IMMUTABLE")
        ),
    )
    capsule = load_capsule(package)
    assert capsule.control_manifest.content_digest == canonical_digest(capsule)
    assert {record.mode for record in capsule.evidence_plane.records} == {
        "CAS",
        "GIT_IMMUTABLE",
        "EXTERNAL_IMMUTABLE",
    }
    assert capsule.semantic_payload.extensions["x-payload-state"] == "validated"
    assert capsule.evidence_plane.extensions["x-evidence-retention"] == "locked"


@pytest.mark.parametrize("mode", ["GIT_IMMUTABLE", "EXTERNAL_IMMUTABLE"])
def test_non_cas_thin_package_does_not_require_local_blob(
    tmp_path: Path, mode: str
) -> None:
    package, _ = write_package(
        tmp_path, sample_capsule_data(evidence_modes=(mode,)), include_cas_blob=False
    )
    assert load_capsule(package).evidence_plane.records[0].mode == mode


def test_schema_invalid_package_fails_without_partial_capsule(tmp_path: Path) -> None:
    package, _ = write_package(tmp_path)
    manifest = package / "manifest.json"
    data = json.loads(manifest.read_text())
    del data["authority"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CapsuleLoadError, match="validation"):
        load_capsule(package)


def test_declared_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    package, _ = write_package(tmp_path)
    manifest = package / "manifest.json"
    data = json.loads(manifest.read_text())
    data["content_digest"] = "sha256:" + ("f" * 64)
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CapsuleLoadError, match="digest"):
        load_capsule(package)


def test_missing_or_tampered_cas_evidence_fails_closed(tmp_path: Path) -> None:
    package, _ = write_package(tmp_path, include_cas_blob=False)
    with pytest.raises(CapsuleLoadError, match="CAS evidence"):
        load_capsule(package)

    hex_digest = CAS_DIGEST.removeprefix("sha256:")
    blob = package / "evidence/blobs/sha256" / hex_digest[:2] / hex_digest[2:]
    blob.parent.mkdir(parents=True)
    blob.write_bytes(CAS_BYTES + b"tampered")
    with pytest.raises(CapsuleLoadError, match="digest"):
        load_capsule(package)


@pytest.mark.parametrize(
    ("field", "value"),
    [("path", "../secret"), ("path", "/etc/passwd"), ("path", "docs\\auth.md")],
)
def test_git_evidence_unsafe_paths_fail_closed(
    tmp_path: Path, field: str, value: str
) -> None:
    data = sample_capsule_data(evidence_modes=("GIT_IMMUTABLE",))
    data["evidence_plane"]["records"][0][field] = value
    package, _ = write_package(tmp_path, data, include_cas_blob=False)
    with pytest.raises(CapsuleLoadError, match="validation"):
        load_capsule(package)


@pytest.mark.parametrize("revision", ["HEAD", "main", "sha1:abc", "a" * 40])
def test_git_evidence_requires_algorithm_tagged_full_oid(
    tmp_path: Path, revision: str
) -> None:
    data = sample_capsule_data(evidence_modes=("GIT_IMMUTABLE",))
    data["evidence_plane"]["records"][0]["revision"] = revision
    package, _ = write_package(tmp_path, data, include_cas_blob=False)
    with pytest.raises(CapsuleLoadError, match="validation"):
        load_capsule(package)


@pytest.mark.parametrize(
    "uri",
    [
        "http://example.com/evidence",
        "https://user@example.com/evidence",
        "https://EXAMPLE.com/evidence",
        "https://example.com/evidence?mutable=yes",
        "https://example.com/evidence#fragment",
        "https://example.com/%65vidence",
        "https://example.com/evidence/",
        "https://example.com/evidence/.",
        "https://example.com/evidence/..",
    ],
)
def test_external_evidence_requires_canonical_immutable_locator(
    tmp_path: Path, uri: str
) -> None:
    data = sample_capsule_data(evidence_modes=("EXTERNAL_IMMUTABLE",))
    data["evidence_plane"]["records"][0]["uri"] = uri
    package, _ = write_package(tmp_path, data, include_cas_blob=False)
    with pytest.raises(CapsuleLoadError, match="validation"):
        load_capsule(package)


def test_unknown_file_is_rejected(tmp_path: Path) -> None:
    package, _ = write_package(tmp_path)
    (package / ".DS_Store").write_bytes(b"noise")
    with pytest.raises(CapsuleLoadError, match="unknown"):
        load_capsule(package)


def test_symlinked_file_is_rejected(tmp_path: Path) -> None:
    package, _ = write_package(tmp_path)
    manifest = package / "manifest.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(manifest.read_bytes())
    manifest.unlink()
    os.symlink(outside, manifest)
    with pytest.raises(CapsuleLoadError, match="symbolic link"):
        load_capsule(package)


def test_duplicate_json_key_is_rejected_before_model_validation(tmp_path: Path) -> None:
    package, _ = write_package(tmp_path)
    manifest = package / "manifest.json"
    manifest.write_text(
        manifest.read_text().replace(
            '"authority": "approved-project-policy",',
            '"authority": "approved-project-policy",\n  "authority": "other",',
        ),
        encoding="utf-8",
    )
    with pytest.raises(CapsuleLoadError, match="duplicate"):
        load_capsule(package)


def test_invalid_utf8_and_lone_surrogate_are_rejected(tmp_path: Path) -> None:
    package, _ = write_package(tmp_path)
    (package / "manifest.json").write_bytes(b'{"bad":"\xff"}')
    with pytest.raises(CapsuleLoadError, match="UTF-8"):
        load_capsule(package)

    package, _ = write_package(tmp_path / "second")
    manifest = package / "manifest.json"
    manifest.write_text(manifest.read_text().replace("team-auth", "\\ud800"))
    with pytest.raises(CapsuleLoadError, match="surrogate"):
        load_capsule(package)


@pytest.mark.parametrize(
    "relative",
    ["manifest.json", "payload/metadata.json", "evidence/metadata.json", "integrity/capsule.lock"],
)
def test_structured_carriers_must_be_json_objects(tmp_path: Path, relative: str) -> None:
    package, _ = write_package(tmp_path)
    (package / relative).write_text("[]\n")
    with pytest.raises(CapsuleLoadError, match="object"):
        load_capsule(package)


def test_unknown_evidence_mode_never_falls_back(tmp_path: Path) -> None:
    package, _ = write_package(tmp_path)
    source_map = package / "evidence/source-map.jsonl"
    record = json.loads(source_map.read_text())
    record["mode"] = "GIT"
    source_map.write_text(json.dumps(record) + "\n")
    with pytest.raises(CapsuleLoadError, match="validation"):
        load_capsule(package)


@pytest.mark.parametrize(
    "relative",
    [
        "manifest.json",
        "payload/atoms.jsonl",
        "evidence/source-map.jsonl",
        "graph/dependencies.json",
        "contracts/replacement.yaml",
        "policies/compression.yaml",
        "integrity/capsule.lock",
        "integrity/checksums.sha256",
    ],
)
def test_missing_required_core_carrier_fails_closed(
    tmp_path: Path, relative: str
) -> None:
    package, _ = write_package(tmp_path)
    (package / relative).unlink()
    with pytest.raises(CapsuleLoadError, match="missing"):
        load_capsule(package)


def test_checksum_mismatch_fails_closed(tmp_path: Path) -> None:
    package, _ = write_package(tmp_path)
    (package / "tests/static/schema-test.json").write_bytes(b"changed")
    with pytest.raises(CapsuleLoadError, match="checksum"):
        load_capsule(package)


def test_structured_file_key_order_and_whitespace_do_not_change_identity(
    tmp_path: Path,
) -> None:
    package, _ = write_package(tmp_path)
    original = load_capsule(package)
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    reordered = dict(reversed(tuple(manifest.items())))
    manifest_path.write_text(json.dumps(reordered, separators=(",", ":")))
    loaded = load_capsule(package)
    assert canonical_digest(loaded) == canonical_digest(original)


def test_detached_signature_value_and_envelope_do_not_change_identity(
    tmp_path: Path,
) -> None:
    package, _ = write_package(tmp_path)
    original = load_capsule(package)
    signature_path = package / "integrity/signature.json"
    signature = json.loads(signature_path.read_text())
    signature["value"] = "base64:AQ=="
    signature["envelope"] = {"x-transport": "different"}
    signature_path.write_text(json.dumps(signature))
    changed = load_capsule(package)
    assert canonical_digest(changed) == canonical_digest(original)


def test_duplicate_yaml_key_and_alias_are_rejected_before_model_validation(
    tmp_path: Path,
) -> None:
    package, _ = write_package(tmp_path)
    contract = package / "contracts/replacement.yaml"
    contract.write_text(
        contract.read_text().replace(
            '"contract_id": "auth.jwt-policy.v2",',
            '"contract_id": "auth.jwt-policy.v2",\n  "contract_id": "duplicate",',
        )
    )
    with pytest.raises(CapsuleLoadError, match="duplicate YAML"):
        load_capsule(package)

    package, _ = write_package(tmp_path / "alias")
    (package / "contracts/replacement.yaml").write_text("shared: &value []\ncopy: *value\n")
    with pytest.raises(CapsuleLoadError, match="aliases"):
        load_capsule(package)


def test_ambiguous_large_integer_is_rejected_before_model_validation(tmp_path: Path) -> None:
    data = sample_capsule_data(evidence_modes=("GIT_IMMUTABLE",))
    package, _ = write_package(tmp_path, data, include_cas_blob=False)
    source_map = package / "evidence/source-map.jsonl"
    record = json.loads(source_map.read_text())
    record["locator"]["start_line"] = 2**53
    source_map.write_text(json.dumps(record) + "\n")
    with pytest.raises(CapsuleLoadError, match="IEEE 754"):
        load_capsule(package)


def test_cross_mode_fields_do_not_silently_fall_back(tmp_path: Path) -> None:
    package, _ = write_package(tmp_path)
    source_map = package / "evidence/source-map.jsonl"
    record = json.loads(source_map.read_text())
    record["repository"] = "https://github.com/example/api"
    source_map.write_text(json.dumps(record) + "\n")
    with pytest.raises(CapsuleLoadError, match="validation"):
        load_capsule(package)


def test_symlinked_cas_object_is_rejected(tmp_path: Path) -> None:
    package, _ = write_package(tmp_path)
    hex_digest = CAS_DIGEST.removeprefix("sha256:")
    blob = package / "evidence/blobs/sha256" / hex_digest[:2] / hex_digest[2:]
    outside = tmp_path / "outside-evidence"
    outside.write_bytes(blob.read_bytes())
    blob.unlink()
    os.symlink(outside, blob)
    with pytest.raises(CapsuleLoadError, match="symbolic link"):
        load_capsule(package)


def test_package_reached_through_symlinked_parent_is_rejected(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    package, _ = write_package(real_parent)
    alias = tmp_path / "alias"
    os.symlink(real_parent, alias)
    assert package == real_parent / "capsule"
    with pytest.raises(CapsuleLoadError, match="symbolic link"):
        load_capsule(alias / "capsule")


@pytest.mark.parametrize(
    "relative",
    ["payload/metadata.json", "evidence/metadata.json"],
)
def test_module_extension_carriers_are_optional(tmp_path: Path, relative: str) -> None:
    data = sample_capsule_data()
    data["semantic_payload"]["extensions"] = {}
    data["evidence_plane"]["extensions"] = {}
    package, _ = write_package(tmp_path, data)
    (package / relative).unlink()
    capsule = load_capsule(package)
    module = (
        capsule.semantic_payload
        if relative.startswith("payload/")
        else capsule.evidence_plane
    )
    assert not module.extensions


@pytest.mark.parametrize(
    "relative",
    [
        "payload/metadata.json",
        "evidence/metadata.json",
        "integrity/capsule.lock",
    ],
)
def test_carrier_unknown_fields_are_rejected(tmp_path: Path, relative: str) -> None:
    package, _ = write_package(tmp_path)
    carrier = package / relative
    data = json.loads(carrier.read_text())
    data["unexpected_security_field"] = "must-not-be-dropped"
    carrier.write_text(json.dumps(data) + "\n")
    with pytest.raises(CapsuleLoadError, match="unknown.*field"):
        load_capsule(package)


def test_malformed_manifest_integrity_is_a_loader_error(tmp_path: Path) -> None:
    package, _ = write_package(tmp_path)
    manifest = package / "manifest.json"
    data = json.loads(manifest.read_text())
    data["integrity"] = "not-an-object"
    manifest.write_text(json.dumps(data) + "\n")
    with pytest.raises(CapsuleLoadError, match="integrity"):
        load_capsule(package)


def test_empty_lock_extensions_may_be_omitted(tmp_path: Path) -> None:
    package, _ = write_package(tmp_path)
    lock_path = package / "integrity/capsule.lock"
    lock = json.loads(lock_path.read_text())
    assert lock.pop("extensions") == {}
    lock_path.write_text(json.dumps(lock) + "\n")
    assert load_capsule(package).tests_integrity.extensions == {}
