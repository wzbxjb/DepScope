import hashlib
import json
from typing import Literal

from depscope.ingest.models import Contract, Coordinate, SourceRef
from depscope.runtime.errors import DomainError


class PackageQuery(Contract):
    coordinate: Coordinate
    status: Literal["matched","no_match","unqueried","partial","error","conflict"]
    record_ids: tuple[str,...] = ()
    source_refs: tuple[SourceRef,...] = ()
    issues: tuple[str,...] = ()


class AdvisoryRevision(Contract):
    id: str
    modified: str
    digest: str
    aliases: tuple[str,...]
    related: tuple[str,...]
    withdrawn: str | None
    affected: tuple[dict,...]
    summary: str
    details: str
    source: SourceRef

    @property
    def revision_id(self) -> str:
        return hashlib.sha256(json.dumps([self.id,self.modified,self.digest],separators=(",", ":")).encode()).hexdigest()


def parse_advisory(raw: bytes, source: SourceRef, expected_id: str) -> AdvisoryRevision:
    try:
        doc=json.loads(raw)
        if doc["id"] != expected_id or not isinstance(doc["modified"],str):
            raise ValueError
        return AdvisoryRevision(id=doc["id"],modified=doc["modified"],digest=source.digest,
                    aliases=tuple(doc.get("aliases",[])),related=tuple(doc.get("related",[])),
                    withdrawn=doc.get("withdrawn"),affected=tuple(doc.get("affected",[])),
                    summary=doc.get("summary",""),details=doc.get("details",""),source=source)
    except (ValueError,TypeError,KeyError):
        raise DomainError("ADVISORY_INVALID", "OSV advisory structure or identity is invalid") from None
