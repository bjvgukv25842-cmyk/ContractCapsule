"""Static schema document definitions for the seven CCS-2.1 modules."""

from __future__ import annotations

import json
from typing import Any

import jsonschema
from pydantic import BaseModel

from contractcapsule.models.core import (
    Capsule,
    CompressionPolicy,
    ControlManifest,
    DependencyGraph,
    EvidencePlane,
    ReplacementContract,
    SemanticPayload,
    TestsIntegrity,
)

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "control-manifest.schema.json": ControlManifest,
    "semantic-payload.schema.json": SemanticPayload,
    "evidence-plane.schema.json": EvidencePlane,
    "dependency-graph.schema.json": DependencyGraph,
    "replacement-contract.schema.json": ReplacementContract,
    "compression-policy.schema.json": CompressionPolicy,
    "tests-integrity.schema.json": TestsIntegrity,
    "capsule.schema.json": Capsule,
}


class CapsuleSchemaValidationError(ValueError):
    """The structural Schema or its mandatory semantic pass rejected a document."""


def schema_documents() -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for filename, model in SCHEMA_MODELS.items():
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://contractcapsule.example/schemas/{filename}"
        if model is Capsule:
            schema["x-contractcapsule-semantic-validation"] = (
                "contractcapsule.models.schema.validate_capsule_document"
            )
        documents[filename] = schema
    return documents


def validate_capsule_document(value: Any) -> Capsule:
    """Apply the public structural Schema and cross-record model invariants."""

    try:
        schema = schema_documents()["capsule.schema.json"]
        jsonschema.Draft202012Validator(schema).validate(value)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return Capsule.model_validate_json(encoded)
    except (TypeError, ValueError, jsonschema.ValidationError) as error:
        raise CapsuleSchemaValidationError("Capsule schema validation failed") from error
