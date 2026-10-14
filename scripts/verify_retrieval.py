"""Actual local embedding + Neo4j retrieval proof; never calls a paid model."""
import asyncio
import json
import time
from pathlib import Path
from depscope.api.services import build_services
from depscope.runtime.config import load_settings
from depscope.runtime.pagination import now
from depscope.investigation.models import InvestigationScope
from depscope.graph.evidence import EvidenceBuilder,build_index
from depscope.retrieval.embedding import OllamaEmbedding
from depscope.retrieval.indexes import IndexStore
from depscope.retrieval.retrievers import Retriever,METHODS


async def main():
    root=Path(__file__).resolve().parents[1]
    sample=json.loads((root/"artifacts/verification/public-demo.json").read_text())
    settings=load_settings()
    services=build_services(settings)
    try:
        started=time.perf_counter()
        scope=InvestigationScope(project_ids=(sample["project_id"],),snapshot_ids=(sample["snapshot_id"],),run_map={sample["snapshot_id"]:sample["run_id"]})
        provider=OllamaEmbedding(settings.embedding_url,settings.embedding_model)
        store=IndexStore(services.driver)
        docs=EvidenceBuilder(services.snapshots,services.runs,services.comparisons,services.records).build(scope)
        print("Indexing actual archived public evidence:",len(docs),"documents",flush=True)
        manifest=await build_index(docs,provider,store)
        retriever=Retriever(store,manifest,provider,services.snapshots,services.runs,services.comparisons)
        results={}
        for method in METHODS:
            result=await retriever.retrieve("Explain GHSA-3hjh-jh2h-vrg6 and its recorded dependency evidence",scope,method)
            assert result.chunks and len(result.chunks)<=10 and result.character_count<=12000
            results[method]=result.model_dump(mode="json")
            print(method,len(result.chunks),result.character_count,flush=True)
        artifact={"observed_at":now(),"scope":scope.model_dump(mode="json"),"manifest":manifest.model_dump(mode="json"),"documents":len(docs),"indexed_chunks":len(store.chunks(manifest)),"elapsed_seconds":time.perf_counter()-started,"results":results,"references":["https://docs.ollama.com/api/embed","https://neo4j.com/docs/cypher-manual/5/indexes/semantic-indexes/vector-indexes/","https://neo4j.com/docs/cypher-manual/5/indexes/semantic-indexes/full-text-indexes/"]}
        (root/"artifacts/verification/retrieval.json").write_text(json.dumps(artifact,indent=2,ensure_ascii=False)+"\n")
        print(json.dumps({k:v for k,v in artifact.items() if k not in ("results","references","scope")}))
    finally:services.close()


if __name__=="__main__":asyncio.run(main())
