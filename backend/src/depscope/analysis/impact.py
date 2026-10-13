from depscope.analysis.metrics import Completeness, completeness
from depscope.analysis.paths import breadth_first, reconstruct
from depscope.identity.coordinates import instance_key
from depscope.ingest.models import Contract
from depscope.runtime.errors import DomainError


class DependencyPath(Contract):
    snapshot_id: str
    project_id: str
    run_id: str
    finding_id: str
    observed_at: str
    instance_ids: tuple[str,...]
    labels: tuple[str,...]
    revision_ids: tuple[str,...]


class PathResult(Contract):
    paths: tuple[DependencyPath,...]
    total_reachable: int
    display_nodes: tuple[str,...]
    hidden_nodes: int
    hidden_paths: int
    completeness: dict[str,Completeness]
    run_map: dict[str,str]
    affected_projects: int
    reachable_matches: int
    unreachable_matches: int
    unknown_paths: int


class PathService:
    def __init__(self,snapshots,runs):
        self.snapshots,self.runs=snapshots,runs

    def _identifiers(self,finding) -> set[str]:
        values=set()
        for key in finding.revision_ids:
            revision=self.runs.revision(key)
            values.update((revision.id,)+revision.aliases)
        return values

    def paths(self,finding_id: str,run_map: dict[str,str]) -> PathResult:
        anchor,anchor_run=self.runs.finding(finding_id)
        if run_map.get(anchor_run.snapshot_id) != anchor_run.id:
            raise DomainError("SCOPE_MISMATCH", "Anchor finding must belong to the selected run map")
        anchor_ids=self._identifiers(anchor)
        results=[]
        display=[]
        display_seen=set()
        all_nodes=set()
        projects=set()
        states={}
        total=reachable=unreachable=unknown=0
        for snapshot_id,run_id in sorted(run_map.items()):
            snapshot=self.snapshots.load(snapshot_id)
            run=self.runs.load(run_id)
            if run.snapshot_id != snapshot_id:
                raise DomainError("SCOPE_MISMATCH", "Run map crosses snapshot contexts")
            states[snapshot_id]=completeness(snapshot)
            parents=breadth_first(snapshot)
            total+=len(parents)
            components={c.local_id:c for c in snapshot.components}
            local_keys={instance_key(snapshot_id,c.local_id):c.local_id for c in snapshot.components}
            seen_ancestors=set()
            for finding in sorted(run.findings,key=lambda f:f.id):
                if not anchor_ids.intersection(self._identifiers(finding)):
                    continue
                target=local_keys.get(finding.instance_id)
                if target is None:
                    raise DomainError("SCOPE_MISMATCH", "Finding instance is outside its run snapshot")
                if snapshot.root_id is None:
                    unknown+=1
                    continue
                if target not in parents:
                    unreachable+=1
                    continue
                reachable+=1
                projects.add(snapshot.project_id)
                node=target
                while node is not None and node not in seen_ancestors:
                    seen_ancestors.add(node)
                    all_nodes.add(instance_key(snapshot_id,node))
                    node=parents[node]
                if len(results)<20:
                    local_path=reconstruct(parents,target)
                    instances=tuple(instance_key(snapshot_id,n) for n in local_path)
                    results.append(DependencyPath(snapshot_id=snapshot_id,project_id=snapshot.project_id,
                                   run_id=run_id,finding_id=finding.id,observed_at=run.observed_at,
                                   instance_ids=instances,labels=tuple(components[n].name for n in local_path),
                                   revision_ids=finding.revision_ids))
                    for inst in instances:
                        if inst not in display_seen and len(display)<200:
                            display_seen.add(inst)
                            display.append(inst)
        return PathResult(paths=tuple(results),total_reachable=total,display_nodes=tuple(display),
                          hidden_nodes=len(all_nodes)-len(display),hidden_paths=max(0,reachable-len(results)),
                          completeness=states,run_map=dict(run_map),affected_projects=len(projects),
                          reachable_matches=reachable,unreachable_matches=unreachable,unknown_paths=unknown)
