import hashlib

import pytest

from depscope.runtime.errors import DomainError
from depscope.sources.records import RecordStore


def test_records_deduplicate_bytes_but_preserve_each_observation(tmp_path):
    store = RecordStore(tmp_path)
    raw = b'{"source":"actual bytes"}'
    a = store.put(raw, "https://api.osv.dev/v1/vulns/GHSA-example", "2026-10-13T00:00:00Z")
    b = store.put(raw, "https://api.osv.dev/v1/vulns/GHSA-example", "2026-10-13T01:00:00Z")
    assert a.digest == b.digest == hashlib.sha256(raw).hexdigest()
    assert store.get(a.digest) == raw
    observations = store.observations(a.digest)
    assert len(observations) == 2
    assert {r.observed_at for r in observations} == {a.observed_at,b.observed_at}


def test_corrupted_bytes_and_invalid_hash_paths_are_rejected(tmp_path):
    store = RecordStore(tmp_path)
    source = store.put(b'original', "fixture://constructed", "2026-10-13T00:00:00Z")
    store.path_for(source.digest).write_bytes(b'changed')
    with pytest.raises(DomainError, match="RECORD_INTEGRITY"):
        store.get(source.digest)
    with pytest.raises(DomainError, match="INVALID_DIGEST"):
        store.get("../../outside")
