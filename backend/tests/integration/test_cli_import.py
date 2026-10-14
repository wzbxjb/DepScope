import asyncio
import dataclasses
import json
import sys
import pytest
from depscope import cli
from depscope.api.services import build_services
from depscope.runtime.config import load_settings


async def test_cli_import_uses_existing_worker_source_contract(
    repo, job_store, tmp_path, monkeypatch
):
    settings = dataclasses.replace(load_settings(), data_root=tmp_path / "data")
    services = build_services(settings, driver=repo.driver, snapshots=repo, jobs=job_store)
    project = repo.create_project("CLI fixture")
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "constructed-cli-fixture",
                "version": "1.0",
                "bom-ref": "root",
            }
        },
        "components": [],
        "dependencies": [{"ref": "root", "dependsOn": []}],
    }
    file = tmp_path / "fixture.json"
    file.write_text(json.dumps(bom))
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_services", lambda settings: services)
    monkeypatch.setattr(
        sys, "argv", ["depscope", "import-file", str(file), "--project-id", project]
    )
    task = asyncio.create_task(cli.main())

    async def worker():
        while not task.done():
            await services.worker.run_once()
            await asyncio.sleep(0.01)

    await asyncio.wait_for(asyncio.gather(task, worker()), 5)
    assert len(repo.list_snapshots(project).items) == 1
