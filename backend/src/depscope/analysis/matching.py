import asyncio
import hashlib
import json
import uuid
from collections import defaultdict
from typing import Literal

from depscope.identity.coordinates import instance_key, normalized_name
from depscope.ingest.models import Contract
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now
from depscope.sources.advisories import PackageQuery

from .aliases import alias_group_key, alias_groups


class Finding(Contract):
    id: str
    instance_id: str
    group_id: str
    revision_ids: tuple[str,...]
    status: Literal["known_match"] = "known_match"


class MatchRun(Contract):
    id: str
    snapshot_id: str
    collection_id: str
    observed_at: str
    queries: tuple[PackageQuery,...]
    findings: tuple[Finding,...]
    revision_ids: tuple[str,...]
    coverage: dict[str,int]


def query_key(coordinate) -> tuple[str,str,str]:
    return coordinate.ecosystem,coordinate.name,coordinate.raw_version


def confirmed_coverage(queries: tuple[PackageQuery,...]) -> dict[str,int]:
    checked=sum(q.status in {"matched","no_match"} for q in queries)
    return {"total":len(queries),"confirmed":checked,"unknown":len(queries)-checked}


class MatchService:
    def __init__(self,snapshots,runs,osv):
        self.snapshots,self.runs,self.osv=snapshots,runs,osv

    async def collect(self,snapshot_ids: tuple[str,...],collection_id: str) -> dict[str,MatchRun]:
        snapshots=tuple(await asyncio.gather(*(asyncio.to_thread(self.snapshots.load,sid) for sid in dict.fromkeys(snapshot_ids))))
        unique={query_key(c.coordinate):c.coordinate for s in snapshots for c in s.components if c.coordinate}
        queried=await self.osv.query(tuple(unique.values()))
        record_ids=tuple(dict.fromkeys(id for q in queried for id in q.record_ids))
        semaphore=asyncio.Semaphore(4)
        async def fetch(id):
            async with semaphore:
                try:
                    return id,await self.osv.advisory(id),None
                except DomainError as exc:
                    if exc.code == "CANCELLED":
                        raise
                    return id,None,exc.code
        fetched=await asyncio.gather(*(fetch(id) for id in record_ids))
        revisions={id:revision for id,revision,error in fetched if revision is not None}
        failures={id:error for id,revision,error in fetched if error is not None}
        groups=alias_groups(tuple(revisions.values()))
        by_query={}
        compatible={}
        for query in queried:
            issues=list(query.issues)
            good=[]
            conflict=False
            missing=False
            for id in query.record_ids:
                if id in failures:
                    missing=True
                    issues.append("advisory_unavailable:"+id+":"+failures[id])
                    continue
                revision=revisions[id]
                matches=any(row.get("package",{}).get("ecosystem")==query.coordinate.ecosystem
                            and normalized_name(row.get("package",{}).get("name",""))==query.coordinate.name
                            for row in revision.affected)
                if not matches:
                    conflict=True
                    issues.append("affected_package_conflict:"+id)
                elif not revision.withdrawn:
                    good.append(id)
            status="conflict" if conflict else ("partial" if missing else query.status)
            adjusted=query.model_copy(update={"status":status,"issues":tuple(issues)})
            by_query[query_key(query.coordinate)]=adjusted
            compatible[query_key(query.coordinate)]=tuple(good)
        results={}
        for snapshot in snapshots:
            run_id=str(uuid.uuid4())
            coordinate_keys=tuple(dict.fromkeys(query_key(c.coordinate) for c in snapshot.components if c.coordinate))
            queries=tuple(by_query[key] for key in coordinate_keys)
            findings=[]
            relevant_revision_ids=set()
            for query in queries:
                relevant_revision_ids.update(revisions[id].revision_id for id in query.record_ids if id in revisions)
            for component in snapshot.components:
                if component.coordinate is None:
                    continue
                grouped=defaultdict(list)
                for id in compatible[query_key(component.coordinate)]:
                    group_id=alias_group_key(set(groups[id]))
                    grouped[group_id].append(revisions[id].revision_id)
                for group_id,ids in grouped.items():
                    inst=instance_key(snapshot.snapshot_id,component.local_id)
                    fid=hashlib.sha256(json.dumps([run_id,inst,group_id],separators=(",", ":")).encode()).hexdigest()
                    findings.append(Finding(id=fid,instance_id=inst,group_id=group_id,revision_ids=tuple(sorted(ids))))
            coverage=confirmed_coverage(queries)
            coverage.update(raw_matched_records=sum(len(q.record_ids) for q in queries),
                            active_findings=len(findings),opaque_instances=sum(c.coordinate is None for c in snapshot.components),
                            total_instances=len(snapshot.components))
            results[snapshot.snapshot_id]=MatchRun(id=run_id,snapshot_id=snapshot.snapshot_id,
                        collection_id=collection_id,observed_at=now(),queries=queries,findings=tuple(findings),
                        revision_ids=tuple(sorted(relevant_revision_ids)),coverage=coverage)
        await asyncio.to_thread(self.runs.save,tuple(results.values()),tuple(revisions.values()))
        return results
