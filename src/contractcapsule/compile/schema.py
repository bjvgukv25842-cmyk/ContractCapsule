"""Independent B-zone schema; never part of the eight A-zone identity schemas."""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from contractcapsule.models.view import ViewManifest


def view_manifest_schema() -> dict[str, Any]:
    schema = ViewManifest.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://contractcapsule.invalid/schemas/view-manifest.schema.json"
    return schema


def validate_view_manifest(value: object) -> None:
    Draft202012Validator(
        view_manifest_schema(), format_checker=FormatChecker()
    ).validate(value)
    ViewManifest.model_validate_json(json.dumps(value, allow_nan=False))


def write_view_manifest_schema(path: Path) -> None:
    path.write_text(
        json.dumps(view_manifest_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    import sys

    write_view_manifest_schema(Path(sys.argv[1]))
