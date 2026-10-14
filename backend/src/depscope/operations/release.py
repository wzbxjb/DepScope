"""Evidence gates for a local release; no commands are read from uploaded documents."""

import hashlib
import hmac
import json
import os
from pathlib import Path

from depscope.ingest.models import Contract
from depscope.runtime.errors import DomainError


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def check_key(data_root, create=False):
    path = Path(data_root) / "verifications/release-signing-key"
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(os.urandom(32))
        except FileExistsError:
            pass
    return path.read_bytes()


def sign_check(payload, data_root):
    return {
        "payload": payload,
        "signature": hmac.new(
            check_key(data_root, True), canonical(payload), hashlib.sha256
        ).hexdigest(),
    }


def source_digest(root):
    root = Path(root)
    files = []
    for folder in (
        "backend/src",
        "backend/tests",
        "frontend/src",
        "frontend/tests",
        "frontend/e2e",
        "schemas",
        "migrations",
        "scripts",
    ):
        files.extend(
            p
            for p in (root / folder).rglob("*")
            if p.is_file()
            and p.suffix in (".py", ".ts", ".tsx", ".css", ".json", ".cypher")
            and "__pycache__" not in p.parts
        )
    for name in (
        "compose.yaml",
        "compose.embeddings.yaml",
        ".dockerignore",
        "backend/Dockerfile",
        "backend/pyproject.toml",
        "backend/requirements-runtime.lock",
        "backend/requirements-dev.lock",
        "frontend/Dockerfile",
        "frontend/nginx.conf",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/playwright.config.ts",
        "frontend/vite.config.ts",
    ):
        if (root / name).is_file():
            files.append(root / name)
    return hashlib.sha256(
        canonical(
            {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(set(files))
            }
        )
    ).hexdigest()


def verify_check(record, data_root, source_root=None):
    try:
        expected = hmac.new(
            check_key(data_root), canonical(record["payload"]), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, record["signature"]):
            raise ValueError
        if source_root is not None and record["payload"].get("source_digest") != source_digest(
            source_root
        ):
            raise ValueError
        return record["payload"]
    except (OSError, ValueError, KeyError, TypeError):
        raise DomainError("UNTRUSTED_CHECK", "Release check is unsigned or modified") from None


class ReleaseManifest(Contract):
    commit: str
    dependencies: dict
    images: dict
    source_manifest: dict
    verification_runs: tuple[dict, ...]
    experiment_runs: tuple[dict, ...]
    checks: dict
    limitations: tuple[str, ...]


