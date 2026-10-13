"""Strict immutable boundary objects; instances retain their source context."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class Coordinate(Contract):
    ecosystem: Literal["PyPI"] = "PyPI"
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    raw_version: str = Field(min_length=1)

    @property
    def key(self) -> str:
        # raw_version is provenance, not package identity.
        import hashlib
        import json
        return hashlib.sha256(json.dumps([self.ecosystem, self.name, self.version],
                              separators=(",", ":")).encode()).hexdigest()


class Component(Contract):
    local_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    coordinate: Coordinate | None
    dependencies_known: bool
    pointer: str


class Edge(Contract):
    from_id: str = Field(min_length=1)
    to_id: str = Field(min_length=1)
    requirement: str | None = None
    pointer: str


class SourceRef(Contract):
    uri: str = Field(min_length=1)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: str
    parser_version: str = Field(min_length=1)

    @field_validator("observed_at")
    @classmethod
    def utc_time(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError("Source timestamps must be UTC")
        return value


class Snapshot(Contract):
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_id: str = Field(min_length=1)
    source_kind: Literal["public_resolution", "observed_environment", "constructed"]
    source: SourceRef
    components: tuple[Component, ...]
    edges: tuple[Edge, ...]
    root_id: str | None
    environment: dict
    issues: tuple[str, ...] = ()

    @model_validator(mode="after")
    def consistent_instances(self) -> "Snapshot":
        ids = {c.local_id for c in self.components}
        if len(ids) != len(self.components):
            raise ValueError("DUPLICATE_COMPONENT: local IDs must be unique")
        if any(e.from_id not in ids or e.to_id not in ids for e in self.edges):
            raise ValueError("DANGLING_EDGE: both endpoints must belong to this snapshot")
        if self.root_id is not None and self.root_id not in ids:
            raise ValueError("UNKNOWN_ROOT: root must belong to this snapshot")
        if len(self.components) > 10000 or len(self.edges) > 50000:
            raise ValueError("LIMIT_EXCEEDED: snapshot exceeds bounded graph limits")
        return self
