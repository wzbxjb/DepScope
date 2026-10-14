import hashlib
import json

from pydantic import Field

from depscope.ingest.models import Contract


class EvidenceDocument(Contract):
    id: str
    text: str
    source_ids: tuple[str,...] = Field(min_length=1)
    pointers: tuple[str,...] = Field(min_length=1)
    snapshot_id: str | None
    run_id: str | None
    entity_keys: tuple[str,...]
    comparison_id: str | None = None


class EvidenceChunk(Contract):
    evidence_id: str
    document_id: str
    text: str
    start: int
    end: int
    source_ids: tuple[str,...]
    pointer: str


def document(text,source_ids,pointer,snapshot_id=None,run_id=None,entity_keys=()):
    identity=hashlib.sha256(json.dumps([source_ids,pointer,text,snapshot_id,run_id],ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
    return EvidenceDocument(id=identity,text=text,source_ids=tuple(source_ids),pointers=(pointer,),snapshot_id=snapshot_id,run_id=run_id,entity_keys=tuple(entity_keys))
