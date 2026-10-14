import hashlib
import json

from depscope.ingest.models import Contract

from .documents import EvidenceChunk

CHUNKING_VERSION="unicode-2000-overlap-200-field-v1"


def evidence_key(digest,pointer,start,end):
    return hashlib.sha256(json.dumps([digest,pointer,start,end],separators=(",",":")).encode()).hexdigest()


def chunk_document(document):
    if len(document.pointers)!=1:
        raise ValueError("Each evidence document must contain exactly one source field")
    result=[]
    start=0
    while start<len(document.text):
        end=min(start+2000,len(document.text))
        if end<len(document.text):
            boundary=document.text.rfind("\n",start+1800,end)
            if boundary>=0:end=boundary+1
        result.append(EvidenceChunk(evidence_id=evidence_key(document.source_ids[0],document.pointers[0],start,end),document_id=document.id,text=document.text[start:end],start=start,end=end,source_ids=document.source_ids,pointer=document.pointers[0]))
        if end==len(document.text):break
        start=end-200
    return tuple(result)


class ContextSelection(Contract):
    chunks: tuple[EvidenceChunk,...]
    omitted_ids: tuple[str,...]
    character_count: int


def cap_context(chunks):
    unique={c.evidence_id:c for c in chunks}
    selected=[]
    omitted=[]
    count=0
    stopped=False
    for chunk in unique.values():
        if stopped or len(selected)==10 or count+len(chunk.text)>12000:
            omitted.append(chunk.evidence_id)
            stopped=True
        else:
            selected.append(chunk)
            count+=len(chunk.text)
    return ContextSelection(chunks=tuple(selected),omitted_ids=tuple(omitted),character_count=count)
