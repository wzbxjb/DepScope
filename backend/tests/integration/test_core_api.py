import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from depscope.runtime.app import create_app
from depscope.runtime.config import load_settings

pytestmark=pytest.mark.integration
BOM={"bomFormat":"CycloneDX","specVersion":"1.6","version":1,
     "metadata":{"component":{"type":"application","name":"test-app","version":"1.0","bom-ref":"root"}},
     "components":[{"type":"library","name":"requests","version":"2.32.3","bom-ref":"lib"}],
     "dependencies":[{"ref":"root","dependsOn":["lib"]},{"ref":"lib","dependsOn":[]}]}


@pytest.fixture
def services(repo,job_store):
    from depscope.api.services import build_services
    return build_services(load_settings(),driver=repo.driver,snapshots=repo,jobs=job_store)


@pytest.fixture
def client(services):
    with TestClient(create_app(load_settings(),services=services)) as test_client:
        yield test_client


def test_streamed_oversize_import_has_no_published_snapshot(client,repo):
    project=client.post("/api/projects",json={"name":"demo"}).json()["id"]
    response=client.post("/api/projects/"+project+"/imports",content=b"x"*(10*1024*1024+1),
                         headers={"Content-Type":"application/json","Content-Length":"1"})
    assert response.status_code==413
    assert repo.list_snapshots(project).items==()


async def test_missing_content_length_is_bounded_by_consumed_chunks(services,repo):
    project=repo.create_project("stream-limit")
    consumed=[]
    async def chunks():
        for value in (b"a"*6_000_000,b"b"*6_000_000,b"never-read"):
            consumed.append(True)
            yield value
    app=create_app(load_settings(),services=services)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://testserver") as http:
        response=await http.post(f"/api/projects/{project}/imports",content=chunks(),headers={"Content-Type":"application/json"})
    assert response.status_code==413 and len(consumed)==2
    assert repo.list_snapshots(project).items==()


def test_import_job_persists_and_graph_context_is_enforced(client,services,repo):
    project=client.post("/api/projects",json={"name":"imported"}).json()["id"]
    submitted=client.post(f"/api/projects/{project}/imports",content=json.dumps(BOM),headers={"Content-Type":"application/json"})
    assert submitted.status_code==202
    job_id=submitted.json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}").json()["status"]=="queued"
    assert asyncio.run(services.worker.run_once())
    job=client.get(f"/api/jobs/{job_id}").json()
    assert job["status"]=="ready"
    assert "owner_token" not in job and "payload" not in job
    snapshot_id=job["result_id"]
    graph=client.get(f"/api/snapshots/{snapshot_id}/graph",params={"project_id":project}).json()
    assert graph["snapshot_id"]==snapshot_id and graph["total_nodes"]==2
    other=repo.create_project("other")
    assert client.get(f"/api/snapshots/{snapshot_id}/graph",params={"project_id":other}).status_code==409
    assert client.get(f"/api/snapshots/{snapshot_id}/graph",params={"focus_id":"lib"}).status_code==409
    snapshots=client.get(f"/api/projects/{project}/snapshots").json()
    assert len(snapshots["items"])==1 and snapshots["next_cursor"] is None
    assert snapshots["items"][0]["root_name"]=="test-app"


def test_invalid_cursor_unknown_project_and_safe_validation(client):
    assert client.get("/api/projects",params={"cursor":"bad"}).status_code==422
    response=client.post("/api/projects",json={"name":"valid","DEEPSEEK_API_KEY":"sentinel-secret"})
    assert response.status_code==422 and "sentinel-secret" not in response.text
    response=client.post("/api/projects/missing/imports",content=json.dumps(BOM),headers={"Content-Type":"application/json"})
    assert response.status_code==404


def test_job_cancel_is_persistent_and_pages_are_consumable(client,services):
    project=client.post("/api/projects",json={"name":"cancelled"}).json()["id"]
    job=client.post(f"/api/projects/{project}/imports",content=json.dumps(BOM),headers={"Content-Type":"application/json"}).json()["job_id"]
    assert client.post(f"/api/jobs/{job}/cancel").status_code==200
    assert client.get(f"/api/jobs/{job}").json()["status"]=="cancelled"
    assert not asyncio.run(services.worker.run_once())
    for index in range(4):
        client.post("/api/projects",json={"name":f"page-{index}"})
    seen=[]
    cursor=None
    while True:
        params={"limit":2}
        if cursor:
            params["cursor"]=cursor
        page=client.get("/api/projects",params=params).json()
        seen.extend(row["id"] for row in page["items"])
        cursor=page["next_cursor"]
        if not cursor:
            break
    assert project in seen and len(seen)==len(set(seen)) and len(seen)>=5


def test_verified_sample_loads_real_archive_through_background_job(client,services,respx_mock):
    def empty_queries(request):
        queries=json.loads(request.content)["queries"]
        return httpx.Response(200,json={"results":[{} for query in queries]})
    respx_mock.post("https://api.osv.dev/v1/querybatch").mock(side_effect=empty_queries)
    submitted=client.post("/api/demo/public-sample")
    assert submitted.status_code==202
    job_id=submitted.json()["job_id"]
    assert asyncio.run(services.worker.run_once())
    job=client.get(f"/api/jobs/{job_id}").json()
    assert job["status"]=="ready"
    graph=client.get(f"/api/snapshots/{job['result_id']}/graph").json()
    assert graph["total_nodes"]==41 and len(graph["edges"])==72
    assert graph["run_id"] is not None
