"""Verified local schema registry; no network retrieval hook exists."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from depscope.runtime.config import PROJECT_ROOT
from depscope.runtime.errors import DomainError


def load_schema_registry(directory: Path) -> Registry:
    manifest = json.loads((directory / "manifest.json").read_bytes())
    registry = Registry()
    for record in manifest["records"]:
        raw = (directory / record["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise DomainError("SCHEMA_INTEGRITY", "Local schema digest mismatch")
        resource = Resource.from_contents(json.loads(raw), default_specification=DRAFT7)
        for uri in [record["schema_id"], record["source_uri"]]:
            registry = registry.with_resource(uri, resource)
    return registry


@lru_cache(maxsize=1)
def cyclonedx_validator() -> Draft7Validator:
    directory = PROJECT_ROOT / "schemas/cyclonedx/1.6"
    schema = json.loads((directory / "bom-1.6.schema.json").read_bytes())
    return Draft7Validator(schema, registry=load_schema_registry(directory))
