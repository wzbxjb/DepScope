"""Offline native backup of this local Compose instance. All restore commands are fixed."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from depscope.generation.budget import BudgetLedger
from depscope.graph.driver import connect
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now

NEO4J_IMAGE = "registry-1.docker.io/library/neo4j:5.26-community@sha256:f1e52d4dc6da122468c4a3c1050a4f5e117f6d3268625237c34d49166f0d6082"


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(root):
    result = {}
    for file in sorted(Path(root).rglob("*")):
        if file.is_symlink():
            raise DomainError("INVALID_BACKUP", "Symlinks are not accepted in backups")
        if file.is_file():
            result[str(file.relative_to(root))] = sha(file)
    return result


def verify_backup(root):
    root = Path(root)
    try:
        doc = json.loads((root / "manifest.json").read_bytes())
        if doc["format"] != "depscope-private-backup-v1" or doc["image"] != NEO4J_IMAGE:
            raise ValueError
        if "neo4j.dump" not in doc["hashes"]:
            raise ValueError
        for relative, digest in doc["hashes"].items():
            path = PurePosixPath(relative)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in relative
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise ValueError
            file = root / relative
            if (
                file.is_symlink()
                or not file.resolve().is_relative_to(root.resolve())
                or sha(file) != digest
            ):
                raise ValueError
        return doc
    except (OSError, ValueError, KeyError, TypeError):
        raise DomainError(
            "INVALID_BACKUP", "Backup format, paths or file digests are invalid"
        ) from None


def graph_state(settings):
    driver = connect(settings)
    try:
        with driver.session() as session:
            nodes = session.run("MATCH (n) RETURN count(n) AS n").single()["n"]
            edges = session.run("MATCH ()-[r]->() RETURN count(r) AS n").single()["n"]
            snapshots = [
                r["id"]
                for r in session.run(
                    "MATCH (s:Snapshot {status:'ready'}) RETURN s.snapshot_id AS id ORDER BY id"
                )
            ]
            budgets = [
                r["id"]
                for r in session.run("MATCH (b:GenerationBudget) RETURN b.id AS id ORDER BY id")
            ]
            active = session.run(
                "MATCH (j:Job) WHERE j.status IN ['validating','fetching','writing'] RETURN count(j) AS n"
            ).single()["n"]
            pending = session.run(
                "MATCH (c:GenerationCall {status:'pending'}) RETURN count(c) AS n"
            ).single()["n"]
        ledger = BudgetLedger(driver)
        return {
            "nodes": nodes,
            "relationships": edges,
            "snapshot_ids": snapshots,
            "budgets": {id: ledger.summary(id).model_dump(mode="json") for id in budgets},
            "active_jobs": active,
            "pending_generation_calls": pending,
        }
    finally:
        driver.close()


class BackupManager:
    def __init__(self, root, settings):
        self.root = Path(root).resolve()
        self.settings = settings

    def _command(self, args, env=None, stdout=None):
        result = subprocess.run(
            args,
            cwd=self.root,
            env=env,
            stdout=stdout or subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600,
        )
        if result.returncode:
            # No command/env/stderr echo: Compose can contain credentials in configuration errors.
            raise DomainError(
                "BACKUP_OPERATION_FAILED",
                "A fixed local backup/restore command failed; no existing volumes were removed",
            )
        return result.stdout.decode().strip() if stdout is None else ""

    def _compose(self, instance, args, env=None):
        return self._command(
            [
                "docker",
                "compose",
                "--project-name",
                instance,
                "-f",
                str(self.root / "compose.yaml"),
                *args,
            ],
            env=env,
        )

    def backup(self, output, instance="depscope-development"):
        if not re.fullmatch(r"depscope-[a-z0-9-]{1,60}", instance):
            raise DomainError("INVALID_INSTANCE", "Choose this project's local Compose instance")
        output = Path(output).resolve()
        if output.is_relative_to(self.settings.data_root.resolve()):
            raise DomainError("INVALID_BACKUP", "Backup must be outside the live data directory")
        if output.exists() and any(output.iterdir()):
            raise DomainError("BACKUP_EXISTS", "Choose a new empty private backup directory")
        output.mkdir(parents=True, exist_ok=True)
        output.chmod(0o700)
        container = self._compose(instance, ["ps", "-q", "neo4j"])
        if not container:
            raise DomainError(
                "BACKUP_TARGET_MISMATCH", "The selected local Neo4j instance is not running"
            )
        port = self._command(["docker", "port", container, "7687/tcp"])
        uri = urlsplit(self.settings.neo4j_uri)
        if uri.hostname not in ("127.0.0.1", "localhost") or f":{uri.port or 7687}" not in port:
            raise DomainError(
                "BACKUP_TARGET_MISMATCH", "Configured database is not the selected local container"
            )
        before = graph_state(self.settings)
        if before["active_jobs"] or before["pending_generation_calls"]:
            raise DomainError("BACKUP_BUSY", "Wait for active jobs and generation calls to settle")
        running = self._compose(instance, ["ps", "--services", "--status", "running"]).splitlines()
        self._compose(instance, ["stop", "api", "worker"])
        try:
            before = graph_state(self.settings)
            if before["active_jobs"] or before["pending_generation_calls"]:
                raise DomainError("BACKUP_BUSY", "A writer became active; retry after it settles")
            self._compose(instance, ["stop", "neo4j"])
            with (output / "neo4j.dump").open("wb") as target:
                self._command(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--network",
                        "none",
                        "--user",
                        "0",
                        "--volumes-from",
                        container,
                        "--entrypoint",
                        "neo4j-admin",
                        NEO4J_IMAGE,
                        "database",
                        "dump",
                        "neo4j",
                        "--to-stdout",
                    ],
                    stdout=target,
                )
            destination = output / "runtime"
            shutil.copytree(
                self.settings.data_root,
                destination,
                ignore=shutil.ignore_patterns("embedding-checkpoints", "corpus-checkpoints"),
                symlinks=True,
            )
            files = inventory(destination)
            # Protect the copied verification signing key and all private model/source receipts.
            for directory in [destination, *[p for p in destination.rglob("*") if p.is_dir()]]:
                directory.chmod(0o700)
            for file in destination.rglob("*"):
                if file.is_file():
                    file.chmod(0o600)
            hashes = {
                "neo4j.dump": sha(output / "neo4j.dump"),
                **{"runtime/" + name: digest for name, digest in files.items()},
            }
            manifest = {
                "format": "depscope-private-backup-v1",
                "image": NEO4J_IMAGE,
                "source_instance": instance,
                "observed_at": now(),
                "graph": before,
                "hashes": hashes,
                "limitations": [
                    "Database dump excludes system users/roles; configure fresh target credentials. API keys and .env are excluded.",
                    "Embedding/corpus computation caches are excluded; indexed vectors, source bytes, journals, verification key and budget ledger are preserved.",
                ],
            }
            (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            (output / "manifest.json").chmod(0o600)
            verify_backup(output)
        finally:
            self._compose(instance, ["up", "-d", "neo4j"])
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    after = graph_state(self.settings)
                    break
                except Exception:
                    time.sleep(1)
            else:
                raise DomainError(
                    "BACKUP_RESTART_FAILED", "Source database did not return to ready state"
                )
            if before != after:
                raise DomainError(
                    "BACKUP_STATE_CHANGED",
                    "Database state changed during backup; keep artifacts for inspection",
                )
            services = [name for name in ("api", "worker") if name in running]
            if services:
                self._compose(instance, ["up", "-d", *services])
        return {
            "backup_path": str(output),
            "manifest_sha256": sha(output / "manifest.json"),
            "graph": before,
            "verified_files": len(hashes),
        }

    def restore(
        self,
        input,
        new_instance=False,
        instance=None,
        bolt_port=17790,
        http_port=17791,
        api_port=18101,
        frontend_port=18080,
    ):
        if not new_instance:
            raise DomainError(
                "NEW_INSTANCE_REQUIRED",
                "Restore requires an explicit new instance; existing volumes are never overwritten",
            )
        if not instance or not re.fullmatch(r"depscope-restore-[a-z0-9-]{1,40}", instance):
            raise DomainError(
                "NEW_INSTANCE_REQUIRED", "Use a unique depscope-restore-* instance name"
            )
        source = Path(input).resolve()
        manifest = verify_backup(source)
        if self._compose(instance, ["ps", "-aq"]):
            raise DomainError("RESTORE_TARGET_EXISTS", "Target instance already exists")
        volume = subprocess.run(
            ["docker", "volume", "inspect", instance + "_neo4j-data"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if volume.returncode == 0:
            raise DomainError("RESTORE_TARGET_EXISTS", "Target database volume already exists")
        target = self.root / "artifacts/private/restores" / instance / "runtime"
        if target.exists():
            raise DomainError("RESTORE_TARGET_EXISTS", "Target source directory already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source / "runtime", target)
        env = dict(os.environ)
        env.update(
            {
                "DEPSCOPE_RUNTIME_PATH": str(target),
                "DEPSCOPE_NEO4J_BOLT_PORT": str(bolt_port),
                "DEPSCOPE_NEO4J_HTTP_PORT": str(http_port),
                "DEPSCOPE_API_PORT": str(api_port),
                "DEPSCOPE_FRONTEND_PORT": str(frontend_port),
                "DEPSCOPE_LOCAL_UID": str(os.getuid()),
            }
        )
        self._compose(instance, ["create", "neo4j"], env)
        container = self._compose(instance, ["ps", "-aq", "neo4j"], env)
        self._command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                "0",
                "--volumes-from",
                container,
                "--mount",
                "type=bind,source=" + str(source) + ",target=/restore,readonly",
                "--entrypoint",
                "neo4j-admin",
                NEO4J_IMAGE,
                "database",
                "load",
                "neo4j",
                "--from-path=/restore",
            ]
        )
        self._compose(instance, ["up", "-d", "neo4j"], env)
        from dataclasses import replace

        restored_settings = replace(
            self.settings, neo4j_uri=f"bolt://127.0.0.1:{bolt_port}", data_root=target
        )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                actual = graph_state(restored_settings)
                break
            except Exception:
                time.sleep(1)
        else:
            raise DomainError("RESTORE_NOT_READY", "Fresh restored database did not become ready")
        if actual != manifest["graph"]:
            raise DomainError("RESTORE_STATE_MISMATCH", "Restored graph or budget ledger differs")
        if inventory(target) != {
            name.removeprefix("runtime/"): digest
            for name, digest in manifest["hashes"].items()
            if name.startswith("runtime/")
        }:
            raise DomainError("RESTORE_STATE_MISMATCH", "Restored raw evidence differs")
        self._compose(instance, ["up", "-d", "api", "worker", "frontend"], env)
        result = {
            "instance": instance,
            "restored_at": now(),
            "source_manifest_sha256": sha(source / "manifest.json"),
            "graph_and_budget_equal": True,
            "source_hashes_equal": True,
            "graph": actual,
            "api_url": f"http://127.0.0.1:{api_port}",
            "frontend_url": f"http://127.0.0.1:{frontend_port}",
            "runtime_path": str(target),
        }
        (target.parent / "restore-result.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
