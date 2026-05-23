"""Vendored JSON Schema package.

Canonical Augur record schemas live here so the SDK has zero runtime
dependency on a sibling `augur-schema` package. The schemas are
byte-identical with the upstream `packages/schema/` in the main Augur
monorepo — keep them in sync when bumping versions.

See `docs/versioning.md` upstream for the schema versioning policy.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMA_VERSION = "0.1"

_SCHEMA_FILES: dict[str, str] = {
    "manifest": "manifest.schema.json",
    "trace": "trace.schema.json",
    "debug_session": "debug_session.schema.json",
    "step_trace": "step_trace.schema.json",
    "observation": "observation.schema.json",
    "decision_event": "decision_event.schema.json",
    "replay_fixture": "replay_fixture.schema.json",
    "modelio": "modelio.schema.json",
    "side_effect": "side_effect.schema.json",
    "preference": "preference.schema.json",
    "prior_steps": "prior_steps.schema.json",
    "diagnostic_finding": "diagnostic_finding.schema.json",
    "coordinate_space": "coordinate_space.schema.json",
    "provenance": "provenance.schema.json",
    "capture_mode": "capture_mode.schema.json",
    "failure_class": "failure_class.schema.json",
}


class SchemaError(Exception):
    """Wraps schema lookup and validation failures."""


def schemas_dir() -> Path:
    """Return the on-disk path to the bundled JSON Schemas."""
    return Path(resources.files("augur_sdk._schema") / "json")  # type: ignore[arg-type]


def list_schemas() -> list[str]:
    return sorted(_SCHEMA_FILES)


@cache
def load_schema(name: str) -> dict[str, Any]:
    filename = _SCHEMA_FILES.get(name, name)
    path = schemas_dir() / filename
    if not path.exists():
        raise SchemaError(f"unknown schema: {name!r}")
    with path.open() as f:
        loaded: dict[str, Any] = json.load(f)
    return loaded


@cache
def _registry() -> Registry:
    """Pre-register every schema by `$id` and filename so cross-schema
    `$ref`s resolve without going to the network."""
    resources_list: list[tuple[str, Resource[Any]]] = []
    for short, filename in _SCHEMA_FILES.items():
        schema = load_schema(short)
        resource = DRAFT202012.create_resource(schema)
        if "$id" in schema:
            resources_list.append((schema["$id"], resource))
        resources_list.append((filename, resource))
    return Registry().with_resources(resources_list)


def validator_for(name: str) -> Draft202012Validator:
    schema = load_schema(name)
    return Draft202012Validator(schema, registry=_registry())


__all__ = [
    "SCHEMA_VERSION",
    "SchemaError",
    "ValidationError",
    "list_schemas",
    "load_schema",
    "schemas_dir",
    "validator_for",
]
