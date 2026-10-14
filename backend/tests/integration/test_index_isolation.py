import uuid
import pytest
from depscope.retrieval.documents import EvidenceDocument
from depscope.retrieval.chunking import chunk_document
from depscope.retrieval.indexes import IndexManifest, IndexStore
from depscope.runtime.errors import DomainError


@pytest.fixture
def index_store(driver):
    store = IndexStore(driver)
    ids = []
    store.test_ids = ids
    yield store
    for id in ids:
        store.delete(id)


def test_equal_dimensions_do_not_mix_model_indexes(index_store):
    import hashlib

    seed = uuid.uuid4().hex
    manifests = [
        IndexManifest(
            id=hashlib.sha256((seed + n).encode()).hexdigest(),
            corpus_digest="c" * 64,
            model_id=n,
            model_digest=n * 64,
            dimension=3,
            chunking_version="1",
        )
        for n in ("1", "2")
    ]
    document = EvidenceDocument(
        id=seed,
        text="requests dependency evidence",
        source_ids=("c" * 64,),
        pointers=("/details",),
        snapshot_id=None,
        run_id=None,
        entity_keys=("GHSA-test",),
    )
    chunks = chunk_document(document)
    for m, vec in zip(manifests, ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])):
        index_store.test_ids.append(m.id)
        index_store.write(m, chunks, [vec], (document,))
    hits = index_store.search(manifests[1], [0.0, 1.0, 0.0])
    assert hits and all(h.index_id == manifests[1].id for h in hits)
    assert index_store.lexical(manifests[1], "requests")[0].evidence_id == chunks[0].evidence_id
    assert index_store.documents(manifests[1])[0].text == document.text
    with pytest.raises(DomainError):
        index_store.write(
            manifests[1].model_copy(update={"model_id": "changed"}),
            chunks,
            [[0.0, 1.0, 0.0]],
            (document,),
        )


def test_missing_evidence_document_cannot_publish(index_store):
    import hashlib

    identity = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    manifest = IndexManifest(
        id=identity,
        corpus_digest="c" * 64,
        model_id="test",
        model_digest="d" * 64,
        dimension=2,
        chunking_version="1",
    )
    document = EvidenceDocument(
        id=uuid.uuid4().hex,
        text="orphan",
        source_ids=("e" * 64,),
        pointers=("/details",),
        snapshot_id=None,
        run_id=None,
        entity_keys=(),
    )
    index_store.test_ids.append(identity)
    with pytest.raises(DomainError):
        index_store.write(manifest, chunk_document(document), [[1.0, 0.0]])
