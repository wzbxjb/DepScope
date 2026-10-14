from depscope.evaluation.metrics import cluster_interval, evidence_recall, score_answer
from depscope.investigation.answers import Answer


def test_empty_gold_is_unavailable_and_service_failure_is_not_correct_abstention():
    assert evidence_recall(set(), {"x"}) is None
    question = {"kind": "missing", "expected_facts": [], "required_evidence": []}
    assert score_answer(question, Answer(status="generation_error"))["correct_abstention"] is False
    assert (
        score_answer(question, Answer(status="insufficient_evidence"))["correct_abstention"] is True
    )


def test_family_interval_is_reproducible_and_retains_actual_group_count():
    rows = [{"cluster": "one", "delta": 1.0}, {"cluster": "two", "delta": -1.0}]
    result = cluster_interval(rows)
    assert result == cluster_interval(rows) and result["groups"] == 2
    assert result["unstable"] is True and result["replicates"] == 1000
