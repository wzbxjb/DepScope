import asyncio
import contextlib
import uuid

from depscope.runtime.errors import DomainError


class Worker:
    def __init__(self, store, repo, handlers):
        self.store,self.repo,self.handlers=store,repo,handlers
        self.owner_token=str(uuid.uuid4())

    async def run_once(self) -> bool:
        await asyncio.to_thread(self.store.mark_interrupted,only_stale=True)
        for job_id in await asyncio.to_thread(self.store.pending):
            if not await asyncio.to_thread(self.store.claim,job_id,self.owner_token):
                continue
            job=await asyncio.to_thread(self.store.get,job_id)
            async def poll(job_id=job_id):
                while True:
                    await asyncio.sleep(.2)
                    if not await asyncio.to_thread(self.store.heartbeat,job_id,self.owner_token):
                        return
            poller=asyncio.create_task(poll())
            try:
                handler=self.handlers.get(job.kind)
                if handler is None:
                    raise DomainError("UNKNOWN_JOB_KIND", "No handler is registered")
                result=await handler(job,lambda job_id=job_id:self.store.is_cancelled(job_id))
                current=await asyncio.to_thread(self.store.get,job_id)
                if current.status in ("validating","fetching"):
                    await asyncio.to_thread(self.store.transition,job_id,current.status,"writing",self.owner_token)
                await asyncio.to_thread(self.store.transition,job_id,"writing","ready",self.owner_token,result_id=result)
            except Exception as exc:
                error=exc.as_dict() if isinstance(exc,DomainError) else DomainError("JOB_FAILED", "Background job failed",retryable=False).as_dict()
                current=await asyncio.to_thread(self.store.get,job_id)
                if current.status in ("validating","fetching","writing") and current.owner_token==self.owner_token:
                    await asyncio.to_thread(self.repo.delete_unpublished,job.staging_owner)
                    target="cancelled" if error["code"]=="CANCELLED" else "failed"
                    await asyncio.to_thread(self.store.transition,job_id,current.status,target,self.owner_token,error=error)
            finally:
                poller.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await poller
            return True
        return False


async def serve(settings):
    from depscope.graph.driver import connect
    from depscope.graph.migrations import migrate
    from depscope.graph.snapshots import SnapshotRepository
    from depscope.jobs.handlers import import_handler
    from depscope.jobs.store import JobStore
    from depscope.sources.records import RecordStore
    driver=connect(settings)
    try:
        await asyncio.to_thread(migrate,driver)
        store=JobStore(driver)
        repo=SnapshotRepository(driver)
        worker=Worker(store,repo,{"import":import_handler(store,repo,RecordStore(settings.data_root))})
        while True:
            if not await worker.run_once():
                await asyncio.sleep(.5)
    finally:
        driver.close()


if __name__ == "__main__":
    import argparse

    from depscope.runtime.config import load_settings
    parser=argparse.ArgumentParser(description="Run the persistent DepScope mutation queue")
    parser.parse_args()
    asyncio.run(serve(load_settings()))
