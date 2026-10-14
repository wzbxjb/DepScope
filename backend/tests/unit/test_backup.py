import json

import pytest

from depscope.operations.backup import BackupManager, verify_backup
from depscope.runtime.errors import DomainError


def test_restore_requires_a_new_instance_before_any_command(tmp_path):
    manager = BackupManager(tmp_path, None)
    with pytest.raises(DomainError, match="NEW_INSTANCE_REQUIRED"):
        manager.restore(tmp_path, new_instance=False, instance="existing")


def test_backup_digest_and_path_checks_precede_database_loading(tmp_path):
    (tmp_path / "neo4j.dump").write_bytes(b"constructed offline dump")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "format": "depscope-private-backup-v1",
                "image": "untrusted-upload-image",
                "hashes": {"../outside": "a" * 64},
            }
        )
    )
    with pytest.raises(DomainError, match="INVALID_BACKUP"):
        verify_backup(tmp_path)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"format": "depscope-private-backup-v1", "hashes": {"neo4j.dump": "a" * 64}})
    )
    with pytest.raises(DomainError, match="INVALID_BACKUP"):
        verify_backup(tmp_path)
