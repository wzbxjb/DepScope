import hashlib
import json

from depscope.retrieval.chunking import chunk_document
from depscope.retrieval.documents import document
from depscope.retrieval.indexes import IndexManifest, IndexStore


class Rows:
    def __init__(self, row=None):
        self.row = row or {}

    def single(self):
        return self.row

    def consume(self):
        return None


class BoundedTransactionDriver:
    """A constrained DB boundary; production failure was the real 358.4 MiB Neo4j limit."""

    def __init__(self):
        self.copies = set()
        self.peak = 0
        self.transactions = 0

    def session(self):
        return Session(self)


class Session:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def run(self, query, **kwargs):
        if "MERGE (m:IndexManifest" in query:
            return Rows({"payload": kwargs["payload"], "signature": kwargs["signature"]})
        if "MERGE (d:EvidenceDocument" in query:
            return Rows({"payload": kwargs["payload"]})
        if "UNWIND $rows" in query:
            self.driver.copies.update(row["key"] for row in kwargs["rows"])
        if "RETURN count(c)" in query:
            return Rows({"n": len(self.driver.copies)})
        return Rows()

    def execute_write(self, operation, *args):
        self.driver.transactions += 1
        return operation(Transaction(self), *args)


class Transaction:
    def __init__(self, session):
        self.session = session
        self.bytes = 0

    def run(self, query, **kwargs):
        self.bytes += len(json.dumps(kwargs).encode())
        self.session.driver.peak = max(self.session.driver.peak, self.bytes)
        if self.bytes > 2_000_000:
            raise RuntimeError("bounded transaction memory exceeded")
        return self.session.run(query, **kwargs)


def test_large_index_uses_bounded_transactions_and_checks_final_counts():
    docs = tuple(
        document(
            "Recorded evidence " + str(i) + " " + "x" * 1000,
            (hashlib.sha256(("constructed:" + str(i)).encode()).hexdigest(),),
            "/text",
        )
        for i in range(600)
    )
    chunks = tuple(c for d in docs for c in chunk_document(d))
    vectors = [(1.0,) * 1024 for _ in chunks]
    manifest = IndexManifest(
        id="b" * 64,
        corpus_digest="c" * 64,
        model_id="constructed-model",
        model_digest="d" * 64,
        dimension=1024,
        chunking_version="test",
    )
    driver = BoundedTransactionDriver()
    IndexStore(driver).write(manifest, chunks, vectors, docs)
    assert len(driver.copies) == len(chunks) and driver.peak <= 2_000_000
    assert driver.transactions > 1
