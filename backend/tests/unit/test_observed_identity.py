import json

from depscope.analysis.verification import constraints_satisfied
from depscope.identity.coordinates import identify, snapshot_key
from depscope.ingest.cyclonedx import parse_cyclonedx
from depscope.ingest.models import Component, Edge, Snapshot


def test_explicit_private_application_is_not_a_public_pypi_package(source_for):
    doc = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "depscope",
                "version": "0.1.0",
                "bom-ref": "root",
                "properties": [{"name": "depscope:identity-scope", "value": "private-application"}],
            }
        },
        "components": [],
        "dependencies": [{"ref": "root", "dependsOn": []}],
    }
    raw = json.dumps(doc).encode()
    snapshot = parse_cyclonedx(raw, "p", source_for(raw), {})
    assert snapshot.components[0].coordinate is None
    assert snapshot.environment["private_application_root"] is True


def test_only_explicit_private_root_can_be_opaque_in_constraint_verification(source_for):
    source = source_for(b"constructed-private-boundary")
    root = Component(
        local_id="root",
        name="depscope",
        coordinate=None,
        dependencies_known=True,
        pointer="/metadata/component",
    )
    library = Component(
        local_id="lib",
        name="requests",
        coordinate=identify("requests", "2.32.3", None),
        dependencies_known=True,
        pointer="/components/0",
    )
    snapshot = Snapshot(
        snapshot_id=snapshot_key("p", "constructed", source.digest),
        project_id="p",
        source_kind="constructed",
        source=source,
        components=(root, library),
        edges=(
            Edge(from_id="root", to_id="lib", requirement="requests>=2", pointer="/dependencies/0"),
        ),
        root_id="root",
        environment={"private_application_root": True},
    )
    assert constraints_satisfied(snapshot, [])
    assert not constraints_satisfied(snapshot.model_copy(update={"environment": {}}), [])
    assert not constraints_satisfied(
        snapshot.model_copy(
            update={"components": (root, library.model_copy(update={"coordinate": None}))}
        ),
        [],
    )
