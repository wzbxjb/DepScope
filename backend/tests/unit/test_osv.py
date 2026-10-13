import json

import httpx
import pytest

from depscope.identity.coordinates import identify
from depscope.runtime.errors import DomainError
from depscope.sources.osv import OsvClient
from depscope.sources.records import RecordStore


@pytest.fixture
def coordinates():
    return (identify("requests","2.32.3",None),identify("langchain-community","0.0.38",None))


async def test_pagination_tracks_each_coordinate(mock_osv,coordinates):
    mock_osv.batch([{}, {"vulns":[{"id":"GHSA-a"}],"next_page_token":"page-two"}])
    mock_osv.single_page("page-two",{"vulns":[{"id":"GHSA-b"}]})
    result=await mock_osv.client.query(coordinates)
    assert result[0].status == "no_match"
    assert result[1].record_ids == ("GHSA-a","GHSA-b") and result[1].status == "matched"
    assert len(result[1].source_refs) == 4
    assert all(mock_osv.client.records.get(ref.digest) for ref in result[1].source_refs)


async def test_failed_second_page_preserves_known_ids_as_partial(respx_mock,tmp_path,coordinates):
    respx_mock.post("https://api.osv.dev/v1/querybatch").respond(200,json={"results":[{}, {"vulns":[{"id":"GHSA-a"}],"next_page_token":"next"}]})
    respx_mock.post("https://api.osv.dev/v1/query").respond(503)
    async def sleep(seconds):
        pass
    async with httpx.AsyncClient() as http:
        result=await OsvClient(RecordStore(tmp_path),http,sleep=sleep).query(coordinates)
    assert result[1].status == "partial" and result[1].record_ids == ("GHSA-a",)
    assert result[0].status == "no_match"


async def test_mismatched_batch_length_is_error_not_safe(respx_mock,tmp_path,coordinates):
    respx_mock.post("https://api.osv.dev/v1/querybatch").respond(200,json={"results":[{}]})
    async with httpx.AsyncClient() as http:
        result=await OsvClient(RecordStore(tmp_path),http).query(coordinates)
    assert all(query.status == "error" for query in result)


async def test_queries_are_bounded_to_100_and_keep_input_order(respx_mock,tmp_path):
    sizes=[]
    def respond(request):
        payload=json.loads(request.content)
        sizes.append(len(payload["queries"]))
        return httpx.Response(200,json={"results":[{} for q in payload["queries"]]})
    respx_mock.post("https://api.osv.dev/v1/querybatch").mock(side_effect=respond)
    coordinates=tuple(identify(f"package-{i}","1.0",None) for i in range(205))
    async with httpx.AsyncClient() as http:
        result=await OsvClient(RecordStore(tmp_path),http).query(coordinates)
    assert sorted(sizes) == [5,100,100]
    assert tuple(query.coordinate for query in result) == coordinates


async def test_missing_advisory_is_failure_and_withdrawal_is_preserved(respx_mock,tmp_path,research_dir):
    raw=(research_dir/"osv_advisory.json").read_bytes()
    doc=json.loads(raw)
    doc["withdrawn"]="2026-01-01T00:00:00Z"
    respx_mock.get("https://api.osv.dev/v1/vulns/"+doc["id"]).respond(200,json=doc)
    respx_mock.get("https://api.osv.dev/v1/vulns/GHSA-missing").respond(404)
    async with httpx.AsyncClient() as http:
        client=OsvClient(RecordStore(tmp_path),http)
        revision=await client.advisory(doc["id"])
        assert revision.withdrawn == doc["withdrawn"] and revision.id == doc["id"]
        assert revision.source.digest == revision.digest
        with pytest.raises(DomainError,match="SOURCE_HTTP_ERROR"):
            await client.advisory("GHSA-missing")


async def test_repeated_page_token_is_partial_not_infinite_loop(respx_mock,tmp_path,coordinates):
    respx_mock.post("https://api.osv.dev/v1/querybatch").respond(200,json={"results":[{}, {"vulns":[{"id":"GHSA-a"}],"next_page_token":"same"}]})
    route=respx_mock.post("https://api.osv.dev/v1/query").respond(200,json={"vulns":[{"id":"GHSA-a"}],"next_page_token":"same"})
    async with httpx.AsyncClient() as http:
        result=await OsvClient(RecordStore(tmp_path),http).query(coordinates)
    assert result[1].status == "partial" and route.call_count == 1
