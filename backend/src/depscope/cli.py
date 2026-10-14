"""Local operational CLI. Mutations go through the persistent single-worker queue."""

import argparse
import asyncio
import json
from pathlib import Path

from depscope.api.services import build_services
from depscope.evaluation.selection import PUBLIC_ROOTS
from depscope.runtime.config import load_settings
from depscope.runtime.errors import DomainError


async def wait(container, id):
    while True:
        job = await asyncio.to_thread(container.jobs.get, id)
        if job.status in ("ready", "failed", "cancelled", "interrupted"):
            if job.status != "ready":
                raise DomainError(
                    job.error.get("code", "JOB_FAILED") if job.error else "JOB_INTERRUPTED",
                    job.error.get("message", "Job did not complete")
                    if job.error
                    else "Job interrupted; retry explicitly",
                )
            return job
        await asyncio.sleep(1)


async def main():
    parser = argparse.ArgumentParser(prog="depscope")
    commands = parser.add_subparsers(dest="command", required=True)
    corpus = commands.add_parser("collect-corpus")
    corpus.add_argument("--cutoff", required=True)
    corpus.add_argument("--output", type=Path, required=True)
    imported = commands.add_parser("import-file")
    imported.add_argument("file", type=Path)
    imported.add_argument("--project-id", required=True)
    imported.add_argument(
        "--source-kind",
        choices=("observed_environment", "constructed"),
        default="observed_environment",
    )
    imported.add_argument("--environment-file", type=Path)
    matched = commands.add_parser("match")
    matched.add_argument("snapshot_id")
    exported = commands.add_parser("export-verification")
    exported.add_argument("report", type=Path)
    exported.add_argument("--project-id", required=True)
    exported.add_argument("--snapshot-id", required=True)
    backed_up = commands.add_parser("backup")
    backed_up.add_argument("--output", type=Path, required=True)
    backed_up.add_argument("--instance", default="depscope-development")
    restored = commands.add_parser("restore")
    restored.add_argument("--input", type=Path, required=True)
    restored.add_argument("--new-instance", action="store_true")
    restored.add_argument("--instance", required=True)
    restored.add_argument("--bolt-port", type=int, default=17790)
    restored.add_argument("--http-port", type=int, default=17791)
    restored.add_argument("--api-port", type=int, default=18101)
    restored.add_argument("--frontend-port", type=int, default=18080)
    args = parser.parse_args()
    settings = load_settings()
    if args.command in ("backup", "restore"):
        from depscope.operations.backup import BackupManager
        from depscope.runtime.config import PROJECT_ROOT

        manager = BackupManager(PROJECT_ROOT, settings)
        if args.command == "backup":
            result = await asyncio.to_thread(manager.backup, args.output, args.instance)
        else:
            ports = (args.bolt_port, args.http_port, args.api_port, args.frontend_port)
            if len(set(ports)) != 4 or any(not 1 <= p <= 65535 for p in ports):
                raise DomainError("INVALID_PORTS", "Choose four distinct valid local ports")
            result = await asyncio.to_thread(
                manager.restore, args.input, args.new_instance, args.instance, *ports
            )
        print(json.dumps(result, ensure_ascii=False))
        return
    container = build_services(settings)
    try:
        if args.command == "export-verification":
            print(
                json.dumps(
                    {
                        "verification_id": container.verifications.register(
                            args.report, args.project_id, args.snapshot_id
                        )
                    }
                )
            )
            return
        if args.command == "collect-corpus":
            from datetime import datetime

            cutoff = datetime.fromisoformat(args.cutoff)
            if cutoff.tzinfo is None:
                raise DomainError("INVALID_CUTOFF", "Timezone-aware cutoff required")
            payload = {
                "packages": list(PUBLIC_ROOTS),
                "cutoff": cutoff.isoformat(),
                "output": str(args.output.resolve()),
            }
            job = await asyncio.to_thread(container.jobs.enqueue, "corpus", payload)
        elif args.command == "match":
            container.snapshots.load(args.snapshot_id)
            job = await asyncio.to_thread(
                container.jobs.enqueue, "match", {"snapshot_ids": [args.snapshot_id]}
            )
        else:
            from depscope.ingest.limits import MAX_BYTES
            from depscope.runtime.pagination import now

            container.snapshots.project(args.project_id)
            if args.file.stat().st_size > MAX_BYTES:
                raise DomainError("UPLOAD_TOO_LARGE", "SBOM exceeds byte limit")
            raw = args.file.read_bytes()
            source = container.records.put(raw, "local-file://" + args.file.name, now())
            environment = {}
            if args.environment_file:
                environment = json.loads(args.environment_file.read_text())
                allowed = {
                    "os",
                    "architecture",
                    "python_version",
                    "extras",
                    "marker_environment",
                    "private_application_root",
                }
                if not isinstance(environment, dict) or not set(environment) <= allowed:
                    raise DomainError(
                        "INVALID_ENVIRONMENT", "Unsupported environment descriptor fields"
                    )
            job = await asyncio.to_thread(
                container.jobs.enqueue,
                "import",
                {
                    "project_id": args.project_id,
                    "source_kind": args.source_kind,
                    "source_ref": source.model_dump(mode="json"),
                    "environment": environment,
                    "digest": source.digest,
                },
            )
        print(json.dumps({"job_id": job.id, "kind": job.kind}), flush=True)
        completed = await wait(container, job.id)
        print(
            json.dumps(
                {
                    "job_id": completed.id,
                    "status": completed.status,
                    "result_id": completed.result_id,
                }
            ),
            flush=True,
        )
    finally:
        container.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except DomainError as exc:
        print(json.dumps({"error": exc.as_dict()}))
        raise SystemExit(1) from None
