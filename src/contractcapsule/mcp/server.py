"""Strict JSON-RPC facade over the trusted ContractCapsule services.

The facade is deliberately small.  It accepts references and validated task
inputs, asks the Registry to re-authorize every publication, and delegates
compilation, evidence expansion, and replacement to explicitly injected core
services.  It never serializes a capsule payload or an approval authority.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TextIO, cast

from pydantic import TypeAdapter, ValidationError

from contractcapsule.compile.errors import CompileError
from contractcapsule.models.base import Principal, SemVer
from contractcapsule.models.canonical import canonical_digest
from contractcapsule.models.core import Capsule
from contractcapsule.models.view import (
    CapsuleRef,
    CompiledView,
    CompileRequest,
    EvidenceHandle,
    EvidenceMaterial,
    TaskContext,
    ViewBudget,
    view_manifest_digest,
)
from contractcapsule.storage.registry import (
    PublishedCapsule,
    Registry,
    RegistryError,
    RegistryNotFound,
)
from contractcapsule.swap.runtime_models import (
    ActivationReceipt,
    BoundaryTicket,
    RollbackReceipt,
)
from contractcapsule.swap.store import RuntimeStoreError
from contractcapsule.validate.approvals import Approval

_SAFE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_JSONRPC_KEYS = frozenset({"jsonrpc", "id", "method", "params"})
_METHODS = frozenset(
    {
        "discover_capsules",
        "compile_view",
        "expand_evidence",
        "compare_capsules",
        "activate_capsule",
        "rollback_capsule",
    }
)

_MESSAGES = {
    "INVALID_REQUEST": "invalid request",
    "INVALID_PARAMS": "invalid parameters",
    "METHOD_NOT_FOUND": "method not found",
    "PERMISSION_DENIED": "permission denied",
    "CAPSULE_UNAVAILABLE": "capsule is unavailable",
    "CAPSULE_INTEGRITY": "capsule integrity check failed",
    "REGISTRY_UNAVAILABLE": "registry is unavailable",
    "COMPILATION_FAILED": "compilation failed",
    "EVIDENCE_UNAUTHORIZED": "evidence is not authorized",
    "EVIDENCE_UNAVAILABLE": "evidence is unavailable",
    "ACTIVATION_FAILED": "activation failed",
    "ROLLBACK_FAILED": "rollback failed",
    "INTERNAL_ERROR": "internal error",
}


class MCPError(ValueError):
    """An intentionally non-disclosing transport/domain error."""

    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or _SAFE_CODE.fullmatch(code) is None:
            code = "INTERNAL_ERROR"
        self.code = code
        super().__init__(code)


def _message(code: str) -> str:
    return _MESSAGES.get(code, "request failed")


def _error_response(request_id: object, code: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": _message(code)},
    }


def _success_response(request_id: object, result: Mapping[str, object]) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": dict(result)}


def _string(value: object, *, field: str) -> str:
    if type(value) is not str or not value or any(
        0xD800 <= ord(character) <= 0xDFFF for character in value
    ):
        raise MCPError("INVALID_PARAMS")
    return value


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise MCPError("INVALID_PARAMS")
    return value


def _keys(
    params: Mapping[str, object], *, allowed: set[str], required: set[str] | None = None
) -> None:
    required = set() if required is None else required
    if set(params) - allowed or not required <= set(params):
        raise MCPError("INVALID_PARAMS")


def _json_safe(value: object) -> object:
    """Normalize a model projection and reject non-JSON transport values."""

    if value is None or type(value) in {bool, int, float, str}:
        if type(value) is float and not math.isfinite(value):
            raise MCPError("INTERNAL_ERROR")
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise MCPError("INTERNAL_ERROR")
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    raise MCPError("INTERNAL_ERROR")


def _model_json(value: object) -> dict[str, object]:
    dump = getattr(value, "model_dump", None)
    if not callable(dump):
        raise MCPError("INTERNAL_ERROR")
    try:
        result = _json_safe(dump(mode="json"))
    except MCPError:
        raise
    except Exception:  # noqa: BLE001 - transport projection must not leak model faults.
        raise MCPError("INTERNAL_ERROR") from None
    if not isinstance(result, dict):
        raise MCPError("INTERNAL_ERROR")
    return result


def _principal(params: Mapping[str, object], *, required: bool = True) -> Principal | None:
    value = params.get("principal_id")
    if value is None and not required:
        return None
    return Principal(_string(value, field="principal_id"))


def _ref_input(value: object) -> tuple[str, str, str | None]:
    raw = _mapping(value)
    _keys(raw, allowed={"capsule_id", "version", "digest"}, required={"capsule_id", "version"})
    capsule_id = _string(raw["capsule_id"], field="capsule_id")
    version = _string(raw["version"], field="version")
    try:
        TypeAdapter(SemVer).validate_python(version, strict=True)
    except (TypeError, ValueError):
        raise MCPError("INVALID_PARAMS") from None
    digest = raw.get("digest")
    if digest is not None:
        digest = _string(digest, field="digest")
        try:
            CapsuleRef(capsule_id=capsule_id, version=version, digest=digest)
        except (TypeError, ValueError, ValidationError):
            raise MCPError("INVALID_PARAMS") from None
    return capsule_id, version, digest


def _sequence(value: object, *, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes, bytearray)):
        raise MCPError("INVALID_PARAMS")
    return tuple(value)


def _task(value: object) -> TaskContext:
    raw = dict(_mapping(value))
    for name in ("paths", "required_interfaces", "required_atom_ids"):
        if name in raw:
            raw[name] = tuple(_sequence(raw[name], field=name))
    try:
        return TaskContext.model_validate(raw)
    except (TypeError, ValueError, ValidationError):
        raise MCPError("INVALID_PARAMS") from None


def _budget(value: object) -> ViewBudget:
    try:
        return ViewBudget.model_validate(_mapping(value))
    except (TypeError, ValueError, ValidationError):
        raise MCPError("INVALID_PARAMS") from None


def _ref_projection(publication: PublishedCapsule) -> dict[str, object]:
    if type(publication) is not PublishedCapsule or type(publication.capsule) is not Capsule:
        raise MCPError("CAPSULE_INTEGRITY")
    manifest = publication.capsule.control_manifest
    return {
        "capsule_id": manifest.capsule_id,
        "version": manifest.version,
        "digest": manifest.content_digest,
        "registry_status": publication.registry_status,
        "published_at": publication.published_at,
    }


def _receipt_projection(value: object, receipt_type: type[object]) -> dict[str, object]:
    if isinstance(value, receipt_type):
        return _model_json(value)
    # Test doubles and alternate core implementations may return a plain JSON
    # projection.  Whitelist the receipt fields so arbitrary internal objects or
    # approval material cannot cross the transport boundary.
    if isinstance(value, Mapping):
        fields = set(getattr(receipt_type, "model_fields", {}))
        if set(value) <= fields:
            result = _json_safe(value)
            if isinstance(result, dict):
                return result
    raise MCPError("INTERNAL_ERROR")


def _policy_checker(authorizer: object) -> Callable[..., object] | None:
    for name in ("authorize_request", "authorize_mcp", "allow"):
        candidate = getattr(authorizer, name, None)
        if callable(candidate):
            return cast(Callable[..., object], candidate)
    # EligibilityAuthorizer.authorize has a capsule-level signature and is
    # exercised by Registry/compiler, so it is not an MCP operation hook.
    candidate = getattr(authorizer, "authorize", None)
    if callable(candidate) and not hasattr(authorizer, "context_digest"):
        return cast(Callable[..., object], candidate)
    if callable(authorizer):
        return cast(Callable[..., object], authorizer)
    return None


def _policy_decision(
    checker: Callable[..., object], action: str, principal: Principal, params: Mapping[str, object]
) -> bool:
    try:
        decision = checker(action, principal, dict(params))
    except TypeError:
        try:
            decision = checker(principal, action, dict(params))
        except Exception:  # noqa: BLE001 - policy faults deny access.
            return False
    except Exception:  # noqa: BLE001 - policy faults deny access.
        return False
    return decision is True


def _public_manifest_fields(publication: PublishedCapsule) -> dict[str, object]:
    manifest = publication.capsule.control_manifest
    wire = manifest.model_dump(mode="json")
    fields = (
        "capsule_id",
        "version",
        "tenant",
        "authority",
        "lifecycle",
        "sensitivity",
        "provides",
        "requires",
        "conflicts",
        "scope",
        "content_digest",
    )
    return {field: wire[field] for field in fields if field in wire}


@dataclass(frozen=True, slots=True)
class MCPService:
    """Explicitly composed MCP operations; no module-level service singleton."""

    registry: object
    compiler: object
    evidence: object
    swap: object
    authorizer: object

    def __post_init__(self) -> None:
        if any(value is None for value in (self.registry, self.compiler, self.evidence, self.swap, self.authorizer)):
            raise MCPError("INVALID_CONFIGURATION")
        if not callable(getattr(self.registry, "get", None)):
            raise MCPError("INVALID_CONFIGURATION")
        if not callable(getattr(self.compiler, "compile_view", None)):
            raise MCPError("INVALID_CONFIGURATION")
        if not callable(getattr(self.evidence, "expand", None)):
            raise MCPError("INVALID_CONFIGURATION")
        if not callable(getattr(self.swap, "activate", None)) or not callable(
            getattr(self.swap, "rollback", None)
        ):
            raise MCPError("INVALID_CONFIGURATION")

    def _authorize(
        self, action: str, principal: Principal | None, params: Mapping[str, object]
    ) -> None:
        """Invoke an optional MCP-specific policy hook before core delegation."""

        if principal is None:
            return
        checker = _policy_checker(self.authorizer)
        if checker is None:
            return
        if not _policy_decision(checker, action, principal, params):
            raise MCPError("PERMISSION_DENIED")

    def _fetch(
        self, ref: tuple[str, str, str | None], principal: Principal
    ) -> PublishedCapsule:
        capsule_id, version, expected_digest = ref
        try:
            registry_get = cast(
                Callable[[str, str, Principal], object],
                getattr(self.registry, "get"),  # noqa: B009
            )
            publication = registry_get(capsule_id, version, principal)
        except RegistryNotFound:
            raise MCPError("CAPSULE_UNAVAILABLE") from None
        except RegistryError:
            raise MCPError("REGISTRY_UNAVAILABLE") from None
        except Exception:  # noqa: BLE001 - registry faults are non-disclosing.
            raise MCPError("REGISTRY_UNAVAILABLE") from None
        if type(publication) is not PublishedCapsule or type(publication.capsule) is not Capsule:
            raise MCPError("CAPSULE_INTEGRITY")
        actual = publication.capsule.control_manifest
        if expected_digest is not None and actual.content_digest != expected_digest:
            raise MCPError("CAPSULE_INTEGRITY")
        if publication.registry_status != "PUBLISHED" or actual.lifecycle != "PUBLISHED":
            raise MCPError("CAPSULE_UNAVAILABLE")
        return publication

    def _discover_candidates(
        self, principal: Principal, capsule_id: str | None, version: str | None, limit: int
    ) -> list[tuple[str, str]]:
        custom = getattr(self.registry, "discover_capsules", None)
        if callable(custom):
            return self._custom_candidates(custom, principal, capsule_id, version, limit)
        if type(self.registry) is not Registry:
            raise MCPError("REGISTRY_UNAVAILABLE")
        return self._sqlite_candidates(capsule_id, version, limit)

    @staticmethod
    def _custom_candidates(
        custom: Callable[..., object],
        principal: Principal,
        capsule_id: str | None,
        version: str | None,
        limit: int,
    ) -> list[tuple[str, str]]:
        try:
            candidates_wire = custom(
                principal, capsule_id=capsule_id, version=version, limit=limit
            )
        except TypeError:
            try:
                candidates_wire = custom(principal)
            except Exception:  # noqa: BLE001 - registry faults are non-disclosing.
                raise MCPError("REGISTRY_UNAVAILABLE") from None
        except Exception:  # noqa: BLE001 - registry faults are non-disclosing.
            raise MCPError("REGISTRY_UNAVAILABLE") from None
        if not isinstance(candidates_wire, (list, tuple)):
            raise MCPError("REGISTRY_UNAVAILABLE")
        candidates: list[tuple[str, str]] = []
        for value in candidates_wire:
            if isinstance(value, PublishedCapsule):
                manifest = value.capsule.control_manifest
                candidates.append((manifest.capsule_id, manifest.version))
            elif isinstance(value, Mapping):
                ref = _ref_input(value)
                candidates.append((ref[0], ref[1]))
            else:
                raise MCPError("REGISTRY_UNAVAILABLE")
        return candidates[:limit]

    def _sqlite_candidates(
        self, capsule_id: str | None, version: str | None, limit: int
    ) -> list[tuple[str, str]]:
        try:
            with self.registry._connect() as connection:  # type: ignore[attr-defined]
                clauses: list[str] = []
                query_values: list[object] = []
                if capsule_id is not None:
                    clauses.append("capsule_id = ?")
                    query_values.append(capsule_id)
                if version is not None:
                    clauses.append("version = ?")
                    query_values.append(version)
                where = " WHERE " + " AND ".join(clauses) if clauses else ""
                rows = connection.execute(
                    "SELECT capsule_id, version FROM publications"
                    + where
                    + " ORDER BY capsule_id, version LIMIT ?",
                    (*query_values, limit),
                ).fetchall()
        except (sqlite3.Error, OSError):
            raise MCPError("REGISTRY_UNAVAILABLE") from None
        return [(str(row[0]), str(row[1])) for row in rows]

    def discover_capsules(self, params: Mapping[str, object]) -> dict[str, object]:
        _keys(
            params,
            allowed={"principal_id", "capsule_id", "version", "limit"},
            required={"principal_id"},
        )
        principal = _principal(params)
        assert principal is not None
        self._authorize("discover_capsules", principal, params)
        capsule_id = params.get("capsule_id")
        if capsule_id is not None:
            capsule_id = _string(capsule_id, field="capsule_id")
        version = params.get("version")
        if version is not None:
            version = _string(version, field="version")
            try:
                TypeAdapter(SemVer).validate_python(version, strict=True)
            except (TypeError, ValueError):
                raise MCPError("INVALID_PARAMS") from None
        limit = params.get("limit", 100)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise MCPError("INVALID_PARAMS")
        result: list[dict[str, object]] = []
        for candidate in self._discover_candidates(principal, capsule_id, version, limit):
            try:
                publication = self._fetch((*candidate, None), principal)
            except MCPError as error:
                if error.code == "CAPSULE_UNAVAILABLE":
                    continue
                raise
            result.append(_ref_projection(publication))
        result.sort(key=lambda item: (str(item["capsule_id"]), str(item["version"])))
        return {"capsules": result}

    def compile_view(self, params: Mapping[str, object]) -> dict[str, object]:
        allowed = {
            "principal_id",
            "capsules",
            "task",
            "budget",
            "as_of",
            "model_id",
            "tokenizer_profile",
            "renderer_version",
            "runtime_config",
            "expected_manifest_digest",
        }
        _keys(params, allowed=allowed, required=allowed - {"renderer_version", "runtime_config", "expected_manifest_digest"})
        principal = _principal(params)
        assert principal is not None
        self._authorize("compile_view", principal, params)
        refs = _sequence(params["capsules"], field="capsules")
        if not refs:
            raise MCPError("INVALID_PARAMS")
        publications: list[PublishedCapsule] = []
        seen: set[tuple[str, str]] = set()
        for raw_ref in refs:
            ref = _ref_input(raw_ref)
            key = (ref[0], ref[1])
            if key in seen:
                raise MCPError("INVALID_PARAMS")
            seen.add(key)
            publications.append(self._fetch(ref, principal))
        task = _task(params["task"])
        budget = _budget(params["budget"])
        request_values: dict[str, object] = {
            "capsules": tuple(publications),
            "task": task,
            "principal": principal,
            "budget": budget,
            "as_of": _string(params["as_of"], field="as_of"),
            "model_id": _string(params["model_id"], field="model_id"),
            "tokenizer_profile": _string(
                params["tokenizer_profile"], field="tokenizer_profile"
            ),
        }
        for optional in ("renderer_version", "runtime_config", "expected_manifest_digest"):
            if optional in params:
                request_values[optional] = params[optional]
        try:
            request = CompileRequest.model_validate(request_values)
        except (TypeError, ValueError, ValidationError):
            raise MCPError("INVALID_PARAMS") from None
        try:
            compile_method = cast(
                Callable[[CompileRequest], object],
                getattr(self.compiler, "compile_view"),  # noqa: B009
            )
            view = compile_method(request)
        except CompileError as error:
            raise MCPError(error.code) from None
        except Exception:  # noqa: BLE001 - compiler faults are non-disclosing.
            raise MCPError("COMPILATION_FAILED") from None
        if type(view) is not CompiledView:
            raise MCPError("COMPILATION_FAILED")
        projection = _model_json(view)
        return {
            "view": projection,
            "manifest_digest": view_manifest_digest(view.manifest),
        }

    def expand_evidence(self, params: Mapping[str, object]) -> dict[str, object]:
        _keys(
            params,
            allowed={"principal_id", "handle", "task", "as_of"},
            required={"principal_id", "handle", "task", "as_of"},
        )
        principal = _principal(params)
        assert principal is not None
        self._authorize("expand_evidence", principal, params)
        try:
            handle_raw = dict(_mapping(params["handle"]))
            if "atom_ids" in handle_raw:
                handle_raw["atom_ids"] = tuple(
                    _sequence(handle_raw["atom_ids"], field="atom_ids")
                )
            handle = EvidenceHandle.model_validate(handle_raw)
        except (TypeError, ValueError, ValidationError):
            raise MCPError("INVALID_PARAMS") from None
        task = _task(params["task"])
        as_of = _string(params["as_of"], field="as_of")
        try:
            expand_method = cast(
                Callable[[EvidenceHandle, Principal, TaskContext, str], object],
                getattr(self.evidence, "expand"),  # noqa: B009
            )
            material = expand_method(handle, principal, task, as_of)
        except CompileError as error:
            raise MCPError(error.code) from None
        except Exception:  # noqa: BLE001 - evidence faults are non-disclosing.
            raise MCPError("EVIDENCE_UNAVAILABLE") from None
        if type(material) is not EvidenceMaterial or material.handle != handle:
            raise MCPError("EVIDENCE_INTEGRITY")
        return {"evidence": _model_json(material), "handle_id": handle.handle_id}

    def compare_capsules(self, params: Mapping[str, object]) -> dict[str, object]:
        _keys(
            params,
            allowed={"principal_id", "old", "new"},
            required={"principal_id", "old", "new"},
        )
        principal = _principal(params)
        assert principal is not None
        self._authorize("compare_capsules", principal, params)
        old = self._fetch(_ref_input(params["old"]), principal)
        new = self._fetch(_ref_input(params["new"]), principal)
        try:
            old_manifest = _public_manifest_fields(old)
            new_manifest = _public_manifest_fields(new)
            changed = sorted(
                key
                for key in set(old_manifest) | set(new_manifest)
                if old_manifest.get(key) != new_manifest.get(key)
            )
            same_digest = canonical_digest(old.capsule) == canonical_digest(new.capsule)
        except Exception:  # noqa: BLE001 - capsule projections are non-disclosing.
            raise MCPError("CAPSULE_INTEGRITY") from None
        return {
            "old": _ref_projection(old),
            "new": _ref_projection(new),
            "same_digest": same_digest,
            "changed_manifest_fields": changed,
        }

    def activate_capsule(self, params: Mapping[str, object]) -> dict[str, object]:
        _keys(
            params,
            allowed={"prepared_id", "ticket", "approval", "principal_id"},
            required={"prepared_id", "ticket"},
        )
        principal = _principal(params, required=False)
        self._authorize("activate_capsule", principal, params)
        prepared_id = _string(params["prepared_id"], field="prepared_id")
        try:
            ticket = BoundaryTicket.model_validate(dict(_mapping(params["ticket"])))
            approval = (
                None
                if params.get("approval") is None
                else Approval.model_validate(dict(_mapping(params["approval"])))
            )
        except (TypeError, ValueError, ValidationError):
            raise MCPError("INVALID_PARAMS") from None
        try:
            activate_method = cast(
                Callable[[str, BoundaryTicket, Approval | None], object],
                getattr(self.swap, "activate"),  # noqa: B009
            )
            receipt = activate_method(prepared_id, ticket, approval)
        except (RuntimeStoreError, ValueError):
            raise MCPError("ACTIVATION_FAILED") from None
        except Exception:  # noqa: BLE001 - activation faults are non-disclosing.
            raise MCPError("ACTIVATION_FAILED") from None
        return {"receipt": _receipt_projection(receipt, ActivationReceipt)}

    def rollback_capsule(self, params: Mapping[str, object]) -> dict[str, object]:
        _keys(
            params,
            allowed={"receipt_id", "ticket", "principal_id"},
            required={"receipt_id", "ticket"},
        )
        principal = _principal(params, required=False)
        self._authorize("rollback_capsule", principal, params)
        receipt_id = _string(params["receipt_id"], field="receipt_id")
        try:
            ticket = BoundaryTicket.model_validate(dict(_mapping(params["ticket"])))
        except (TypeError, ValueError, ValidationError):
            raise MCPError("INVALID_PARAMS") from None
        try:
            rollback_method = cast(
                Callable[[str, BoundaryTicket], object],
                getattr(self.swap, "rollback"),  # noqa: B009
            )
            receipt = rollback_method(receipt_id, ticket)
        except (RuntimeStoreError, ValueError):
            raise MCPError("ROLLBACK_FAILED") from None
        except Exception:  # noqa: BLE001 - rollback faults are non-disclosing.
            raise MCPError("ROLLBACK_FAILED") from None
        return {"receipt": _receipt_projection(receipt, RollbackReceipt)}


def _request_id(request: Mapping[str, object]) -> object:
    if "id" not in request:
        return None
    value = request["id"]
    if value is None or type(value) in {str, int}:
        return value
    raise MCPError("INVALID_REQUEST")


def handle_request(
    service: MCPService, request: Mapping[str, object]
) -> dict[str, object]:
    """Handle one JSON-RPC request and return a safe JSON object."""

    request_id: object = None
    try:
        if not isinstance(request, Mapping):
            raise MCPError("INVALID_REQUEST")
        request_id = _request_id(request)
        if set(request) - _JSONRPC_KEYS or request.get("jsonrpc") != "2.0":
            raise MCPError("INVALID_REQUEST")
        method = request.get("method")
        if type(method) is not str or not method:
            raise MCPError("INVALID_REQUEST")
        params_value = request.get("params", {})
        params = _mapping(params_value)
        if method not in _METHODS:
            raise MCPError("METHOD_NOT_FOUND")
        result = getattr(service, method)(params)
        if not isinstance(result, Mapping):
            raise MCPError("INTERNAL_ERROR")
        safe_result = _json_safe(result)
        if not isinstance(safe_result, dict):
            raise MCPError("INTERNAL_ERROR")
        return _success_response(request_id, safe_result)
    except MCPError as error:
        return _error_response(request_id, error.code)
    except ValidationError:
        return _error_response(request_id, "INVALID_PARAMS")
    except Exception:  # noqa: BLE001 - JSON-RPC boundary is non-disclosing.
        return _error_response(request_id, "INTERNAL_ERROR")


def handle_json(service: MCPService, raw: str) -> dict[str, object]:
    """Decode one JSON request without exposing decoder or model details."""

    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _error_response(None, "INVALID_REQUEST")
    if not isinstance(value, Mapping):
        return _error_response(None, "INVALID_REQUEST")
    return handle_request(service, value)


def serve_stdio(
    service: MCPService, input_stream: TextIO, output_stream: TextIO
) -> None:
    """Serve newline-delimited JSON-RPC requests over an injected stdio pair."""

    for line in input_stream:
        if not line.strip():
            continue
        response = handle_json(service, line)
        output_stream.write(json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n")
        output_stream.flush()


__all__ = ["MCPError", "MCPService", "handle_json", "handle_request", "serve_stdio"]