def verify_release(root):
    root = Path(root)
    required = (
        "compose.yaml",
        "backend/Dockerfile",
        "frontend/Dockerfile",
        "README.md",
        "README.zh-CN.md",
        "docs/operations/setup.md",
        "docs/operations/backup.md",
        "docs/operations/verification.md",
        "docs/portfolio/demo_script.md",
        "docs/portfolio/resume_evidence.md",
        "artifacts/verification/container-images.json",
        "artifacts/verification/clean-reproduction.json",
        "artifacts/verification/restore-validation.json",
        "artifacts/verification/full-workflow-result.json",
        "artifacts/verification/product-demo.webm",
    )
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise DomainError(
            "RELEASE_INCOMPLETE",
            "Required release evidence is missing",
            tuple("/" + name for name in missing),
        )
    from depscope.api.services import build_services
    from depscope.evaluation.corpus import CorpusManifest, _digest
    from depscope.evaluation.experiments import ExperimentRepository
    from depscope.evaluation.freeze import FrozenSuite, verify_suite
    from depscope.runtime.config import load_settings

    settings = load_settings()
    container = build_services(settings)
    try:
        manifest = CorpusManifest.model_validate_json(
            (root / "artifacts/corpus/manifest.json").read_bytes()
        )
        if _digest(manifest.model_dump(mode="json", exclude={"id"})) != manifest.id:
            raise DomainError("RELEASE_INCOMPLETE", "Corpus manifest changed")
        for digest in manifest.source_hashes.values():
            if (
                hashlib.sha256((root / "artifacts/corpus/raw" / digest).read_bytes()).hexdigest()
                != digest
            ):
                raise DomainError("RELEASE_INCOMPLETE", "Raw corpus record changed")
        home = root / "artifacts/benchmark/v1"
        suite = FrozenSuite.model_validate_json((home / "suite.json").read_bytes()).model_copy(
            update={"output_path": str(home.resolve())}
        )
        verify_suite(suite)
        questions = json.loads((home / "questions.json").read_bytes())
        dev = [q for q in questions if q["split"] == "dev"]
        test = [q for q in questions if q["split"] == "test"]
        families = lambda rows: set().union(*(set(q["family_names"]) for q in rows))
        experiment = ExperimentRepository(
            root / "artifacts/experiments", container.investigation.ledger, container.records
        ).load("benchmark-v1-20261014")["manifest"]
        reports = []
        for name in (
            "backend-tests",
            "frontend-build",
            "browser-full",
            "browser-live",
            "docker-build",
            "docker-start",
        ):
            record = json.loads(
                (root / "artifacts/verification/checks" / (name + ".json")).read_bytes()
            )
            payload = verify_check(record, settings.data_root, source_root=root)
            if payload["name"] != name or payload["exit_code"] != 0:
                raise DomainError("RELEASE_INCOMPLETE", "A required verification command failed")
            container.records.get(payload["log_digest"])
            reports.append(payload)
        observed = []
        for name in ("backend", "example"):
            evidence = json.loads(
                (root / f"artifacts/corpus/{name}-verification-summary.json").read_bytes()
            )
            snapshot = container.snapshots.load(evidence["snapshot_id"])
            level = container.verifications.level(snapshot, snapshot, evidence["verification_id"])
            if snapshot.source_kind != "observed_environment" or level != "tests_verified":
                raise DomainError(
                    "RELEASE_INCOMPLETE", "Actual environment verification is unavailable"
                )
            observed.append(evidence)
        restore = json.loads((root / "artifacts/verification/restore-validation.json").read_bytes())
        clean = json.loads((root / "artifacts/verification/clean-reproduction.json").read_bytes())
        flow = json.loads((root / "artifacts/verification/full-workflow-result.json").read_bytes())
        gates = {
            "A1": bool(clean.get("passed")),
            "A2": manifest.actual_counts["successful_snapshots"] >= 2,
            "A3": flow.get("same_file_snapshot_idempotent") is True,
            "A4": len(observed) == 2,
            "A5": any(r["name"] == "backend-tests" for r in reports),
            "A6": flow.get("comparison_level") == "metadata_comparison",
            "A7": any(r["name"] == "browser-live" for r in reports),
            "A8": len(questions) == 200
            and len(dev) == 60
            and len(test) == 140
            and families(dev).isdisjoint(families(test))
            and experiment["usage"]["actual_reserved_calls"] >= 800
            and len(experiment["result_hashes"]) == 800,
            "A9": (root / "docs/evaluation/results.md").exists(),
            "A10": all(
                (root / name).exists()
                for name in (
                    "README.md",
                    "README.zh-CN.md",
                    "docs/portfolio/demo_script.md",
                    "docs/portfolio/resume_evidence.md",
                )
            ),
            "backup_restore": restore.get("graph_and_budget_equal") is True
            and restore.get("source_hashes_equal") is True,
        }
        if not all(gates.values()):
            raise DomainError(
                "RELEASE_INCOMPLETE",
                "Some acceptance gates failed",
                tuple("/" + k for k, v in gates.items() if not v),
            )
        import subprocess

        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        return ReleaseManifest(
            commit=commit,
            dependencies={
                "backend_lock_sha256": hashlib.sha256(
                    (root / "backend/requirements-runtime.lock").read_bytes()
                ).hexdigest(),
                "frontend_lock_sha256": hashlib.sha256(
                    (root / "frontend/package-lock.json").read_bytes()
                ).hexdigest(),
            },
            images=json.loads((root / "artifacts/verification/container-images.json").read_bytes()),
            source_manifest={
                "corpus_id": manifest.id,
                "counts": manifest.actual_counts,
                "observed_environments": observed,
            },
            verification_runs=tuple(reports),
            experiment_runs=(experiment,),
            checks=gates,
            limitations=(
                "Local repository; no remote publication or user-study/business-impact claim.",
                "Program reference labels, no human semantic audit; test has seven underlying families and overlapping composite bootstrap labels.",
                "Graph expansion did not improve on hybrid in this frozen run. Provider alias/default sampling is not a deterministic backend version.",
                "Known-advisory matching does not establish exploitability or safety. Observed environment tests do not prove an upgrade.",
                "Estimated generation cost is a peak-rate upper bound, not a supplier invoice.",
            ),
        )
    finally:
        container.close()
