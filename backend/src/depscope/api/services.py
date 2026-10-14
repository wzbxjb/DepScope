import asyncio
import hashlib
import json
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
from depscope.ingest.depsdev import parse_depsdev
from depscope.jobs.handlers import import_handler
from depscope.jobs.store import JobStore
from depscope.jobs.worker import Worker
from depscope.runtime.config import PROJECT_ROOT, Settings
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now
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
        async def sample(job,cancelled):
            directory=PROJECT_ROOT / "docs/research/software_supply_chain"
            raw=await asyncio.to_thread((directory/"experimental_dependencies.json").read_bytes)
            manifest=json.loads((directory/"research_manifest.json").read_bytes())
            digest=hashlib.sha256(raw).hexdigest()
            if digest != manifest["source_files"]["experimental_dependencies.json"]["sha256"]:
                raise DomainError("RECORD_INTEGRITY", "Verified sample digest does not match its archive manifest")
            with driver.session() as session:
                existing=session.run("MATCH (p:Project {kind:'public_demo'})-[:HAS_SNAPSHOT]->(s:Snapshot {status:'ready'})-[:DERIVED_FROM]->(source:SourceRecord {digest:$digest}) RETURN s.snapshot_id AS sid ORDER BY s.published_at DESC LIMIT 1",digest=digest).single()
            await asyncio.to_thread(jobs.transition,job.id,"validating","writing",job.owner_token)
            if existing:
                snapshot_id=existing["sid"]
            else:
                project=await asyncio.to_thread(snapshots.create_project,"Verified public sample: langchain-experimental 0.0.50","public_demo")
                source=await asyncio.to_thread(records.put,raw,"archive://depscope/experimental_dependencies.json",now())
                snapshot=await asyncio.to_thread(parse_depsdev,raw,project,source)
                snapshot_id=await asyncio.to_thread(snapshots.publish,snapshot,job.staging_owner,cancelled=cancelled)
            try:
                await asyncio.to_thread(runs.latest,snapshot_id)
            except DomainError as exc:
                if exc.code!="MATCH_RUN_NOT_FOUND":
                    raise
                await MatchService(snapshots,runs,OsvClient(records,cancelled=cancelled)).collect((snapshot_id,),str(uuid.uuid4()))
            return snapshot_id
        worker=Worker(jobs,snapshots,{"import":import_handler(jobs,snapshots,records),"match":match,"compare":compare,"sample":sample})
        return Services(driver,snapshots,runs,comparisons,jobs,records,verifications,matching,
                        path_service,graph_service,comparison_service,worker,owns)
    except Exception:
        if owns:
            driver.close()
        raise
