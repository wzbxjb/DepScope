import pytest

from depscope.graph.migrations import migrate
from depscope.identity.coordinates import instance_key
from depscope.runtime.errors import DomainError

pytestmark = pytest.mark.integration


def test_duplicate_import_and_context_boundary(repo, public_snapshot_factory):
    project = repo.create_project("sample")
    snap = public_snapshot_factory(project)
    first = repo.publish(snap, "job-a")
    assert repo.publish(snap, "job-b") == first
    loaded = repo.load(first)
    assert loaded == snap and len(loaded.edges) == 72
    assert all(e.from_id in {c.local_id for c in loaded.components} for e in loaded.edges)
    other = public_snapshot_factory(repo.create_project("other"))
    repo.publish(other, "job-c")
    with repo.driver.session() as session:
        crossed = session.run("MATCH (a:ComponentInstance)-[:DEPENDS_ON]->(b:ComponentInstance) WHERE a.snapshot_id <> b.snapshot_id RETURN count(*) AS n").single()["n"]
        assert crossed == 0
        assert instance_key(first,"0") != instance_key(other.snapshot_id,"0")
        assert session.run("MATCH (:ComponentInstance {snapshot_id:$s})-[e:DEPENDS_ON]->() RETURN count(e) AS n",s=first).single()["n"] == 72


def test_ready_is_immutable_and_foreign_cleanup_cannot_delete_it(repo, public_snapshot_factory):
    snap = public_snapshot_factory(repo.create_project("immutable"))
    repo.publish(snap, "job-ready")
    changed = snap.model_copy(update={"issues":("changed",)})
    assert repo.publish(changed, "job-other") == snap.snapshot_id
    assert repo.delete_unpublished("job-ready") == 0
    assert repo.load(snap.snapshot_id) == snap


def test_failed_stage_is_owned_and_not_visible(repo, public_snapshot_factory):
    snap = public_snapshot_factory(repo.create_project("staged"))
    repo.stage(snap, "owner")
    assert repo.list_snapshots(snap.project_id).items == ()
    with pytest.raises(DomainError, match="SNAPSHOT_NOT_READY"):
        repo.load(snap.snapshot_id)
    assert repo.delete_unpublished("foreign") == 0
    assert repo.delete_unpublished("owner") == 1
    repo.publish(snap,"retry")
    assert repo.load(snap.snapshot_id) == snap


def test_migrations_are_repeatable_and_pages_cover_all_contexts(repo, snapshot_factory):
    migrate(repo.driver)
    migrate(repo.driver)
    project = repo.create_project("pages")
    ids=[]
    for i in range(5):
        snap = snapshot_factory(project, ("r",f"n{i}"), (("r",f"n{i}"),),root="r")
        ids.append(repo.publish(snap,"job-"+str(i)))
    cursor=None
    seen=[]
    while True:
        page=repo.list_snapshots(project,cursor,limit=2)
        seen.extend(row["snapshot_id"] for row in page.items)
        cursor=page.next_cursor
        if cursor is None:
            break
    assert set(seen) == set(ids) and len(seen) == 5


def test_exception_between_component_and_edge_writes_cleans_only_owned_stage(repo, public_snapshot_factory, monkeypatch):
    ready = public_snapshot_factory(repo.create_project("protected"))
    repo.publish(ready,"protected-owner")
    candidate = public_snapshot_factory(repo.create_project("interrupted"))
    original = repo.driver.session
    injected = []
    class SessionBoundary:
        def __init__(self):
            self.session = original()
        def __enter__(self):
            self.session.__enter__()
            return self
        def __exit__(self,*args):
            return self.session.__exit__(*args)
        def execute_write(self,*args,**kwargs):
            return self.session.execute_write(*args,**kwargs)
        def run(self, query, **parameters):
            if "MERGE (a)-[e:DEPENDS_ON" in query and not injected:
                injected.append(True)
                raise RuntimeError("constructed connection interruption")
            return self.session.run(query,**parameters)
    monkeypatch.setattr(repo.driver,"session",lambda:SessionBoundary())
    with pytest.raises(RuntimeError, match="connection interruption"):
        repo.publish(candidate,"interrupted-owner")
    with pytest.raises(DomainError, match="SNAPSHOT_NOT_FOUND"):
        repo.load(candidate.snapshot_id)
    assert repo.load(ready.snapshot_id) == ready


def test_cancel_before_write_does_not_publish_or_remove_ready(repo,public_snapshot_factory):
    protected=public_snapshot_factory(repo.create_project("keep"))
    repo.publish(protected,"keep-owner")
    candidate=public_snapshot_factory(repo.create_project("cancel"))
    with pytest.raises(DomainError,match="CANCELLED"):
        repo.publish(candidate,"cancel-owner",cancelled=lambda:True)
    assert repo.list_snapshots(candidate.project_id).items == ()
    assert repo.load(protected.snapshot_id) == protected
