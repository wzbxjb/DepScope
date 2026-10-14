import json
from collections import Counter

import pytest

from depscope.evaluation.benchmark import build_benchmark
from depscope.evaluation.corpus import CorpusManifest
from depscope.evaluation.freeze import freeze_suite, verify_suite
from depscope.runtime.config import PROJECT_ROOT
from depscope.runtime.errors import DomainError


def test_frozen_benchmark_has_no_family_leakage():
    home = PROJECT_ROOT / "artifacts/corpus"
    manifest = CorpusManifest.model_validate_json((home / "manifest.json").read_bytes())
    questions = build_benchmark(manifest, home)
    dev = [q for q in questions if q.split == "dev"]
    test = [q for q in questions if q.split == "test"]
    assert len(dev) == 60 and len(test) == 140
    assert (
        set()
        .union(*(set(q.family_names) for q in dev))
        .isdisjoint(set().union(*(set(q.family_names) for q in test)))
    )
    assert Counter(q.kind for q in questions) == {
        "single": 40,
        "path": 60,
        "cross": 40,
        "comparison": 40,
        "missing": 20,
    }
    assert all(
        q.source_ids
        and q.label_origin == "program_reference"
        and q.review_status == "not_human_reviewed"
        for q in questions
    )
    assert len({q.id for q in questions}) == 200
    assert (
        len(
            {
                json.dumps([q.reference_locators, q.expected_facts], sort_keys=True)
                for q in questions
            }
        )
        == 200
    )


def test_freeze_rejects_unrecorded_question_or_configuration_changes(tmp_path):
    suite = freeze_suite((), {"corpus_digest": "a" * 64, "model": "fixed"}, tmp_path)
    verify_suite(suite)
    (tmp_path / "config.json").write_text("{}")
    with pytest.raises(DomainError, match="FROZEN_SUITE_MODIFIED"):
        verify_suite(suite)


def test_path_labels_only_select_unambiguous_shortest_reference_paths():
    import networkx as nx

    from depscope.evaluation.reference import RawReference, instance

    home = PROJECT_ROOT / "artifacts/corpus"
    manifest = CorpusManifest.model_validate_json((home / "manifest.json").read_bytes())
    questions = build_benchmark(manifest, home)
    reference = RawReference(home)
    cases = {c.snapshot_id: c for c in manifest.cases}
    for q in questions:
        for fact in q.expected_facts:
            if fact["kind"] != "path":
                continue
            sid = fact["value"]["snapshot_id"]
            doc, graph = reference.graph(cases[sid])
            end = fact["value"]["instance_ids"][-1]
            target = next(i for i in graph if instance(sid, i) == end)
            assert sum(1 for _ in nx.all_shortest_paths(graph, 0, target)) == 1


def test_single_questions_include_original_advisory_query_status_facts():
    home = PROJECT_ROOT / "artifacts/corpus"
    manifest = CorpusManifest.model_validate_json((home / "manifest.json").read_bytes())
    questions = build_benchmark(manifest, home)
    query_questions = [
        q for q in questions if q.kind == "single" and q.expected_facts[0]["kind"] == "query"
    ]
    assert len(query_questions) >= 5
    assert all(len(q.source_ids) >= 3 for q in query_questions)


def test_frozen_suite_can_relocate_without_changing_experiment_identity(tmp_path):
    import shutil

    first_home = tmp_path / "first"
    second_home = tmp_path / "second"
    config = {"corpus_digest": "a" * 64, "model": "fixed"}
    first = freeze_suite((), config, first_home)
    shutil.copytree(first_home, second_home)
    shutil.rmtree(first_home)
    second = freeze_suite((), config, second_home)
    verify_suite(second)
    assert second.digest == first.digest and second.output_path == str(second_home.resolve())
