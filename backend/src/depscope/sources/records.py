"""Content-addressed raw evidence plus an append-only observation journal."""
import fcntl
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from depscope.ingest.models import SourceRef
from depscope.runtime.errors import DomainError


class RecordStore:
    def __init__(self, root: Path, parser_version: str = "raw-v1"):
        self.root = Path(root)
        self.parser_version = parser_version

    def path_for(self, digest: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise DomainError("INVALID_DIGEST", "Digest must be a SHA-256 hex string")
        return self.root / "records" / digest[:2] / digest

    def put(self, raw: bytes, uri: str, observed_at: str) -> SourceRef:
        digest = hashlib.sha256(raw).hexdigest()
        source = SourceRef(uri=uri, digest=digest, observed_at=observed_at,
                           parser_version=self.parser_version)
        path = self.path_for(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.get(digest)
        else:
            descriptor, temporary = tempfile.mkstemp(prefix=".record-", dir=path.parent)
            try:
                with os.fdopen(descriptor, "wb") as file:
                    file.write(raw)
                    file.flush()
                    os.fsync(file.fileno())
                if hashlib.sha256(Path(temporary).read_bytes()).hexdigest() != digest:
                    raise DomainError("RECORD_INTEGRITY", "Temporary record digest mismatch")
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        journal = self.root / "observations.jsonl"
        with journal.open("a", encoding="utf-8") as file:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX)
            file.write(source.model_dump_json() + "\n")
            file.flush()
            os.fsync(file.fileno())
        return source

    def get(self, digest: str) -> bytes:
        path = self.path_for(digest)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raise DomainError("RECORD_NOT_FOUND", "Raw evidence is unavailable") from None
        if hashlib.sha256(raw).hexdigest() != digest:
            raise DomainError("RECORD_INTEGRITY", "Raw evidence digest mismatch")
        return raw

    def observations(self, digest: str) -> tuple[SourceRef, ...]:
        self.path_for(digest)
        journal = self.root / "observations.jsonl"
        if not journal.exists():
            return ()
        with journal.open(encoding="utf-8") as file:
            fcntl.flock(file.fileno(), fcntl.LOCK_SH)
            return tuple(SourceRef.model_validate_json(line) for line in file
                         if json.loads(line)["digest"] == digest)
