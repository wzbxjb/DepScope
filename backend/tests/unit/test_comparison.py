import pytest

from depscope.analysis.comparison import compare_known_findings, compare_packages
from depscope.analysis.verification import verification_level
from depscope.identity.coordinates import identify


def test_failed_query_cannot_be_counted_as_removed_match(comparison_inputs):
    before,after,bs,as_=comparison_inputs("matched","error")
    result=compare_known_findings(before,after,bs,as_)
    assert result.removed_known_matches==0 and result.unknown==1


def test_complete_no_match_can_remove_known_group_but_partial_cannot(comparison_inputs):
    before,after,bs,as_=comparison_inputs("matched","no_match")
    assert compare_known_findings(before,after,bs,as_).removed_known_matches == 1
    before,after,bs,as_=comparison_inputs("matched","partial")
    assert compare_known_findings(before,after,bs,as_).removed_known_matches == 0


def test_removed_package_requires_complete_candidate_graph(comparison_inputs):
    before,after,bs,as_=comparison_inputs("matched","no_match")
    empty=as_.model_copy(update={"components":(),"edges":(),"root_id":None})
    empty_run=after.model_copy(update={"queries":(),"findings":()})
    result=compare_known_findings(before,empty_run,bs,empty)
    assert result.removed_known_matches==0 and result.unknown==1


def test_package_diff_preserves_multiple_versions_and_opaque_counts(comparison_inputs):
    before,after,bs,as_=comparison_inputs("matched","no_match")
    another=bs.components[0].model_copy(update={"local_id":"other","coordinate":identify("requests","2.30.0",None)})
    bs=bs.model_copy(update={"components":bs.components+(another,)})
    diff=compare_packages(bs,as_)
    assert diff.versions_changed[0].before == ("2.30.0","2.31.0")
    assert diff.versions_changed[0].after == ("2.32.3",)
    assert diff.environment_comparable is False


@pytest.mark.parametrize('resolution,tests,env,constraints,expected',[
    (False,True,True,True,"metadata_comparison"),
    (True,True,False,True,"metadata_comparison"),
    (True,True,True,False,"metadata_comparison"),
    (True,False,True,True,"resolution_verified"),
    (True,True,True,True,"tests_verified"),
])
def test_levels_require_all_evidence_conditions(resolution,tests,env,constraints,expected):
    assert verification_level(resolution,tests,env,constraints)==expected
