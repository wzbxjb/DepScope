import pytest

from depscope.operations.release import verify_check, verify_release
from depscope.runtime.errors import DomainError


def test_release_refuses_missing_evidence_instead_of_claiming_completion(tmp_path):
    with pytest.raises(DomainError, match="RELEASE_INCOMPLETE"):
        verify_release(tmp_path)


def test_uploaded_unsigned_success_is_not_a_verified_check(tmp_path):
    with pytest.raises(DomainError, match="UNTRUSTED_CHECK"):
        verify_check(
            {"payload": {"exit_code": 0, "command": ["uploaded-command"]}, "signature": "invented"},
            tmp_path,
        )


def test_verified_check_is_bound_to_the_tested_source_tree(tmp_path):
    from depscope.operations.release import sign_check, source_digest

    source = tmp_path / "source"
    (source / "backend/src").mkdir(parents=True)
    file = source / "backend/src/fixture.py"
    file.write_text("value = 1\n")
    record = sign_check({"source_digest": source_digest(source), "exit_code": 0}, tmp_path / "data")
    verify_check(record, tmp_path / "data", source_root=source)
    file.write_text("value = 2\n")
    with pytest.raises(DomainError, match="UNTRUSTED_CHECK"):
        verify_check(record, tmp_path / "data", source_root=source)
