from depscope.analysis.aliases import alias_groups


def test_related_is_not_alias_and_withdrawn_is_not_active(advisory_factory):
    a=advisory_factory("GHSA-a",aliases=("CVE-1",),related=("GHSA-b",))
    b=advisory_factory("GHSA-b")
    withdrawn=advisory_factory("GHSA-old",aliases=("CVE-1",),withdrawn="2026-01-01")
    groups=alias_groups((a,b,withdrawn))
    assert groups["GHSA-a"] != groups["GHSA-b"]
    assert "GHSA-old" not in groups


def test_alias_links_are_transitive_and_input_order_independent(advisory_factory):
    records=(advisory_factory("GHSA-a",aliases=("CVE-1",)),
             advisory_factory("PYSEC-b",aliases=("CVE-1","CVE-2")),
             advisory_factory("GHSA-c",aliases=("CVE-2",)))
    groups=alias_groups(records)
    assert groups == alias_groups(tuple(reversed(records)))
    assert groups["GHSA-a"] == groups["GHSA-c"] == ("CVE-1","CVE-2","GHSA-a","GHSA-c","PYSEC-b")
