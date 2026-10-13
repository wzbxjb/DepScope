import copy
import json

import pytest

from depscope.ingest.cyclonedx import parse_cyclonedx
from depscope.ingest.limits import async_read_limited, read_limited
from depscope.runtime.errors import DomainError

BOM = {
    "bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
    "metadata": {"component": {"type": "application", "name": "fixture", "bom-ref": "root"}},
    "components": [{"type": "library", "name": "requests", "version": "2.32.3", "bom-ref": "lib"}],
    "dependencies": [{"ref": "root", "dependsOn": ["lib"]}],
}


@pytest.fixture
def bom():
    return copy.deepcopy(BOM)


def parse(bom, source_for):
    raw = json.dumps(bom).encode()
    return parse_cyclonedx(raw, "p", source_for(raw), {})


def test_absent_dependency_record_is_unknown(bom, source_for):
    snap = parse(bom, source_for)
    assert not next(c for c in snap.components if c.local_id == "lib").dependencies_known
    bom["dependencies"].append({"ref": "lib", "dependsOn": []})
    assert next(c for c in parse(bom, source_for).components if c.local_id == "lib").dependencies_known


def test_ref_without_depends_on_is_unknown(bom, source_for):
    bom["dependencies"].append({"ref": "lib"})
    assert not parse(bom, source_for).components[1].dependencies_known


def test_stream_limit_uses_observed_bytes():
    with pytest.raises(DomainError, match="UPLOAD_TOO_LARGE"):
        read_limited(iter([b"a" * 6_000_000, b"b" * 6_000_000]))
    assert read_limited([b"ab", b"c"], limit=3) == b"abc"


async def test_async_stream_stops_at_first_excess_chunk():
    consumed = []
    async def chunks():
        for chunk in [b"ab", b"cd", b"never"]:
            consumed.append(chunk)
            yield chunk
    with pytest.raises(DomainError, match="UPLOAD_TOO_LARGE"):
        await async_read_limited(chunks(), limit=3)
    assert consumed == [b"ab", b"cd"]


def test_unsupported_version_and_invalid_schema_report_pointers(bom, source_for):
    bom["specVersion"] = "1.7"
    with pytest.raises(DomainError, match="UNSUPPORTED_FORMAT"):
        parse(bom, source_for)
    bom["specVersion"] = "1.6"
    bom["components"][0]["type"] = "unknown-type"
    with pytest.raises(DomainError) as exc:
        parse(bom, source_for)
    assert exc.value.pointers == ("/components/0/type",)


def test_root_and_nested_duplicate_ids_are_rejected(bom, source_for):
    bom["components"][0]["components"] = [{"type":"library", "name":"nested", "bom-ref":"root"}]
    with pytest.raises(DomainError, match="DUPLICATE_COMPONENT") as exc:
        parse(bom, source_for)
    assert "/components/0/components/0/bom-ref" in exc.value.pointers


def test_dangling_refs_and_conflicting_purls_are_rejected(bom, source_for):
    bom["dependencies"][0]["dependsOn"] = ["missing"]
    with pytest.raises(DomainError, match="DANGLING_EDGE") as exc:
        parse(bom, source_for)
    assert exc.value.pointers == ("/dependencies/0/dependsOn/0",)
    bom["dependencies"][0]["dependsOn"] = ["lib"]
    bom["components"][0]["purl"] = "pkg:pypi/other@1.0"
    with pytest.raises(DomainError, match="COORDINATE_CONFLICT") as exc:
        parse(bom, source_for)
    assert exc.value.pointers == ("/components/0/purl",)


def test_cycles_opaque_components_and_missing_root_are_preserved(bom, source_for):
    bom["components"][0]["purl"] = "pkg:npm/requests@2.32.3"
    bom["dependencies"].append({"ref":"lib", "dependsOn":["root"]})
    snap = parse(bom, source_for)
    assert snap.components[1].coordinate is None
    assert len(snap.edges) == 2 and snap.root_id == "root"
    del bom["metadata"]
    bom["dependencies"] = [{"ref":"lib", "dependsOn":[]}]
    assert parse(bom, source_for).root_id is None


def test_external_references_and_schema_url_never_fetch(bom, source_for, respx_mock):
    bom["$schema"] = "https://attacker.example/schema.json"
    bom["externalReferences"] = [{"type":"website", "url":"http://127.0.0.1/private"}]
    assert len(parse(bom, source_for).components) == 2
    assert len(respx_mock.calls) == 0


def test_component_limit_includes_metadata_root(bom, source_for):
    bom["components"] = [{"type":"library", "name":f"lib-{i}", "bom-ref":str(i)} for i in range(10000)]
    bom["dependencies"] = []
    with pytest.raises(DomainError, match="LIMIT_EXCEEDED"):
        parse(bom, source_for)


def test_edge_limit_rejects_whole_graph(bom, source_for):
    bom["components"] = [{"type":"library", "name":f"lib-{i}", "bom-ref":str(i)} for i in range(224)]
    refs = [str(i) for i in range(224)]
    bom["dependencies"] = [{"ref":str(i), "dependsOn":refs} for i in range(224)]
    with pytest.raises(DomainError, match="LIMIT_EXCEEDED"):
        parse(bom, source_for)


def test_components_without_bom_ref_have_distinct_local_instances(bom, source_for):
    del bom["components"][0]["bom-ref"]
    bom["dependencies"] = []
    snap = parse(bom, source_for)
    assert len({c.local_id for c in snap.components}) == 2
    assert snap.components[1].pointer == "/components/0"


def test_source_digest_mismatch_is_rejected(bom, source_for):
    raw=json.dumps(bom).encode()
    with pytest.raises(DomainError, match="SOURCE_DIGEST_MISMATCH"):
        parse_cyclonedx(raw, "p", source_for(b"different"), {})
