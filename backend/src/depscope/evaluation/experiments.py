"""Only DB-anchored, content-verified runs are displayed as experiments."""

import hashlib
import json
import re
from pathlib import Path

from depscope.evaluation.models import ExperimentManifest
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import Page, decode_cursor, encode_cursor, now, page_limit


class ExperimentRepository:
    def __init__(self, root, ledger, records=None):
        self.root = Path(root)
        self.ledger = ledger
        self.records = records

    def load(self, id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", id):
            raise DomainError("EXPERIMENT_NOT_FOUND", "Experiment is unavailable")
        try:
            raw = (self.root / id / "manifest.json").read_bytes()
            manifest = ExperimentManifest.model_validate_json(raw)
            if manifest.run_id != id or manifest.id != id:
                raise ValueError
            budget = self.ledger.summary(id)
            if budget.call_count < 1:
                raise ValueError
            with self.ledger.driver.session() as session:
                anchor = session.run(
                    "MATCH (r:ExperimentRun {run_id:$id}) RETURN r.manifest_digest AS manifest_digest,r.report_digest AS report_digest",
                    id=id,
                ).single()
            if not anchor or hashlib.sha256(raw).hexdigest() != anchor["manifest_digest"]:
                raise ValueError
            if self.records is not None:
                self.records.get(anchor["manifest_digest"])
            for name, digest in manifest.result_hashes.items():
                if not re.fullmatch(r"[a-f0-9]{64}-(lexical|vector|rrf|graph_rrf)\.json", name):
                    raise ValueError
                if (
                    hashlib.sha256((self.root / id / "results" / name).read_bytes()).hexdigest()
                    != digest
                ):
                    raise ValueError
            report_raw = (self.root / id / "report.json").read_bytes()
            if hashlib.sha256(report_raw).hexdigest() != anchor["report_digest"]:
                raise ValueError
            report = json.loads(report_raw)
            return {"manifest": manifest.model_dump(mode="json"), "report": report}
        except (OSError, ValueError, KeyError, TypeError, DomainError):
            raise DomainError(
                "EXPERIMENT_NOT_FOUND", "No intact recorded experiment is available"
            ) from None

    def list(self, cursor=None, limit=50):
        limit = page_limit(limit)
        last = decode_cursor(cursor, "experiments")
        rows = []
        for directory in sorted(self.root.iterdir()) if self.root.exists() else ():
            if directory.name <= last or not directory.is_dir():
                continue
            try:
                record = self.load(directory.name)
            except DomainError:
                continue
            manifest = record["manifest"]
            rows.append(
                {
                    key: manifest[key]
                    for key in (
                        "id",
                        "run_id",
                        "suite_digest",
                        "status",
                        "usage",
                        "cost",
                        "observed_at",
                    )
                }
            )
            if len(rows) > limit:
                break
        next_cursor = (
            encode_cursor("experiments", rows[limit - 1]["id"]) if len(rows) > limit else None
        )
        return Page(items=tuple(rows[:limit]), next_cursor=next_cursor, observed_at=now())
