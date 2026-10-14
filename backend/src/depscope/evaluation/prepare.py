"""Build the full frozen evidence corpus and resumable local embedding index."""

import asyncio
import json
from pathlib import Path

from depscope.api.services import build_services
from depscope.evaluation.benchmark import build_benchmark
from depscope.evaluation.corpus import CorpusManifest
from depscope.evaluation.freeze import canonical, digest
from depscope.graph.evidence import EvidenceBuilder
from depscope.investigation.models import InvestigationScope
from depscope.retrieval.chunking import CHUNKING_VERSION, chunk_document
from depscope.retrieval.embedding import EmbeddingBatch, OllamaEmbedding
from depscope.retrieval.indexes import IndexStore, make_manifest
from depscope.runtime.config import PROJECT_ROOT, load_settings
from depscope.runtime.errors import DomainError


def bind_required_evidence(questions, documents, records):
    locators = {}
    comparisons = {}
    queries = {}
    for document in documents:
        try:
            receipt = json.loads(records.get(document.source_ids[0]))
            fact = receipt["fact"]
        except (KeyError, ValueError):
            continue
        chunks = chunk_document(document)
        if len(chunks) != 1:
            continue
        id = chunks[0].evidence_id
        if fact.get("kind") in ("component", "dependency_edge"):
            pointer = fact["upstream_pointer"]
            for source in document.source_ids[1:]:
                locators[(source, pointer)] = id
        if fact.get("kind") == "package_query":
            query = fact["query"]["coordinate"]
            queries[(fact["snapshot_id"], fact["run_id"], query["name"], query["raw_version"])] = id
        if fact.get("kind") == "comparison" and len(fact["comparison"]) == 2:
            comp = fact["comparison"]
            metric = next(k for k in comp if k != "id")
            comparisons[(comp["id"], metric)] = id
    result = []
    for question in questions:
        required = []
        if question.kind != "missing":
            for locator in question.reference_locators:
                id = (
                    queries.get(tuple(locator["query_key"]))
                    if "query_key" in locator
                    else (
                        comparisons.get((locator["comparison_id"], locator["metric"]))
                        if "comparison_id" in locator
                        else locators.get((locator["source_digest"], locator["pointer"]))
                    )
                )
                if not id:
                    raise DomainError(
                        "GOLD_EVIDENCE_MISSING",
                        "A raw-reference label cannot be bound to an intact source receipt",
                    )
                required.append(id)
        result.append(
            question.model_copy(update={"required_evidence": tuple(sorted(set(required)))})
        )
    return tuple(result)


async def prepare(container, settings, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = CorpusManifest.model_validate_json(
        (PROJECT_ROOT / "artifacts/corpus/manifest.json").read_bytes()
    )
    questions = build_benchmark(manifest)
    builder = EvidenceBuilder(
        container.snapshots, container.runs, container.comparisons, container.records
    )
    documents = {}
    for index, case in enumerate(manifest.cases):
        scope = InvestigationScope(
            project_ids=(case.project_id,),
            snapshot_ids=(case.snapshot_id,),
            run_map={case.snapshot_id: case.run_id},
        )
        docs = await asyncio.to_thread(builder.build, scope)
        documents.update((d.id, d) for d in docs)
        print(
            json.dumps({"stage": "evidence", "cases_done": index + 1, "documents": len(documents)}),
            flush=True,
        )
    for id in manifest.comparison_ids:
        comparison = container.comparisons.load(id)
        sources = []
        for sid, runid in zip(
            (comparison.baseline_id, comparison.candidate_id), comparison.run_ids, strict=True
        ):
            sources.append(container.snapshots.load(sid).source.digest)
            run = container.runs.load(runid)
            sources.extend(ref.digest for query in run.queries for ref in query.source_refs)
            sources.extend(container.runs.revision(rid).digest for rid in run.revision_ids)
        docs = builder.comparison_receipts(comparison, tuple(dict.fromkeys(sources)))
        documents.update((d.id, d) for d in docs)
    docs = tuple(documents[id] for id in sorted(documents))
    questions = bind_required_evidence(questions, docs, container.records)
    chunks = tuple({c.evidence_id: c for d in docs for c in chunk_document(d)}.values())
    (output / "documents.json").write_bytes(canonical([d.model_dump(mode="json") for d in docs]))
    (output / "chunks.json").write_bytes(canonical([c.model_dump(mode="json") for c in chunks]))
    (output / "questions-prepared.json").write_bytes(
        canonical([q.model_dump(mode="json") for q in questions])
    )
    provider = OllamaEmbedding(settings.embedding_url, settings.embedding_model)
    probe = await provider.embed((chunks[0].text,))
    index = make_manifest(chunks, probe, CHUNKING_VERSION)
    store = IndexStore(container.driver)
    try:
        existing = store.manifest(index.id)
        if existing != index:
            raise DomainError("INDEX_MODEL_MISMATCH", "Existing frozen corpus index differs")
        (output / "index.json").write_bytes(canonical(index.model_dump(mode="json")))
        print(
            json.dumps(
                {
                    "stage": "index_ready",
                    "index_id": index.id,
                    "chunks": len(chunks),
                    "documents": len(docs),
                    "reused": True,
                }
            ),
            flush=True,
        )
        return questions, index
    except DomainError as error:
        if error.code != "INDEX_NOT_READY":
            raise
    cache = settings.data_root / "embedding-checkpoints" / index.model_digest
    cache.mkdir(parents=True, exist_ok=True)
    vectors = []
    for offset in range(0, len(chunks), 32):
        texts = tuple(c.text for c in chunks[offset : offset + 32])
        signature = digest(canonical(texts))
        path = cache / (signature + ".json")
        if path.exists():
            batch = EmbeddingBatch.model_validate_json(path.read_bytes())
        else:
            batch = await provider.embed(texts)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(batch.model_dump_json().encode())
            temporary.replace(path)
        if (batch.model_id, batch.model_digest, len(batch.vectors[0])) != (
            index.model_id,
            index.model_digest,
            index.dimension,
        ) or len(batch.vectors) != len(texts):
            raise DomainError("INDEX_MODEL_MISMATCH", "Embedding checkpoint identity differs")
        vectors.extend(batch.vectors)
        print(
            json.dumps(
                {
                    "stage": "embedding",
                    "completed_chunks": len(vectors),
                    "total_chunks": len(chunks),
                }
            ),
            flush=True,
        )
    after = await provider.embed((chunks[0].text,))
    if after.model_digest != index.model_digest:
        raise DomainError(
            "EMBEDDING_MODEL_CHANGED", "Embedding model changed while preparing the corpus"
        )
    await asyncio.to_thread(store.write, index, chunks, vectors, docs)
    (output / "index.json").write_bytes(canonical(index.model_dump(mode="json")))
    print(
        json.dumps(
            {
                "stage": "index_ready",
                "index_id": index.id,
                "chunks": len(chunks),
                "documents": len(docs),
                "reused": False,
            }
        ),
        flush=True,
    )
    return questions, index


if __name__ == "__main__":
    settings = load_settings()
    container = build_services(settings)
    try:
        asyncio.run(prepare(container, settings, PROJECT_ROOT / "artifacts/benchmark/v1"))
    finally:
        container.close()
