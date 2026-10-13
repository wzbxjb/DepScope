import pytest

from depscope.identity.coordinates import identify, instance_key, snapshot_key
from depscope.runtime.errors import DomainError


def test_conflicting_purl_is_not_silently_preferred():
    assert identify("LangChain_Core", "0.1.23", None).name == "langchain-core"
    with pytest.raises(DomainError, match="COORDINATE_CONFLICT"):
        identify("langchain-core", "0.1.23", "pkg:pypi/requests@2.32.3")
    assert identify("opaque-library", None, None) is None


@pytest.mark.parametrize("version, canonical", [
    ("v1.0RC1", "1.0rc1"), ("1.0+LOCAL.2", "1.0+local.2"),
    ("1!2.0.post1", "1!2.0.post1"),
])
def test_pep440_keeps_source_version(version, canonical):
    coordinate = identify("Some_Pkg", version, None)
    assert coordinate.version == canonical
    assert coordinate.raw_version == version


def test_invalid_versions_and_non_pypi_purls_remain_opaque():
    assert identify("pkg", "not-a-version", None) is None
    assert identify("requests", "2.32.3", "pkg:npm/requests@2.32.3") is None


def test_purl_can_supply_missing_version_and_validate_normalized_identity():
    assert identify("LangChain_Core", None, "pkg:pypi/langchain-core@0.1.23").version == "0.1.23"
    assert identify("requests", "v2.32.3", "pkg:pypi/requests@2.32.3").raw_version == "v2.32.3"
    with pytest.raises(DomainError, match="COORDINATE_CONFLICT"):
        identify("requests", "2.32.3", "pkg:pypi/requests@2.31.0")
    with pytest.raises(DomainError, match="PURL_INVALID"):
        identify("requests", "2.32.3", "invalid-purl")


def test_context_keys_are_deterministic_and_unambiguous():
    assert snapshot_key("a", "public_resolution", "f"*64) == snapshot_key("a", "public_resolution", "f"*64)
    assert snapshot_key("a", "public_resolution", "f"*64) != snapshot_key("a", "observed_environment", "f"*64)
    assert instance_key("a:b", "c") != instance_key("a", "b:c")
    assert instance_key("snap-a", "same") != instance_key("snap-b", "same")
