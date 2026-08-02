"""Strict shared types for the CCS-2.1 canonical model."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
SEMVER_PATTERN = (
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
RFC3339_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?Z$"
)
MEDIA_TYPE_PATTERN = (
    r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+"
    r"(?:;[A-Za-z0-9!#$&^_.+-]+=[A-Za-z0-9!#$&^_.+\-]+)*$"
)
EXTENSION_PATTERN = re.compile(r"^x-[a-z0-9]+(?:-[a-z0-9]+)*$")

def _valid_date(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("date must be a real ISO 8601 calendar date") from error
    return value


def _valid_timestamp(value: str) -> str:
    try:
        datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ValueError("timestamp must be a real UTC RFC 3339 value") from error
    return value


Digest = Annotated[str, StringConstraints(pattern=DIGEST_PATTERN)]
SemVer = Annotated[str, StringConstraints(pattern=SEMVER_PATTERN)]
DateString = Annotated[
    str, StringConstraints(pattern=DATE_PATTERN), AfterValidator(_valid_date)
]
TimestampString = Annotated[
    str, StringConstraints(pattern=RFC3339_PATTERN), AfterValidator(_valid_timestamp)
]
MediaType = Annotated[str, StringConstraints(pattern=MEDIA_TYPE_PATTERN)]
NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
type JsonValue = (
    None | bool | int | float | str | tuple[JsonValue, ...] | Mapping[str, JsonValue]
)


class ModelInvariantError(ValueError):
    """Raised when a value violates a canonical-model invariant."""


def reject_surrogates(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ModelInvariantError("lone Unicode surrogate is not permitted")


def _freeze_number(value: float) -> int | float:
    if isinstance(value, int):
        if abs(value) > (2**53 - 1):
            raise ModelInvariantError("integer is outside the exact IEEE 754 range")
        return value
    if not math.isfinite(value):
        raise ModelInvariantError("non-finite number is not permitted")
    return value


def freeze_json(value: Any) -> JsonValue:
    """Validate and recursively freeze a JSON-compatible value."""

    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str):
            reject_surrogates(value)
        return value
    if isinstance(value, (int, float)):
        return _freeze_number(value)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ModelInvariantError("JSON object keys must be strings")
            reject_surrogates(key)
            result[key] = freeze_json(item)
        return MappingProxyType(result)
    raise ModelInvariantError(f"non-JSON value is not permitted: {type(value).__name__}")


def validate_extensions(value: Mapping[str, Any]) -> Mapping[str, JsonValue]:
    for key in value:
        if not EXTENSION_PATTERN.fullmatch(key):
            raise ModelInvariantError(f"invalid extension namespace: {key}")
    frozen = freeze_json(value)
    if not isinstance(frozen, Mapping):  # pragma: no cover - defensive typing guard
        raise ModelInvariantError("extensions must be an object")
    return frozen


def is_safe_relative_path(value: str, *, prefix: str | None = None) -> bool:
    if (
        not value
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
        or re.match(r"^[A-Za-z]:", value) is not None
    ):
        return False
    if any(part in {"", ".", ".."} for part in value.split("/")):
        return False
    return prefix is None or value.startswith(prefix)


def is_canonical_https_uri(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    hostname = parsed.hostname
    return (
        parsed.scheme == "https"
        and hostname is not None
        and hostname == hostname.lower()
        and re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", hostname) is not None
        and parsed.username is None
        and parsed.password is None
        and port not in {443}
        and not parsed.query
        and not parsed.fragment
        and parsed.netloc == parsed.netloc.lower()
        and "%" not in value
        and not parsed.path.endswith("/")
        and "//" not in parsed.path
        and not any(part in {".", ".."} for part in parsed.path.split("/"))
    )


class StrictFrozenModel(BaseModel):
    """Base class that rejects coercion, unknown fields, mutation and non-finite data."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def _reject_surrogates_in_model(self) -> StrictFrozenModel:
        def walk(value: Any) -> None:
            if isinstance(value, str):
                reject_surrogates(value)
            elif isinstance(value, BaseModel):
                for name in type(value).model_fields:
                    walk(getattr(value, name))
            elif isinstance(value, Mapping):
                for key, item in value.items():
                    reject_surrogates(str(key))
                    walk(item)
            elif isinstance(value, (tuple, list)):
                for item in value:
                    walk(item)

        walk(self)
        return self


class ExtensibleModel(StrictFrozenModel):
    """Strict model with the sole allowed unknown-data namespace."""

    extensions: Mapping[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={
            "propertyNames": {"pattern": r"^x-[a-z0-9]+(?:-[a-z0-9]+)*$"}
        }
    )

    @field_validator("extensions", mode="after")
    @classmethod
    def _freeze_extensions(cls, value: Mapping[str, Any]) -> Mapping[str, JsonValue]:
        return validate_extensions(value)

    @field_serializer("extensions")
    def _serialize_extensions(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return thaw_json(value)


def thaw_json(value: Any) -> Any:
    """Return mutable JSON containers for transport serialization only."""

    if isinstance(value, Mapping):
        return {str(key): thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class Principal:
    """Opaque caller identity interpreted only by a trusted policy resolver."""

    principal_id: str

    def __post_init__(self) -> None:
        if not self.principal_id:
            raise ValueError("principal_id must not be empty")
        reject_surrogates(self.principal_id)
