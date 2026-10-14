import asyncio
import uuid
from collections import defaultdict

from depscope.identity.coordinates import instance_key
from depscope.ingest.models import Contract
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now

from .matching import query_key
from .metrics import completeness
from .verification import environment_known


class PackageEntry(Contract):
    name: str
    versions: tuple[str,...]


class VersionChange(Contract):
    name: str
    before: tuple[str,...]
    after: tuple[str,...]


class PackageDiff(Contract):
    added: tuple[PackageEntry,...]
    removed: tuple[PackageEntry,...]
    versions_changed: tuple[VersionChange,...]
    opaque_before: int
    opaque_after: int
    environment_comparable: bool


class MatchingDiff(Contract):
    added_known_matches: int
    remaining_known_matches: int
    removed_known_matches: int
    unknown: int
    unknown_details: tuple[str,...]


class Comparison(Contract):
    id: str
    baseline_id: str
    candidate_id: str
    run_ids: tuple[str,str]
    collection_id: str
    diff: PackageDiff
    removed_known_matches: int
    unknown: int
    level: str
    limitations: tuple[str,...]
    observed_at: str
    verification_id: str | None = None
    added_known_matches: int | None = None
    remaining_known_matches: int | None = None


def package_versions(snapshot) -> dict[str,tuple[str,...]]:
    values=defaultdict(set)
    for component in snapshot.components:
        if component.coordinate:
            values[component.coordinate.name].add(component.coordinate.version)
    return {name:tuple(sorted(versions)) for name,versions in values.items()}


def compare_packages(before,after) -> PackageDiff:
    a,b=package_versions(before),package_versions(after)
    return PackageDiff(added=tuple(PackageEntry(name=n,versions=b[n]) for n in sorted(b.keys()-a.keys())),
                       removed=tuple(PackageEntry(name=n,versions=a[n]) for n in sorted(a.keys()-b.keys())),
                       versions_changed=tuple(VersionChange(name=n,before=a[n],after=b[n]) for n in sorted(a.keys()&b.keys()) if a[n]!=b[n]),
                       opaque_before=sum(c.coordinate is None for c in before.components),
                       opaque_after=sum(c.coordinate is None for c in after.components),
                       environment_comparable=environment_known(before.environment) and before.environment==after.environment)


def _finding_groups(run,snapshot):
    keys={instance_key(snapshot.snapshot_id,c.local_id):c.coordinate for c in snapshot.components}
    result=defaultdict(set)
    for finding in run.findings:
        coordinate=keys.get(finding.instance_id)
        if coordinate:
            result[coordinate.name].add(finding.group_id)
    return result


def compare_known_findings(before,after,before_snapshot,after_snapshot) -> MatchingDiff:
    if before.snapshot_id!=before_snapshot.snapshot_id or after.snapshot_id!=after_snapshot.snapshot_id or before.collection_id!=after.collection_id:
        raise DomainError("COMPARISON_CONTEXT_MISMATCH", "Comparison requires scoped runs from one collection")
    a,b=_finding_groups(before,before_snapshot),_finding_groups(after,after_snapshot)
    package_queries=defaultdict(list)
    for query in (*before.queries,*after.queries):
        package_queries[query.coordinate.name].append(query)
    after_names=package_versions(after_snapshot)
    unknown_packages={q.coordinate.name for q in (*before.queries,*after.queries) if q.status not in {"matched","no_match"}}
    details=[]
    removed=0
    for name,groups in sorted(a.items()):
        for group in sorted(groups):
            if name in unknown_packages:
                details.append(name+":"+group+":query_unknown")
            elif name not in after_names:
                if completeness(after_snapshot).state!="complete" or any(c.coordinate is None for c in after_snapshot.components):
                    details.append(name+":"+group+":candidate_inventory_incomplete")
                else:
                    removed+=1
            elif group not in b.get(name,set()):
                candidate_keys={query_key(c.coordinate) for c in after_snapshot.components if c.coordinate and c.coordinate.name==name}
                confirmed_keys={query_key(q.coordinate) for q in after.queries if q.status in {"matched","no_match"}}
                if not candidate_keys<=confirmed_keys:
                    details.append(name+":"+group+":candidate_unqueried")
                else:
                    removed+=1
    details.extend(name+":query_unknown" for name in sorted(unknown_packages-a.keys()))
    return MatchingDiff(removed_known_matches=removed,unknown=len(details),unknown_details=tuple(details),
                        added_known_matches=sum(len(groups-a.get(name,set())) for name,groups in b.items()),
                        remaining_known_matches=sum(len(groups) for groups in b.values()))


class ComparisonService:
    def __init__(self,snapshots,matching,comparisons,verifications):
        self.snapshots,self.matching,self.comparisons,self.verifications=snapshots,matching,comparisons,verifications

    async def create(self,before_id,after_id,verification_id=None) -> Comparison:
        before,after=await asyncio.gather(asyncio.to_thread(self.snapshots.load,before_id),asyncio.to_thread(self.snapshots.load,after_id))
        if before_id==after_id:
            raise DomainError("IDENTICAL_SNAPSHOTS", "Choose two different snapshots")
        collection=str(uuid.uuid4())
        runs=await self.matching.collect((before_id,after_id),collection)
        matching=compare_known_findings(runs[before_id],runs[after_id],before,after)
        diff=compare_packages(before,after)
        level=await asyncio.to_thread(self.verifications.level,before,after,verification_id)
        limitations=[]
        if level=="metadata_comparison":
            limitations.append("No trusted installation and test verification for this candidate.")
        if not diff.environment_comparable:
            limitations.append("Target environments are unknown or differ.")
        if matching.unknown:
            limitations.append("Some matching changes remain unknown; they are not counted as removed.")
        if completeness(after).state!="complete":
            limitations.append("Candidate dependency graph is incomplete.")
        if diff.opaque_before or diff.opaque_after:
            limitations.append("Some components have no reliable PyPI identity.")
        result=Comparison(id=str(uuid.uuid4()),baseline_id=before_id,candidate_id=after_id,
                    run_ids=(runs[before_id].id,runs[after_id].id),collection_id=collection,diff=diff,
                    removed_known_matches=matching.removed_known_matches,unknown=matching.unknown,
                    level=level,limitations=tuple(limitations),observed_at=now(),verification_id=verification_id,
                    added_known_matches=matching.added_known_matches,remaining_known_matches=matching.remaining_known_matches)
        await asyncio.to_thread(self.comparisons.save,result)
        return result
