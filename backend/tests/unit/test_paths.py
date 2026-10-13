import networkx as nx

from depscope.analysis.paths import shortest_path
from depscope.ingest.depsdev import parse_depsdev


def test_cycle_terminates_without_cross_snapshot_path(snapshot_factory):
    a=snapshot_factory("a",("r","x","y"),(("r","x"),("x","y"),("y","x")),root="r")
    b=snapshot_factory("b",("x","z"),(("x","z"),),root="x")
    assert shortest_path(a,"y") == ("r","x","y")
    assert shortest_path(a,"z") is None
    assert shortest_path(b,"z") == ("x","z")


def test_missing_root_and_disconnected_targets_stay_unknown(snapshot_factory):
    snapshot=snapshot_factory("unknown",("a","b"),(("a","b"),),root=None)
    assert shortest_path(snapshot,"b") is None
    snapshot=snapshot_factory("disconnected",("a","b"),(),root="a")
    assert shortest_path(snapshot,"b") is None
    assert shortest_path(snapshot,"a") == ("a",)


def verify_against_networkx(snapshot):
    graph=nx.DiGraph()
    graph.add_nodes_from(c.local_id for c in snapshot.components)
    graph.add_edges_from((e.from_id,e.to_id) for e in snapshot.edges)
    for target in graph.nodes:
        path=shortest_path(snapshot,target)
        if nx.has_path(graph,snapshot.root_id,target):
            assert len(path)-1 == nx.shortest_path_length(graph,snapshot.root_id,target)
            assert path[0]==snapshot.root_id and path[-1]==target
            assert all(graph.has_edge(a,b) for a,b in zip(path,path[1:],strict=False))
        else:
            assert path is None


def test_real_graphs_match_independent_oracle(research_dir,source_for):
    for file in ("experimental_dependencies.json","langchain_dependencies.json"):
        raw=(research_dir/file).read_bytes()
        verify_against_networkx(parse_depsdev(raw,"oracle",source_for(raw)))


def test_constructed_branching_graph_matches_oracle(snapshot_factory):
    ids=tuple(str(i) for i in range(80))
    edges=tuple((str(i),str(j)) for i in range(80) for j in range(80) if (i*31+j*17)%67==0)
    verify_against_networkx(snapshot_factory("branching",ids,edges,root="0"))


def test_unknown_dependencies_and_missing_root_are_not_complete(snapshot_factory):
    from depscope.analysis.metrics import completeness
    snapshot=snapshot_factory("partial",("r","x"),(("r","x"),),root="r")
    changed=snapshot.model_copy(update={"components":(snapshot.components[0],snapshot.components[1].model_copy(update={"dependencies_known":False}))})
    assert completeness(changed).state == "partial"
    assert completeness(changed).unknown_dependencies == 1
    assert completeness(snapshot.model_copy(update={"root_id":None})).state == "unknown"
