import json

import httpx
import pytest

from depscope.analysis.comparison import ComparisonService
from depscope.analysis.matching import MatchService
from depscope.analysis.verification import VerificationRegistry
from depscope.graph.comparisons import ComparisonRepository
from depscope.graph.match_runs import MatchRunRepository
from depscope.identity.coordinates import identify
from depscope.runtime.errors import DomainError
from depscope.sources.osv import OsvClient
from depscope.sources.records import RecordStore

pytestmark=pytest.mark.integration


async def test_comparison_pins_shared_collection_and_stays_metadata_without_local_proof(repo,snapshot_factory,respx_mock,tmp_path,advisory_factory):
    project=repo.create_project("upgrade")
    snapshots=[]
    for index,version in enumerate(("2.31.0","2.32.3")):
        snap=snapshot_factory(project,(f"r{index}",),(),root=f"r{index}")
        snap=snap.model_copy(update={"components":(snap.components[0].model_copy(update={"name":"requests","coordinate":identify("requests",version,None)}),)})
        repo.publish(snap,"comparison-fixture-"+str(index))
        snapshots.append(snap)
    def response(request):
        queries=json.loads(request.content)["queries"]
        return httpx.Response(200,json={"results":[{"vulns":[{"id":"GHSA-upgrade"}]} if q["version"]=="2.31.0" else {} for q in queries]})
    respx_mock.post("https://api.osv.dev/v1/querybatch").mock(side_effect=response)
    respx_mock.get("https://api.osv.dev/v1/vulns/GHSA-upgrade").respond(200,json=advisory_factory("GHSA-upgrade").model_dump(mode="json",exclude={"digest","source"}))
    runs=MatchRunRepository(repo.driver)
    comparisons=ComparisonRepository(repo.driver)
    async with httpx.AsyncClient() as http:
        matching=MatchService(repo,runs,OsvClient(RecordStore(tmp_path),http))
        service=ComparisonService(repo,matching,comparisons,VerificationRegistry(tmp_path))
        result=await service.create(snapshots[0].snapshot_id,snapshots[1].snapshot_id)
    assert result.level == "metadata_comparison" and result.removed_known_matches == 1
    selected=[runs.load(id) for id in result.run_ids]
    assert {r.collection_id for r in selected} == {result.collection_id}
    assert comparisons.load(result.id) == result
    with pytest.raises(DomainError,match="COMPARISON_IMMUTABLE"):
        comparisons.save(result.model_copy(update={"removed_known_matches":999}))
    assert runs.load(result.run_ids[0]).snapshot_id == result.baseline_id


def test_unsigned_uploaded_test_results_cannot_enter_registry(tmp_path):
    path=tmp_path/"uploaded.json"
    path.write_text(json.dumps({"producer":"depscope-local-v1","exit_code":0,"tests_ok":True}))
    with pytest.raises(DomainError,match="UNTRUSTED_VERIFICATION"):
        VerificationRegistry(tmp_path/"registry").register(path,"project","snapshot")
