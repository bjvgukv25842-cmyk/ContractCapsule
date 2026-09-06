"""Strict input and service checks before any public projection or source use."""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, TypeAdapter

from contractcapsule.audit.quarantine import scan_secrets
from contractcapsule.compile.errors import CompileError
from contractcapsule.models.base import Digest, Principal, SemVer, freeze_json
from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.models.core import Capsule
from contractcapsule.models.view import (
    CompileRequest,
    ServiceStamp,
    TaskContext,
    ViewBudget,
)
from contractcapsule.storage.registry import PublishedCapsule


def original_values(value: Any) -> Any:
    """Revalidate raw model trees before serializers can erase invalid fields."""
    if isinstance(value, BaseModel):
        fields = type(value).model_fields
        if set(vars(value)) != set(fields) or value.model_extra:
            raise CompileError("INVALID_REQUEST")
        values = {
            field.alias or name: original_values(getattr(value, name))
            for name, field in fields.items()
        }
        type(value).model_validate(values)
        return values
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise CompileError("INVALID_REQUEST")
        return {key: original_values(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(original_values(item) for item in value)
    if isinstance(value, list):
        return [original_values(item) for item in value]
    return value


def scan(value: object) -> None:
    try:
        scan_secrets(canonical_json_bytes(value))
    except Exception:  # noqa: BLE001 - scanner faults deny without disclosing the input.
        raise CompileError("SECRET_DETECTED") from None


def validate_request(request: CompileRequest) -> None:
    if type(request) is not CompileRequest:
        raise CompileError("INVALID_REQUEST")
    if (
        type(request.task) is not TaskContext
        or type(request.budget) is not ViewBudget
        or type(request.principal) is not Principal
        or type(request.principal.principal_id) is not str
    ):
        raise CompileError("INVALID_REQUEST")
    CompileRequest.model_validate(original_values(request))
    for pub in request.capsules:
        if type(pub) is not PublishedCapsule or type(pub.capsule) is not Capsule:
            raise CompileError("INVALID_REQUEST")
        Capsule.model_validate(original_values(pub.capsule))
    freeze_json(request.runtime_config)
    scan(
        {
            "task": original_values(request.task),
            "principal": request.principal.principal_id,
            "model_id": request.model_id,
            "tokenizer_profile": request.tokenizer_profile,
            "renderer_version": request.renderer_version,
            "runtime_config": request.runtime_config,
        }
    )


def stamp(name: str, service: object) -> ServiceStamp:
    version = getattr(service, "version", None)
    config = getattr(service, "config_digest", None)
    if type(version) is not str or not version:
        raise CompileError("INVALID_CONFIGURATION")
    config = TypeAdapter(Digest).validate_python(config, strict=True)
    if name != "renderer":
        TypeAdapter(SemVer).validate_python(version, strict=True)
    scan({"version": version})
    return ServiceStamp(name=name, version=version, config_digest=config)


def expansion_ids(request: CompileRequest, renderer: object) -> tuple[str, ...]:
    config = request.runtime_config
    if set(config) - {"expanded_handles"}:
        raise CompileError("INVALID_CONFIGURATION")
    requested = config.get("expanded_handles", ())
    configured = getattr(renderer, "expanded_handles", ())
    if type(requested) is not tuple or type(configured) is not tuple:
        raise CompileError("INVALID_CONFIGURATION")
    for item in (*requested, *configured):
        TypeAdapter(Digest).validate_python(item, strict=True)
    return tuple(sorted(set(requested) | set(configured)))
