import math
import pytest
from depscope.retrieval.documents import EvidenceDocument
from depscope.retrieval.chunking import chunk_document, evidence_key, cap_context
from depscope.retrieval.embedding import OllamaEmbedding, validate_vector
from depscope.retrieval.rrf import rrf
from depscope.retrieval.retrievers import expand_graph
from depscope.runtime.errors import DomainError


def doc(text="x", sid="a"*64, entities=()):
    return EvidenceDocument(id="doc",text=text,source_ids=("c"*64,),pointers=("/details",),snapshot_id=sid,run_id=None,entity_keys=entities)


def test_unicode_offsets_overlap_and_stable_origin():
    text="😀中"*1100
    chunks=chunk_document(doc(text))
    assert [(c.start,c.end) for c in chunks]==[(0,2000),(1800,2200)]
    assert chunks[1].text==text[1800:2200]
    assert chunks[0].evidence_id==evidence_key("c"*64,"/details",0,2000)
    assert chunk_document(doc(text))[0].evidence_id==chunks[0].evidence_id


def test_field_boundary_and_context_cap_are_reported():
    chunks=tuple(chunk_document(doc("a"*2000).model_copy(update={"id":str(i),"source_ids":(f"{i:064x}",)}))[0] for i in range(12))
    result=cap_context(chunks)
    assert len(result.chunks)==6 and result.character_count==12000
    assert result.omitted_ids==tuple(c.evidence_id for c in chunks[6:])
    assert len(cap_context(tuple(c.model_copy(update={"text":"short"}) for c in chunks)).chunks)==10
    field=chunk_document(doc("a"*1850+"\n"+"b"*300))
    assert field[0].end==1851 and field[1].start==1651


@pytest.mark.parametrize("vector,dimension",[([0.,0.],2),([math.nan,1.],2),([math.inf,1.],2),([1.],2)])
def test_bad_vectors_fail_closed(vector,dimension):
    with pytest.raises(DomainError): validate_vector(vector,dimension)


def test_rrf_deduplicates_with_deterministic_ties():
    assert rrf((("b","a","a"),("a","b")))==("a","b")


def test_graph_expansion_cannot_cross_snapshots():
    seed=doc("seed",entities=("root",))
    neighbor=doc("neighbor",entities=("child",)).model_copy(update={"id":"neighbor"})
    foreign=doc("foreign","b"*64,("child",)).model_copy(update={"id":"foreign"})
    found=expand_graph((seed,), (seed,neighbor,foreign), {"a"*64:(("root","child"),)}, ("a"*64,))
    assert tuple(d.id for d in found)==("neighbor",)


async def test_ollama_contract_records_digest_and_rejects_silent_truncation(respx_mock):
    import httpx
    respx_mock.get("http://embedding.test/api/tags").respond(json={"models":[{"name":"test","digest":"1"*64}]})
    route=respx_mock.post("http://embedding.test/api/embed").respond(json={"model":"test","embeddings":[[1.,0.],[0.,1.]],"prompt_eval_count":2})
    async with httpx.AsyncClient() as http:
        result=await OllamaEmbedding("http://embedding.test","test",http).embed(("a","b"))
    assert result.model_digest=="1"*64 and len(result.vectors)==2
    import json
    assert json.loads(route.calls[0].request.content)["truncate"] is False
    assert result.usage=={"prompt_eval_count":2}


async def test_same_exact_locator_all_methods_and_foreign_scope_excluded(snapshot_factory):
    from types import SimpleNamespace
    from depscope.investigation.models import InvestigationScope
    from depscope.retrieval.retrievers import Retriever,METHODS
    from depscope.retrieval.embedding import EmbeddingBatch
    snapshot=snapshot_factory("p",("root",),(),"root")
    run=SimpleNamespace(snapshot_id=snapshot.snapshot_id,revision_ids=())
    scope=InvestigationScope(project_ids=("p",),snapshot_ids=(snapshot.snapshot_id,),run_map={snapshot.snapshot_id:"run"})
    local=doc("scoped fact",snapshot.snapshot_id,("pkg@1.0",)).model_copy(update={"id":"local"})
    foreign=doc("foreign fact","b"*64,("pkg@1.0",)).model_copy(update={"id":"foreign","source_ids":("d"*64,)})
    chunks=chunk_document(local)+chunk_document(foreign)
    class Store:
        def documents(self,m):return (local,foreign)
        def chunks(self,m):return chunks
        def lexical(self,*args):return ()
        def search(self,*args):return ()
    class Provider:
        async def embed(self,texts):return EmbeddingBatch(vectors=((1.,0.),),model_id="test",model_digest="digest",usage=None)
    manifest=SimpleNamespace(id="a"*64,model_id="test",model_digest="digest")
    retriever=Retriever(Store(),manifest,Provider(),SimpleNamespace(load=lambda id:snapshot),SimpleNamespace(load=lambda id:run))
    for method in METHODS:
        result=await retriever.retrieve("What about pkg@1.0?",scope,method)
        assert tuple(c.document_id for c in result.chunks)==("local",)
        assert result.character_count==len(local.text)
    wrong=scope.model_copy(update={"project_ids":("other",)})
    with pytest.raises(DomainError):await retriever.search("question",wrong,"lexical")
