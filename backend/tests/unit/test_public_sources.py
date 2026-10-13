import json
from datetime import UTC, datetime

import httpx
import pytest

from depscope.ingest.depsdev import parse_depsdev
from depscope.runtime.errors import DomainError
from depscope.sources.http import PublicClient
from depscope.sources.pypi import select_versions
from depscope.sources.retry import request_with_retry


def test_public_graph_preserves_instance_indices(research_dir, source_for):
    raw = (research_dir / "experimental_dependencies.json").read_bytes()
    snap = parse_depsdev(raw, "public-demo", source_for(raw))
    assert len(snap.components) == 41 and len(snap.edges) == 72
    assert snap.root_id == "0"
    assert len({c.local_id for c in snap.components}) == 41
    assert snap.source_kind == "public_resolution"
    assert snap.environment["resolution_context"] == "deps.dev generic Linux"


def test_duplicate_versions_remain_distinct_and_errors_remain_visible(research_dir, source_for):
    doc = json.loads((research_dir / "experimental_dependencies.json").read_bytes())
    doc["nodes"].append(dict(doc["nodes"][1]))
    doc["nodes"][-1]["errors"] = [{"error":"resolution unavailable"}]
    doc["error"] = "incomplete resolution"
    raw = json.dumps(doc).encode()
    snap = parse_depsdev(raw, "p", source_for(raw))
    assert len(snap.components) == 42
    assert snap.components[1].coordinate.key == snap.components[-1].coordinate.key
    assert snap.components[-1].dependencies_known is False
    assert any("resolution unavailable" in item for item in snap.issues)
    assert any("incomplete resolution" in item for item in snap.issues)


def test_invalid_edge_index_and_digest_are_rejected(research_dir, source_for):
    doc = json.loads((research_dir / "experimental_dependencies.json").read_bytes())
    doc["edges"][0]["toNode"] = 5000
    raw = json.dumps(doc).encode()
    with pytest.raises(DomainError, match="DANGLING_EDGE"):
        parse_depsdev(raw, "p", source_for(raw))
    with pytest.raises(DomainError, match="SOURCE_DIGEST_MISMATCH"):
        parse_depsdev(raw, "p", source_for(b'other'))


def release(date, yanked=False):
    return {"upload_time_iso_8601":date, "yanked":yanked}


def test_version_selection_uses_dates_and_excludes_unusable_releases():
    metadata={"releases":{
        "0.1":[release("2024-01-05T00:00:00Z")],
        "0.2":[release("2024-02-01T00:00:00Z")],
        "1.0":[release("2025-01-02T00:00:00Z")],
        "2.0":[release("2026-09-01T00:00:00Z")],
        "3.0":[release("2026-12-01T00:00:00Z")],
        "4.0rc1":[release("2026-01-01T00:00:00Z")],
        "5.0.dev1":[release("2026-01-01T00:00:00Z")],
        "6.0":[release("2026-01-01T00:00:00Z",True)],
        "empty":[],
    }}
    assert select_versions(metadata, datetime(2026,10,13,tzinfo=UTC)) == ("2.0","0.1","1.0")
    assert select_versions({"releases":{"2.0":metadata["releases"]["2.0"]}}, datetime(2026,10,13,tzinfo=UTC)) == ("2.0",)


async def test_retry_is_bounded_and_retry_after_takes_priority(respx_mock):
    route=respx_mock.get("https://pypi.org/pypi/requests/json")
    route.side_effect=[httpx.Response(429,headers={"Retry-After":"1"}),httpx.Response(503),httpx.Response(200,json={"ok":True})]
    waits=[]
    async def sleep(seconds):
        waits.append(seconds)
    async with httpx.AsyncClient() as client:
        result=await request_with_retry(client,"GET","https://pypi.org/pypi/requests/json",sleep=sleep)
    assert result.json() == {"ok":True}
    assert waits == [1.0,4.0]
    assert route.call_count == 3


async def test_retry_cancellation_and_exhaustion(respx_mock):
    route=respx_mock.get("https://pypi.org/pypi/requests/json").respond(503)
    waits=[]
    async def sleep(seconds):
        waits.append(seconds)
    async with httpx.AsyncClient() as client:
        with pytest.raises(DomainError,match="SOURCE_UNAVAILABLE"):
            await request_with_retry(client,"GET","https://pypi.org/pypi/requests/json",sleep=sleep)
        assert waits == [2.0,4.0,8.0] and route.call_count == 4
        with pytest.raises(DomainError,match="CANCELLED"):
            await request_with_retry(client,"GET","https://pypi.org/pypi/requests/json",cancelled=lambda:True,sleep=sleep)
        assert route.call_count == 4


async def test_public_client_rejects_arbitrary_urls_without_network(respx_mock):
    async with httpx.AsyncClient() as http:
        client=PublicClient(http)
        for uri in ("http://127.0.0.1/private", "https://pypi.org.evil.example/api", "https://user:pass@pypi.org/pypi/x/json"):
            with pytest.raises(DomainError,match="SOURCE_URL_REJECTED"):
                await client.get_json(uri)
    assert len(respx_mock.calls) == 0
