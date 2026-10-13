import hashlib

import pytest

from depscope.analysis.impact import PathService
from depscope.analysis.matching import Finding, MatchRun
from depscope.graph.match_runs import MatchRunRepository
from depscope.graph.queries import GraphService
from depscope.identity.coordinates import identify, instance_key
from depscope.runtime.errors import DomainError
from depscope.sources.advisories import PackageQuery

pytestmark=pytest.mark.integration


def matched_graph(repo,snapshot_factory,advisory_factory,count=250,date="2026-10-13T00:00:00Z"):
    ids=tuple(str(i) for i in range(count))
    snapshot=snapshot_factory(repo.create_project("impact"),ids,tuple((str(i),str(i+1)) for i in range(count-1)),root="0")
    coordinate=identify("requests","2.31.0",None)
    components=snapshot.components[:-1]+(snapshot.components[-1].model_copy(update={"coordinate":coordinate}),)
    snapshot=snapshot.model_copy(update={"components":components})
    repo.publish(snapshot,"impact-fixture")
    advisory=advisory_factory("GHSA-impact",aliases=("CVE-impact",))
    finding=Finding(id=hashlib.sha256((snapshot.snapshot_id+"finding").encode()).hexdigest(),
                    instance_id=instance_key(snapshot.snapshot_id,str(count-1)),group_id="impact-group",
                    revision_ids=(advisory.revision_id,))
    run=MatchRun(id="impact-"+snapshot.snapshot_id,snapshot_id=snapshot.snapshot_id,collection_id="impact-test",observed_at=date,
                 queries=(PackageQuery(coordinate=coordinate,status="matched",record_ids=(advisory.id,),source_refs=(advisory.source,)),),
                 findings=(finding,),revision_ids=(advisory.revision_id,),coverage={"total":1,"confirmed":1,"unknown":0})
    runs=MatchRunRepository(repo.driver)
    runs.save((run,),(advisory,))
    return snapshot,run,finding


def test_view_cap_never_shrinks_aggregate_counts(repo,snapshot_factory,advisory_factory):
    snapshot,run,finding=matched_graph(repo,snapshot_factory,advisory_factory)
    runs=MatchRunRepository(repo.driver)
    view=GraphService(repo,runs).view(snapshot.snapshot_id)
    assert len(view.nodes)==200 and view.total_nodes==250 and view.hidden_nodes==50
    result=PathService(repo,runs).paths(finding.id,{snapshot.snapshot_id:run.id})
    assert result.total_reachable==250 and len(result.display_nodes)==200 and result.hidden_nodes==50
    assert len(result.paths[0].instance_ids)==250


def test_cross_project_paths_keep_separate_snapshot_and_run_dates(repo,snapshot_factory,advisory_factory):
    a,ar,af=matched_graph(repo,snapshot_factory,advisory_factory,count=3,date="2026-10-12T00:00:00Z")
    b,br,bf=matched_graph(repo,snapshot_factory,advisory_factory,count=4,date="2026-10-13T00:00:00Z")
    mapping={a.snapshot_id:ar.id,b.snapshot_id:br.id}
    result=PathService(repo,MatchRunRepository(repo.driver)).paths(af.id,mapping)
    assert result.affected_projects == 2 and len(result.paths)==2
    assert result.run_map == mapping
    assert {path.observed_at for path in result.paths} == {ar.observed_at,br.observed_at}
    for path in result.paths:
        snapshot=a if path.snapshot_id==a.snapshot_id else b
        assert set(path.instance_ids) <= {instance_key(snapshot.snapshot_id,c.local_id) for c in snapshot.components}
    with pytest.raises(DomainError,match="SCOPE_MISMATCH"):
        PathService(repo,MatchRunRepository(repo.driver)).paths(af.id,{a.snapshot_id:br.id})
