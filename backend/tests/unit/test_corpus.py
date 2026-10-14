import json
from datetime import datetime
from types import SimpleNamespace
from pathlib import Path
import pytest
from depscope.evaluation.corpus import CorpusCollector
from depscope.sources.records import RecordStore
from depscope.analysis.matching import MatchRun
from depscope.runtime.errors import DomainError


def graph(name, version):
    return json.dumps(
        {
            "nodes": [
                {
                    "versionKey": {"system": "PYPI", "name": name, "version": version},
                    "relation": "SELF",
                },
                {
                    "versionKey": {"system": "PYPI", "name": "requests", "version": "2.32.3"},
                    "relation": "DIRECT",
                },
            ],
            "edges": [{"fromNode": 0, "toNode": 1, "requirement": "requests>=2"}],
        }
    ).encode()


@pytest.fixture
def corpus_factory(tmp_path):
    class Snapshots:
        def __init__(self):
            self.values = {}
            self.projects = {}

        def create_project(self, name, kind):
            self.projects[name] = name
            return name

        def publish(self, snapshot, owner, **kwargs):
            self.values[snapshot.snapshot_id] = snapshot
            return snapshot.snapshot_id

        def load(self, id):
            return self.values[id]

    snapshots = Snapshots()

    class Runs:
        def __init__(self):
            self.values = {}

        def load(self, id):
            return self.values[id]

        def revision(self, id):
            raise AssertionError("No constructed advisory data")

    runs = Runs()

    class Matching:
        async def collect(self, sids, collection):
            values = {
                sid: MatchRun(
                    id="run-" + sid,
                    snapshot_id=sid,
                    collection_id=collection,
                    observed_at="2026-10-13T00:00:00Z",
                    queries=(),
                    findings=(),
                    revision_ids=(),
                    coverage={"total": 0, "confirmed": 0, "unknown": 0, "active_findings": 0},
                )
                for sid in sids
            }
            runs.values.update({r.id: r for r in values.values()})
            return values

    comparisons = SimpleNamespace(save=lambda c: None)
    services = SimpleNamespace(
        snapshots=snapshots,
        runs=runs,
        match_service=Matching(),
        comparisons=comparisons,
        records=RecordStore(tmp_path / "records-root"),
    )

    async def build(
        missing_year=("langgraph", 2024), resolution_error=("mlflow", "3.0"), partial_graph=False
    ):
        class Public:
            async def get_raw(self, uri, cancelled=lambda: False):
                if uri.startswith("https://pypi.org"):
                    name = uri.split("/")[-2]
                    releases = {
                        "1.0": [{"upload_time_iso_8601": "2024-01-02T00:00:00Z", "yanked": False}],
                        "2.0": [{"upload_time_iso_8601": "2025-01-02T00:00:00Z", "yanked": False}],
                        "3.0": [{"upload_time_iso_8601": "2026-01-02T00:00:00Z", "yanked": False}],
                    }
                    if name == missing_year[0]:
                        releases.pop("1.0")
                    return json.dumps({"info": {"name": name}, "releases": releases}).encode()
                name = uri.split("/packages/")[1].split("/")[0]
                version = uri.split("/versions/")[1].split(":")[0]
                if (name, version) == resolution_error:
                    raise DomainError("SOURCE_HTTP_ERROR", "Constructed resolution failure")
                raw = graph(name, version)
                if partial_graph and name == "mlflow" and version == "3.0":
                    value = json.loads(raw)
                    value["error"] = "Constructed partial resolution"
                    raw = json.dumps(value).encode()
                return raw

        collector = CorpusCollector(services, Public(), tmp_path / "checkpoint")
        return await collector.collect(
            ("langgraph", "mlflow"), datetime.fromisoformat("2026-10-13T23:59:59-05:00")
        )

    return build


async def test_corpus_preserves_selection_failures(corpus_factory):
    manifest = await corpus_factory()
    assert any(
        row["reason"] == "missing_year" and row["package"] == "langgraph" and row["year"] == 2024
        for row in manifest.exclusions
    )
    assert any(
        row["reason"] == "resolution_error"
        and row["package"] == "mlflow"
        and row["version"] == "3.0"
        for row in manifest.exclusions
    )
    assert manifest.actual_counts["successful_snapshots"] == 4
    assert manifest.actual_counts["selected_versions"] == 5
    assert manifest.actual_counts["successful_snapshots"] < 45
    assert {c.version for c in manifest.cases if c.package == "langgraph"} == {"2.0", "3.0"}
    assert all(
        c.family_name == "langchain_family" for c in manifest.cases if c.package == "langgraph"
    )


async def test_corpus_resume_keeps_first_frozen_source_selection(corpus_factory):
    first = await corpus_factory()
    second = await corpus_factory(resolution_error=("never", "never"))
    assert (
        second.id == first.id
        and second.cases == first.cases
        and second.exclusions == first.exclusions
    )


async def test_partial_resolution_is_preserved_but_not_counted_as_complete_success(corpus_factory):
    manifest = await corpus_factory(resolution_error=("never", "never"), partial_graph=True)
    assert len(manifest.cases) == 5
    assert manifest.actual_counts["published_snapshots"] == 5
    assert manifest.actual_counts["successful_snapshots"] == 4
    assert manifest.actual_counts["partial_or_unknown_snapshots"] == 1
    assert any(
        row["reason"] == "partial_resolution" and row["package"] == "mlflow"
        for row in manifest.exclusions
    )
