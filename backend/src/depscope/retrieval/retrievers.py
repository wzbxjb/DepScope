import asyncio
import re

from depscope.identity.coordinates import instance_key
from depscope.ingest.models import Contract
from depscope.investigation.models import validate_scope
from depscope.runtime.errors import DomainError

from .chunking import cap_context
from .documents import EvidenceChunk
from .rrf import rrf

METHODS=("lexical","vector","rrf","graph_rrf")


class RetrievalResult(Contract):
    chunks: tuple[EvidenceChunk,...]
    omitted_ids: tuple[str,...]
    character_count: int
    index_id: str
    method: str
    scope_snapshot_ids: tuple[str,...]


def expand_graph(seeds,documents,edges_by_snapshot,snapshot_ids):
    keys={}
    seed_ids={s.id for s in seeds}
    for seed in seeds:
        if seed.snapshot_id in snapshot_ids:keys.setdefault(seed.snapshot_id,set()).update(seed.entity_keys)
    neighbors={sid:set(values) for sid,values in keys.items()}
    for sid,edges in edges_by_snapshot.items():
        if sid not in keys:continue
        for a,b in edges:
            if a in keys[sid]:neighbors[sid].add(b)
            if b in keys[sid]:neighbors[sid].add(a)
    return tuple(d for d in sorted(documents,key=lambda d:d.id) if d.id not in seed_ids and d.snapshot_id in neighbors and set(d.entity_keys)&neighbors[d.snapshot_id])


class Retriever:
    def __init__(self,index_store,manifest,provider,snapshots,runs,comparisons=None):
        self.store,self.manifest,self.provider=index_store,manifest,provider
        self.snapshots,self.runs,self.comparisons=snapshots,runs,comparisons

    async def retrieve(self,question,scope,method):
        if method not in METHODS:raise DomainError("RETRIEVAL_METHOD","Unknown retrieval method")
        selected=await asyncio.to_thread(validate_scope,scope,self.snapshots,self.runs,self.comparisons)
        documents,chunks=await asyncio.gather(asyncio.to_thread(self.store.documents,self.manifest),asyncio.to_thread(self.store.chunks,self.manifest))
        global_sources=set()
        for run_id in scope.run_map.values():
            run=await asyncio.to_thread(self.runs.load,run_id)
            for rid in run.revision_ids:global_sources.add((await asyncio.to_thread(self.runs.revision,rid)).digest)
        allowed_docs={d.id:d for d in documents if (d.snapshot_id in scope.snapshot_ids and (d.run_id is None or d.run_id in scope.run_map.values()) and (d.comparison_id is None or d.comparison_id==scope.comparison_id)) or (d.snapshot_id is None and bool(set(d.source_ids)&global_sources))}
        by_id={c.evidence_id:c for c in chunks if c.document_id in allowed_docs}
        allowed=tuple(by_id)
        # ID lookup is shared across all four methods; ordinary package words remain ranked.
        identifiers=set(re.findall(r"(?:GHSA-[a-z0-9-]+|CVE-\d{4}-\d+|[0-9a-f]{64}|[\w.-]+@[\w.+!-]+)",question,flags=re.IGNORECASE))
        exact=tuple(sorted(c.evidence_id for c in by_id.values() if any(identifier.casefold()==entity.casefold() for identifier in identifiers for entity in allowed_docs[c.document_id].entity_keys)))
        lexical=vector=()
        if method in ("lexical","rrf","graph_rrf"):
            lexical=tuple(h.evidence_id for h in await asyncio.to_thread(self.store.lexical,self.manifest,question,allowed))
        if method in ("vector","rrf","graph_rrf"):
            batch=await self.provider.embed((question,))
            if (batch.model_id,batch.model_digest)!=(self.manifest.model_id,self.manifest.model_digest):raise DomainError("INDEX_MODEL_MISMATCH","Question embedding model differs from indexed corpus")
            vector=tuple(h.evidence_id for h in await asyncio.to_thread(self.store.search,self.manifest,batch.vectors[0],allowed))
        ranking=lexical if method=="lexical" else vector if method=="vector" else rrf((lexical,vector))
        ranking=tuple(dict.fromkeys(exact+ranking))
        if method=="graph_rrf" and ranking:
            seed_docs=tuple({by_id[e].document_id:allowed_docs[by_id[e].document_id] for e in ranking[:4]}.values())
            edges={s.snapshot_id:tuple((instance_key(s.snapshot_id,e.from_id),instance_key(s.snapshot_id,e.to_id)) for e in s.edges) for s in selected}
            expanded=expand_graph(seed_docs,tuple(allowed_docs.values()),edges,scope.snapshot_ids)
            extra=tuple(c.evidence_id for d in expanded for c in by_id.values() if c.document_id==d.id)
            # Same prefix, then bounded one-hop evidence, then remaining ranked context.
            ranking=tuple(dict.fromkeys(ranking[:4]+extra[:6]+ranking[4:]))
        selection=cap_context(tuple(by_id[id] for id in ranking))
        return RetrievalResult(**selection.model_dump(),index_id=self.manifest.id,method=method,scope_snapshot_ids=scope.snapshot_ids)

    async def search(self,question,scope,method):return (await self.retrieve(question,scope,method)).chunks
