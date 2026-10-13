import json

import httpx
import pytest

from depscope.analysis.matching import MatchService
from depscope.graph.match_runs import MatchRunRepository
from depscope.identity.coordinates import identify
from depscope.sources.osv import OsvClient
from depscope.sources.records import RecordStore

pytestmark=pytest.mark.integration


def requests_snapshot(repo,snapshot_factory):
    snapshot=snapshot_factory(repo.create_project("matching"),("root","a","b"),(("root","a"),("a","b")),root="root")
    components=tuple(c.model_copy(update={"coordinate":identify("requests","2.31.0",None)}) if c.local_id != "root" else c for c in snapshot.components)
    snapshot=snapshot.model_copy(update={"components":components})
    repo.publish(snapshot,"matching-fixture")
    return snapshot


async def test_shared_collection_deduplicates_queries_and_alias_findings(repo,snapshot_factory,respx_mock,tmp_path,advisory_factory):
    before=requests_snapshot(repo,snapshot_factory)
    after=requests_snapshot(repo,snapshot_factory)
    ids=["GHSA-a","PYSEC-b","GHSA-old"]
    batch=respx_mock.post("https://api.osv.dev/v1/querybatch").respond(200,json={"results":[{"vulns":[{"id":id} for id in ids]}]})
    for id in ids:
        advisory=advisory_factory(id,aliases=("CVE-1",),withdrawn="2026-01-01" if id=="GHSA-old" else None)
        doc=advisory.model_dump(mode="json",exclude={"digest","source"})
        respx_mock.get("https://api.osv.dev/v1/vulns/"+id).respond(200,json=doc)
    runs=MatchRunRepository(repo.driver)
    async with httpx.AsyncClient() as http:
        service=MatchService(repo,runs,OsvClient(RecordStore(tmp_path),http))
        result=await service.collect((before.snapshot_id,after.snapshot_id),"collection-test")
    assert len(json.loads(batch.calls[0].request.content)["queries"]) == 1
    assert len(result) == 2
    for snapshot in (before,after):
        run=result[snapshot.snapshot_id]
        assert run.collection_id == "collection-test"
        assert len(run.findings) == 2  # two instances, one alias group each
        assert all(len(f.revision_ids)==2 for f in run.findings)
        assert len(run.revision_ids)==3
        assert run.coverage["raw_matched_records"] == 3
        assert run.coverage["opaque_instances"] == 1
        assert runs.load(run.id) == run
        assert runs.latest(snapshot.snapshot_id).id == run.id
    assert result[before.snapshot_id].findings[0].instance_id != result[after.snapshot_id].findings[0].instance_id


async def test_conflicting_and_missing_advisories_remain_unknown(repo,snapshot_factory,respx_mock,tmp_path,advisory_factory):
    snap=requests_snapshot(repo,snapshot_factory)
    respx_mock.post("https://api.osv.dev/v1/querybatch").respond(200,json={"results":[{"vulns":[{"id":"GHSA-other"},{"id":"GHSA-missing"}]}]})
    doc=advisory_factory("GHSA-other").model_dump(mode="json",exclude={"digest","source"})
    doc["affected"][0]["package"]["name"]="unrelated-package"
    respx_mock.get("https://api.osv.dev/v1/vulns/GHSA-other").respond(200,json=doc)
    respx_mock.get("https://api.osv.dev/v1/vulns/GHSA-missing").respond(404)
    async with httpx.AsyncClient() as http:
        result=await MatchService(repo,MatchRunRepository(repo.driver),OsvClient(RecordStore(tmp_path),http)).collect((snap.snapshot_id,),"conflict-test")
    run=result[snap.snapshot_id]
    assert run.queries[0].status == "conflict"
    assert run.findings == () and run.coverage["confirmed"] == 0 and run.coverage["unknown"] == 1


async def test_refresh_keeps_same_content_revision_and_old_run_immutable(repo,snapshot_factory,respx_mock,tmp_path,advisory_factory):
    snapshot=requests_snapshot(repo,snapshot_factory)
    respx_mock.post("https://api.osv.dev/v1/querybatch").respond(200,json={"results":[{"vulns":[{"id":"GHSA-a"}]}]})
    doc=advisory_factory("GHSA-a",aliases=("CVE-1",)).model_dump(mode="json",exclude={"digest","source"})
    route=respx_mock.get("https://api.osv.dev/v1/vulns/GHSA-a").respond(200,json=doc)
    runs=MatchRunRepository(repo.driver)
    async with httpx.AsyncClient() as http:
        service=MatchService(repo,runs,OsvClient(RecordStore(tmp_path),http))
        first=(await service.collect((snapshot.snapshot_id,),"first"))[snapshot.snapshot_id]
        second=(await service.collect((snapshot.snapshot_id,),"second"))[snapshot.snapshot_id]
        assert first.revision_ids == second.revision_ids and first.id != second.id
        doc["aliases"].append("CVE-2")
        route.respond(200,json=doc)
        third=(await service.collect((snapshot.snapshot_id,),"third"))[snapshot.snapshot_id]
    assert first.findings[0].group_id != third.findings[0].group_id
    assert runs.load(first.id) == first
    assert runs.latest(snapshot.snapshot_id) == third
