import hashlib
import json
import re

from pydantic import Field

from depscope.ingest.models import Contract
from depscope.runtime.errors import DomainError

from .documents import EvidenceChunk, EvidenceDocument
from .embedding import validate_vector


class IndexManifest(Contract):
    id: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_id: str
    model_digest: str
    dimension: int = Field(gt=0, le=4096)
    chunking_version: str


class SearchHit(Contract):
    evidence_id: str
    index_id: str
    score: float


def index_names(id):
    if not re.fullmatch(r"[0-9a-f]{64}", id):
        raise DomainError("INVALID_INDEX", "Index identity must be a SHA-256 hex string")
    return "Evidence_" + id, "vec_" + id, "text_" + id


def make_manifest(chunks, batch, version):
    corpus = hashlib.sha256(
        json.dumps(
            sorted((c.model_dump(mode="json") for c in chunks), key=lambda c: c["evidence_id"]),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    config = {
        "corpus_digest": corpus,
        "model_id": batch.model_id,
        "model_digest": batch.model_digest,
        "dimension": len(batch.vectors[0]),
        "chunking_version": version,
    }
    id = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return IndexManifest(id=id, **config)


class IndexStore:
    def __init__(self, driver):
        self.driver = driver

    def write(self, manifest, evidence, vectors, documents=()):
        label, vec, text = index_names(manifest.id)
        if len(evidence) != len(vectors) or len({c.evidence_id for c in evidence}) != len(evidence):
            raise DomainError(
                "INDEX_CONTENT_INVALID", "Index requires one vector per unique evidence ID"
            )
        vectors = tuple(validate_vector(v, manifest.dimension) for v in vectors)
        corpus_signature = hashlib.sha256(
            json.dumps(
                [[c.model_dump(mode="json"), v] for c, v in zip(evidence, vectors, strict=True)],
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()

        def claim(tx):
            row = tx.run(
                "MERGE (m:IndexManifest {id:$id}) ON CREATE SET m.payload=$payload,m.signature=$signature,m.status='building' RETURN m.payload AS payload,m.signature AS signature",
                id=manifest.id,
                payload=manifest.model_dump_json(),
                signature=corpus_signature,
            ).single()
            if row["payload"] != manifest.model_dump_json() or row["signature"] != corpus_signature:
                raise DomainError(
                    "INDEX_IMMUTABLE", "Index manifest and vectors cannot be modified in place"
                )

        def bounded(rows):
            batch = []
            size = 0
            for row in rows:
                amount = len(json.dumps(row, ensure_ascii=False).encode())
                if batch and (len(batch) >= 128 or size + amount > 1_000_000):
                    yield tuple(batch)
                    batch, size = [], 0
                batch.append(row)
                size += amount
            if batch:
                yield tuple(batch)

        def persist_documents(tx, rows):
            for document in rows:
                row = tx.run(
                    "MERGE (d:EvidenceDocument {id:$id}) ON CREATE SET d.payload=$payload RETURN d.payload AS payload",
                    **document,
                ).single()
                if row["payload"] != document["payload"]:
                    raise DomainError(
                        "EVIDENCE_IMMUTABLE", "Original evidence document cannot change"
                    )

        def persist_copies(tx, rows):
            tx.run(
                f"UNWIND $rows AS r MERGE (c:EvidenceCopy:{label} {{copy_key:r.key}}) ON CREATE SET c.index_id=$id,c.evidence_id=r.evidence,c.document_id=r.document,c.payload=r.payload,c.text=r.text,c.embedding=r.vector WITH c,r MATCH (d:EvidenceDocument {{id:r.document}}) MERGE (c)-[:CHUNK_OF]->(d)",
                rows=list(rows),
                id=manifest.id,
            ).consume()

        def verify_counts(tx):
            count = tx.run(
                f"MATCH (c:{label})-[:CHUNK_OF]->(:EvidenceDocument) RETURN count(c) AS n"
            ).single()["n"]
            if count != len(evidence):
                raise DomainError(
                    "INDEX_CONTENT_INVALID", "Index counts do not match its evidence collection"
                )

        with self.driver.session() as session:
            session.run(
                "CREATE CONSTRAINT evidence_document_identity IF NOT EXISTS FOR (d:EvidenceDocument) REQUIRE d.id IS UNIQUE"
            ).consume()
            session.run(
                "CREATE CONSTRAINT evidence_copy_identity IF NOT EXISTS FOR (c:EvidenceCopy) REQUIRE c.copy_key IS UNIQUE"
            ).consume()
            session.run(
                "CREATE CONSTRAINT index_manifest_identity IF NOT EXISTS FOR (m:IndexManifest) REQUIRE m.id IS UNIQUE"
            ).consume()
            session.execute_write(claim)
            for batch in bounded({"id": d.id, "payload": d.model_dump_json()} for d in documents):
                session.execute_write(persist_documents, batch)
            for batch in bounded(
                {
                    "key": manifest.id + ":" + c.evidence_id,
                    "evidence": c.evidence_id,
                    "document": c.document_id,
                    "payload": c.model_dump_json(),
                    "text": c.text,
                    "vector": list(v),
                }
                for c, v in zip(evidence, vectors, strict=True)
            ):
                session.execute_write(persist_copies, batch)
            session.execute_write(verify_counts)
            session.run(
                f"CREATE VECTOR INDEX {vec} IF NOT EXISTS FOR (c:{label}) ON (c.embedding) OPTIONS {{indexConfig: {{`vector.dimensions`: $dimension, `vector.similarity_function`: 'cosine'}}}}",
                dimension=manifest.dimension,
            ).consume()
            session.run(
                f"CREATE FULLTEXT INDEX {text} IF NOT EXISTS FOR (c:{label}) ON EACH [c.text]"
            ).consume()
            session.run("CALL db.awaitIndex($name,60)", name=vec).consume()
            session.run("CALL db.awaitIndex($name,60)", name=text).consume()
            session.run(
                "MATCH (m:IndexManifest {id:$id}) SET m.status='ready'", id=manifest.id
            ).consume()

    def manifest(self, id):
        index_names(id)
        with self.driver.session() as session:
            row = session.run(
                "MATCH (m:IndexManifest {id:$id,status:'ready'}) RETURN m.payload AS payload", id=id
            ).single()
        if not row:
            raise DomainError("INDEX_NOT_READY", "Evidence index is unavailable")
        return IndexManifest.model_validate_json(row["payload"])

    def _checked(self, manifest):
        if self.manifest(manifest.id) != manifest:
            raise DomainError(
                "INDEX_MODEL_MISMATCH", "Query manifest does not match the immutable index"
            )

    def chunks(self, manifest):
        self._checked(manifest)
        with self.driver.session() as session:
            rows = tuple(
                session.run(
                    "MATCH (c:EvidenceCopy {index_id:$id}) RETURN c.payload AS payload ORDER BY c.evidence_id",
                    id=manifest.id,
                )
            )
        return tuple(EvidenceChunk.model_validate_json(r["payload"]) for r in rows)

    def documents(self, manifest):
        self._checked(manifest)
        with self.driver.session() as session:
            rows = tuple(
                session.run(
                    "MATCH (c:EvidenceCopy {index_id:$id})-[:CHUNK_OF]->(d) RETURN DISTINCT d.id AS id,d.payload AS payload ORDER BY id",
                    id=manifest.id,
                )
            )
        return tuple(EvidenceDocument.model_validate_json(r["payload"]) for r in rows)

    def search(self, manifest, vector, allowed_ids=None, limit=50):
        self._checked(manifest)
        _, vec, _ = index_names(manifest.id)
        vector = validate_vector(vector, manifest.dimension)
        with self.driver.session() as session:
            n = session.run(
                "MATCH (c:EvidenceCopy {index_id:$id}) RETURN count(c) AS n", id=manifest.id
            ).single()["n"]
            if not n:
                return ()
            rows = tuple(
                session.run(
                    "CALL db.index.vector.queryNodes($index,$count,$vector) YIELD node,score WHERE node.index_id=$id AND ($allowed IS NULL OR node.evidence_id IN $allowed) RETURN node.evidence_id AS evidence,score ORDER BY score DESC,evidence LIMIT $limit",
                    index=vec,
                    count=n,
                    vector=list(vector),
                    id=manifest.id,
                    allowed=list(allowed_ids) if allowed_ids is not None else None,
                    limit=limit,
                )
            )
        return tuple(
            SearchHit(evidence_id=r["evidence"], index_id=manifest.id, score=float(r["score"]))
            for r in rows
        )

    def lexical(self, manifest, question, allowed_ids=None, limit=50):
        self._checked(manifest)
        _, _, text = index_names(manifest.id)
        tokens = re.findall(r"[\w]+", question, flags=re.UNICODE)[:64]
        if not tokens:
            return ()
        # Literal quoted tokens prevent user strings becoming Lucene operators.
        query = " OR ".join('"' + token + '"' for token in tokens)
        with self.driver.session() as session:
            rows = tuple(
                session.run(
                    "CALL db.index.fulltext.queryNodes($index,$literal_query) YIELD node,score WHERE node.index_id=$id AND ($allowed IS NULL OR node.evidence_id IN $allowed) RETURN node.evidence_id AS evidence,score ORDER BY score DESC,evidence LIMIT $limit",
                    index=text,
                    literal_query=query,
                    id=manifest.id,
                    allowed=list(allowed_ids) if allowed_ids is not None else None,
                    limit=limit,
                )
            )
        return tuple(
            SearchHit(evidence_id=r["evidence"], index_id=manifest.id, score=float(r["score"]))
            for r in rows
        )

    def delete(self, id):
        label, vec, text = index_names(id)
        with self.driver.session() as session:
            session.run(f"DROP INDEX {vec} IF EXISTS").consume()
            session.run(f"DROP INDEX {text} IF EXISTS").consume()
            session.run(f"MATCH (c:{label}) DETACH DELETE c").consume()
            session.run("MATCH (m:IndexManifest {id:$id}) DETACH DELETE m", id=id).consume()
