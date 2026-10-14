import pytest

from depscope.analysis.producer import normalize_owned_sbom
from depscope.runtime.errors import DomainError


def test_only_proven_owned_distribution_merges_with_application_root(tmp_path):
    project = tmp_path / "application"
    project.mkdir()
    bom = {
        "metadata": {
            "component": {
                "bom-ref": "app",
                "name": "private-app",
                "version": "1.0",
                "type": "application",
            }
        },
        "components": [
            {"bom-ref": "dist", "name": "private-app", "version": "1.0", "type": "library"},
            {"bom-ref": "one", "name": "requests", "version": "2.32.3", "type": "library"},
            {"bom-ref": "two", "name": "requests", "version": "2.32.3", "type": "library"},
        ],
        "dependencies": [
            {"ref": "app", "dependsOn": ["dist"]},
            {"ref": "dist", "dependsOn": ["one", "two"]},
            {"ref": "one", "dependsOn": []},
            {"ref": "two", "dependsOn": []},
        ],
    }
    inspect = {
        "installed": [
            {
                "metadata": {"name": "private-app", "version": "1.0"},
                "direct_url": {"url": project.as_uri(), "dir_info": {"editable": True}},
            }
        ]
    }
    normalized, audit = normalize_owned_sbom(bom, inspect, project)
    assert len(normalized["components"]) == 2
    assert normalized["metadata"]["component"]["properties"][0]["value"] == "private-application"
    assert next(row for row in normalized["dependencies"] if row["ref"] == "app")["dependsOn"] == [
        "one",
        "two",
    ]
    assert audit["merged_distribution_ref"] == "dist"
    inspect["installed"][0]["direct_url"]["url"] = (tmp_path / "foreign").as_uri()
    with pytest.raises(DomainError):
        normalize_owned_sbom(bom, inspect, project)


def test_unknown_environment_target_cannot_execute_a_command(tmp_path):
    from depscope.analysis.environment_runner import target_paths

    with pytest.raises(DomainError, match="UNTRUSTED_PRODUCER"):
        target_paths("uploaded-arbitrary-command", tmp_path)


def test_dependency_audit_uses_active_installed_metadata_and_rejects_missing_distribution():
    from depscope.analysis.producer import reconcile_installed_dependencies

    doc = {
        "metadata": {"component": {"bom-ref": "root", "name": "app", "version": "1.0"}},
        "components": [{"bom-ref": "lib", "name": "requests", "version": "2.32.3"}],
        "dependencies": [{"ref": "root", "dependsOn": []}, {"ref": "lib"}],
    }
    inspect = {
        "installed": [
            {
                "metadata": {
                    "name": "app",
                    "version": "1.0",
                    "requires_dist": ["requests>=2", 'absent; extra == "optional"'],
                }
            },
            {"metadata": {"name": "requests", "version": "2.32.3"}},
        ]
    }
    result, declarations, audit = reconcile_installed_dependencies(
        doc, inspect, {"extras": [], "marker_environment": {}}
    )
    assert audit["tool_missing_edges"] == [["root", "lib"]]
    assert result["dependencies"] == [
        {"ref": "lib", "dependsOn": []},
        {"ref": "root", "dependsOn": ["lib"]},
    ]
    assert declarations[0]["original_requirement"] == "requests>=2"
    inspect["installed"][0]["metadata"]["requires_dist"].append("missing>=1")
    with pytest.raises(DomainError, match="INSTALLED_CONSTRAINT_FAILURE"):
        reconcile_installed_dependencies(doc, inspect, {"extras": [], "marker_environment": {}})
