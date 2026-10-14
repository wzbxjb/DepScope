import json

from depscope.analysis.metrics import completeness
from depscope.identity.coordinates import instance_key
from depscope.investigation.models import validate_scope
from depscope.retrieval.chunking import CHUNKING_VERSION, chunk_document
from depscope.retrieval.documents import document
from depscope.retrieval.indexes import make_manifest
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now


class EvidenceBuilder:
    def __init__(self, snapshots, runs, comparisons, records):
        self.snapshots, self.runs, self.comparisons, self.records = (
            snapshots,
            runs,
            comparisons,
            records,
        )

    def receipt(self, fact, source_ids, snapshot_id=None, run_id=None, entities=()):
        # A deterministic derived receipt preserves context that raw public bytes do not carry.
        text = json.dumps(fact, ensure_ascii=False, sort_keys=True)
        raw = json.dumps(
            {"text": text, "fact": fact, "upstream_source_ids": list(source_ids)},
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
        source = self.records.put(raw, "derived://depscope/evidence-v1", now())
        return document(
            text, (source.digest,) + tuple(source_ids), "/text", snapshot_id, run_id, entities
        )

    def comparison_receipts(self, comparison, source_ids):
        # Each scalar remains an intact, independently checked receipt after fixed-size chunking.
        if len(source_ids) > 3:
            lineage = self.records.put(
                json.dumps(
                    {
                        "comparison_id": comparison.id,
                        "run_ids": list(comparison.run_ids),
                        "upstream_source_ids": list(source_ids),
                    },
                    sort_keys=True,
                ).encode(),
                "derived://depscope/comparison-lineage-v1",
                now(),
            )
            source_ids = tuple(source_ids[:2]) + (lineage.digest,)
        values = comparison.model_dump(mode="json")
        facts = [values] + [
            {"id": comparison.id, metric: values[metric]}
            for metric in (
                "level",
                "removed_known_matches",
                "added_known_matches",
                "remaining_known_matches",
                "unknown",
            )
            if values.get(metric) is not None
        ]
        return tuple(
            self.receipt(
                {"kind": "comparison", "comparison": fact},
                source_ids,
                comparison.baseline_id,
                None,
                (comparison.id,),
            ).model_copy(update={"comparison_id": comparison.id})
            for fact in facts
        )

    def build(self, scope):
        snapshots = validate_scope(scope, self.snapshots, self.runs, self.comparisons)
        documents = []
        revisions = set()
        for snapshot in snapshots:
            sid = snapshot.snapshot_id
            run = self.runs.load(scope.run_map[sid])
            revisions.update(run.revision_ids)
            source = (snapshot.source.digest,)
            by_id = {c.local_id: c for c in snapshot.components}
            documents.append(
                self.receipt(
                    {
                        "kind": "snapshot_counts",
                        "snapshot_id": sid,
                        "project_id": snapshot.project_id,
                        "run_id": run.id,
                        "instances": len(snapshot.components),
                        "unique_package_versions": len(
                            {c.coordinate.key for c in snapshot.components if c.coordinate}
                        ),
                        "recorded_edges": len(snapshot.edges),
                        "root_id": snapshot.root_id,
                        "completeness": completeness(snapshot).model_dump(mode="json"),
                        "source_observed_at": snapshot.source.observed_at,
                        "query_observed_at": run.observed_at,
                        "query_coverage": run.coverage,
                    },
                    source,
                    sid,
                    run.id,
                    (sid,),
                )
            )
            for component in snapshot.components:
                inst = instance_key(sid, component.local_id)
                entities = (inst, component.name) + (
                    (component.coordinate.name + "@" + component.coordinate.raw_version,)
                    if component.coordinate
                    else ()
                )
                documents.append(
                    self.receipt(
                        {
                            "kind": "component",
                            "snapshot_id": sid,
                            "project_id": snapshot.project_id,
                            "instance_id": inst,
                            "component": component.model_dump(mode="json"),
                            "upstream_pointer": component.pointer,
                        },
                        source,
                        sid,
                        None,
                        entities,
                    )
                )
            for edge in snapshot.edges:
                origin, target = by_id[edge.from_id], by_id[edge.to_id]
                entities = (
                    instance_key(sid, edge.from_id),
                    instance_key(sid, edge.to_id),
                    origin.name,
                    target.name,
                )
                documents.append(
                    self.receipt(
                        {
                            "kind": "dependency_edge",
                            "snapshot_id": sid,
                            "project_id": snapshot.project_id,
                            "from_instance": entities[0],
                            "to_instance": entities[1],
                            "from_name": origin.name,
                            "to_name": target.name,
                            "requirement": edge.requirement,
                            "upstream_pointer": edge.pointer,
                        },
                        source,
                        sid,
                        None,
                        entities,
                    )
                )
            for query in run.queries:
                documents.append(
                    self.receipt(
                        {
                            "kind": "package_query",
                            "snapshot_id": sid,
                            "run_id": run.id,
                            "query": query.model_dump(mode="json"),
                            "observed_at": run.observed_at,
                        },
                        tuple(ref.digest for ref in query.source_refs) or source,
                        sid,
                        run.id,
                        (
                            query.coordinate.name,
                            query.coordinate.name + "@" + query.coordinate.raw_version,
                        )
                        + query.record_ids,
                    )
                )
            for finding in run.findings:
                documents.append(
                    self.receipt(
                        {
                            "kind": "finding",
                            "snapshot_id": sid,
                            "run_id": run.id,
                            "finding": finding.model_dump(mode="json"),
                            "interpretation": "Known advisory match; exploitability has not been established.",
                        },
                        tuple(self.runs.revision(r).digest for r in finding.revision_ids),
                        sid,
                        run.id,
                        (finding.id, finding.instance_id)
                        + tuple(self.runs.revision(r).id for r in finding.revision_ids),
                    )
                )
        for rid in sorted(revisions):
            revision = self.runs.revision(rid)
            raw = json.loads(self.records.get(revision.digest))
            for field in (
                "id",
                "aliases",
                "summary",
                "details",
                "affected",
                "withdrawn",
                "modified",
            ):
                if field not in raw:
                    continue
                value = raw[field]
                text = (
                    value
                    if isinstance(value, str)
                    else json.dumps(value, ensure_ascii=False, sort_keys=True)
                )
                documents.append(
                    document(
                        text,
                        (revision.digest,),
                        "/" + field,
                        None,
                        None,
                        (revision.id,) + revision.aliases,
                    )
                )
        if scope.comparison_id:
            comparison = self.comparisons.load(scope.comparison_id)
            baseline = self.snapshots.load(comparison.baseline_id)
            candidate = self.snapshots.load(comparison.candidate_id)
            sources = [baseline.source.digest, candidate.source.digest]
            for run_id in comparison.run_ids:
                run = self.runs.load(run_id)
                sources.extend(ref.digest for query in run.queries for ref in query.source_refs)
                sources.extend(self.runs.revision(rid).digest for rid in run.revision_ids)
            documents.extend(self.comparison_receipts(comparison, tuple(dict.fromkeys(sources))))
        return tuple({d.id: d for d in documents}.values())


async def build_index(documents, provider, store):
    chunks = tuple(
        {
            c.evidence_id: c
            for d in sorted(documents, key=lambda d: d.id)
            for c in chunk_document(d)
        }.values()
    )
    if not chunks:
        raise DomainError("EVIDENCE_EMPTY", "No evidence is available for indexing")
    probe = await provider.embed((chunks[0].text,))
    manifest = make_manifest(chunks, probe, CHUNKING_VERSION)
    import asyncio

    try:
        existing = await asyncio.to_thread(store.manifest, manifest.id)
        if existing != manifest:
            raise DomainError(
                "INDEX_MODEL_MISMATCH", "Persisted index does not match current evidence and model"
            )
        return existing
    except DomainError as exc:
        if exc.code != "INDEX_NOT_READY":
            raise
    batches = []
    vectors = []
    for offset in range(0, len(chunks), 32):
        batch = await provider.embed(tuple(c.text for c in chunks[offset : offset + 32]))
        if batches and (batch.model_id, batch.model_digest, len(batch.vectors[0])) != (
            batches[0].model_id,
            batches[0].model_digest,
            len(batches[0].vectors[0]),
        ):
            raise DomainError("EMBEDDING_MODEL_CHANGED", "Embedding model changed within corpus")
        batches.append(batch)
        vectors.extend(batch.vectors)
    manifest = make_manifest(chunks, batches[0], CHUNKING_VERSION)
    import asyncio

    await asyncio.to_thread(store.write, manifest, chunks, vectors, documents)
    return manifest
