import asyncio
import uuid
from dataclasses import dataclass

from depscope.analysis.comparison import ComparisonService
from depscope.analysis.impact import PathService
from depscope.analysis.matching import MatchService
from depscope.analysis.verification import VerificationRegistry
from depscope.graph.comparisons import ComparisonRepository
from depscope.graph.driver import connect
from depscope.graph.match_runs import MatchRunRepository
from depscope.graph.migrations import migrate
from depscope.graph.queries import GraphService
from depscope.graph.snapshots import SnapshotRepository
from depscope.jobs.handlers import import_handler
from depscope.jobs.store import JobStore
from depscope.jobs.worker import Worker
from depscope.runtime.config import Settings
from depscope.sources.osv import OsvClient
from depscope.sources.records import RecordStore


@dataclass
class Services:
    driver: object
    snapshots: SnapshotRepository
    runs: MatchRunRepository
    comparisons: ComparisonRepository
    jobs: JobStore
    records: RecordStore
    verifications: VerificationRegistry
    match_service: MatchService
    path_service: PathService
    graph_service: GraphService
    comparison_service: ComparisonService
    worker: Worker
    owns_driver: bool = True

    def close(self):
        if self.owns_driver:
            self.driver.close()


def build_services(settings: Settings,driver=None,snapshots=None,jobs=None) -> Services:
    owns=driver is None
    driver=connect(settings) if driver is None else driver
    try:
        migrate(driver)
        snapshots=SnapshotRepository(driver) if snapshots is None else snapshots
        jobs=JobStore(driver) if jobs is None else jobs
        runs=MatchRunRepository(driver)
        comparisons=ComparisonRepository(driver)
        records=RecordStore(settings.data_root)
        verifications=VerificationRegistry(settings.data_root)
        matching=MatchService(snapshots,runs,OsvClient(records))
        path_service=PathService(snapshots,runs)
        graph_service=GraphService(snapshots,runs)
        comparison_service=ComparisonService(snapshots,matching,comparisons,verifications)
        async def match(job,cancelled):
            await asyncio.to_thread(jobs.transition,job.id,"validating","fetching",job.owner_token)
            service=MatchService(snapshots,runs,OsvClient(records,cancelled=cancelled))
            results=await service.collect(tuple(job.payload["snapshot_ids"]),str(uuid.uuid4()))
            return next(iter(results.values())).id
        async def compare(job,cancelled):
            await asyncio.to_thread(jobs.transition,job.id,"validating","fetching",job.owner_token)
            service=ComparisonService(snapshots,MatchService(snapshots,runs,OsvClient(records,cancelled=cancelled)),comparisons,verifications)
            result=await service.create(job.payload["baseline_id"],job.payload["candidate_id"],job.payload.get("verification_id"))
            return result.id
        worker=Worker(jobs,snapshots,{"import":import_handler(jobs,snapshots,records),"match":match,"compare":compare})
        return Services(driver,snapshots,runs,comparisons,jobs,records,verifications,matching,
                        path_service,graph_service,comparison_service,worker,owns)
    except Exception:
        if owns:
            driver.close()
        raise
