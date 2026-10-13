from concurrent.futures import ThreadPoolExecutor

import pytest

from depscope.jobs.worker import Worker
from depscope.runtime.errors import DomainError

pytestmark=pytest.mark.integration


def test_restart_never_discards_published_snapshot(job_store,repo,ready_snapshot):
    job=job_store.enqueue("import",{"snapshot_id":ready_snapshot.snapshot_id})
    assert job_store.claim(job.id,"worker-old")
    job_store.mark_interrupted()
    assert repo.load(ready_snapshot.snapshot_id).snapshot_id == ready_snapshot.snapshot_id
    assert job_store.get(job.id).status == "interrupted"
    assert job_store.transition(job.id,"interrupted","queued")
    assert job_store.claim(job.id,"worker-new")
    assert job_store.get(job.id).owner_token == "worker-new"


def test_two_workers_compete_for_one_mutation_lease(job_store):
    jobs=[job_store.enqueue("import",{"test":i}) for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda pair:job_store.claim(pair[1].id,"worker-"+str(pair[0])),enumerate(jobs)))
    assert sorted(results) == [False,True]
    selected=jobs[results.index(True)]
    assert job_store.claim(selected.id,"foreign") is False


async def test_cancel_never_deletes_ready_and_worker_errors_are_durable(job_store,repo,ready_snapshot):
    job=job_store.enqueue("import",{"snapshot_id":ready_snapshot.snapshot_id})
    async def handle(job,cancelled):
        job_store.request_cancel(job.id)
        assert cancelled()
        raise DomainError("CANCELLED","Test cancellation")
    worker=Worker(job_store,repo,{"import":handle})
    assert await worker.run_once()
    assert job_store.get(job.id).status == "cancelled"
    assert repo.load(ready_snapshot.snapshot_id) == ready_snapshot
    queued=job_store.enqueue("import",{})
    job_store.request_cancel(queued.id)
    assert job_store.get(queued.id).status == "cancelled"


async def test_success_and_non_retryable_failure_are_recorded(job_store,repo,ready_snapshot):
    async def handle(job,cancelled):
        if job.payload.get("fail"):
            raise DomainError("INVALID_BOM","Constructed validation failure",("/components",))
        return ready_snapshot.snapshot_id
    worker=Worker(job_store,repo,{"import":handle})
    job=job_store.enqueue("import",{})
    assert await worker.run_once()
    result=job_store.get(job.id)
    assert result.status == "ready" and result.progress == 1 and result.result_id == ready_snapshot.snapshot_id
    job_store.request_cancel(job.id)
    assert job_store.get(job.id).status == "ready"
    failed=job_store.enqueue("import",{"fail":True})
    assert await worker.run_once()
    assert job_store.get(failed.id).error["retryable"] is False
    assert job_store.get(failed.id).status == "failed"
    assert not await worker.run_once()


def test_retry_gets_fresh_cancellation_state(job_store):
    job=job_store.enqueue("import",{})
    assert job_store.claim(job.id,"old-owner")
    job_store.mark_interrupted()
    assert not job_store.heartbeat(job.id,"old-owner")
    assert job_store.is_cancelled(job.id)
    assert job_store.transition(job.id,"interrupted","queued")
    assert job_store.claim(job.id,"new-owner")
    assert not job_store.is_cancelled(job.id)
