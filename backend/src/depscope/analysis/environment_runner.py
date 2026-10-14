"""Two fixed local producers. No HTTP/upload caller can choose executable commands."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from depscope.analysis.producer import normalize_owned_sbom, reconcile_installed_dependencies
from depscope.analysis.verification import VerificationRecord
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now


def target_paths(target, root):
    relative = {"backend": "backend", "example": "examples/evidence_assistant"}
    if target not in relative:
        raise DomainError(
            "UNTRUSTED_PRODUCER", "Only the two controlled local applications can be verified"
        )
    return Path(root) / relative[target]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode()


async def produce(target, root, container):
    root = Path(root).resolve()
    project = target_paths(target, root)
    interpreter = project / ".venv-runtime/bin/python"
    tools = root / ".superpowers/tools/runtime-tests/lib/python3.11/site-packages"
    output = root / "artifacts/corpus"
    private = root / "artifacts/private/environments" / target
    private.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    producer = (
        "depscope.local-backend-v1" if target == "backend" else "depscope.example-assistant-v1"
    )
    sources = {}

    def save(label, raw, public=False):
        source = container.records.put(raw, "local-producer://" + target + "/" + label, now())
        sources[label] = source.digest
        (private / label).write_bytes(raw)
        if public:
            (output / (target + "-" + label)).write_bytes(raw)
        return source

    def capture(label, command, cwd=project):
        environment = dict(os.environ)
        environment["DEPSCOPE_TEST_NEO4J_URI"] = "bolt://127.0.0.1:17688"
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600,
        )
        save(label, result.stdout)
        return result

    inspected = capture("pip-inspect.json", [str(interpreter), "-m", "pip", "inspect", "--local"])
    if inspected.returncode:
        raise DomainError("ENVIRONMENT_CAPTURE_FAILED", "Installed inventory could not be captured")
    inspect = json.loads(inspected.stdout)
    declared = tomllib.loads((project / "pyproject.toml").read_text())["project"]
    owned = next(
        row["metadata"]
        for row in inspect["installed"]
        if row["metadata"]["name"] == declared["name"]
    )
    if (
        sorted(owned.get("requires_dist", [])) != sorted(declared["dependencies"])
        and target == "example"
    ):
        raise DomainError(
            "APPLICATION_METADATA_MISMATCH",
            "Application declarations differ from installed metadata",
        )
    save("pyproject.toml", (project / "pyproject.toml").read_bytes())
    source_rows = []
    source_directories = [root / "backend/src", project / "tests"]
    if target == "example":
        source_directories += [project]
    for directory in source_directories:
        for file in sorted(directory.rglob("*.py")):
            if any(part.startswith(".venv") or part == "__pycache__" for part in file.parts):
                continue
            source_rows.append(
                {
                    "path": str(file.relative_to(root)),
                    "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                }
            )
    save("application-source-manifest.json", canonical(source_rows), public=True)
    freeze = (
        "\n".join(
            sorted(
                row["metadata"]["name"] + "==" + row["metadata"]["version"]
                for row in inspect["installed"]
                if row["metadata"]["name"] != declared["name"]
            )
        )
        + "\n"
    )
    (project / "requirements-runtime.lock").write_text(freeze)
    save("requirements-runtime.lock", freeze.encode())
    env_code = "import json,platform,sys,os;print(json.dumps({'os':platform.system(),'architecture':platform.machine(),'python_version':platform.python_version(),'extras':[],'marker_environment':{'implementation_name':sys.implementation.name,'implementation_version':platform.python_version(),'os_name':os.name,'platform_machine':platform.machine(),'platform_release':platform.release(),'platform_system':platform.system(),'platform_version':platform.version(),'python_full_version':platform.python_version(),'platform_python_implementation':platform.python_implementation(),'python_version':'.'.join(platform.python_version_tuple()[:2]),'sys_platform':sys.platform}}))"
    captured = capture("environment-capture.json", [str(interpreter), "-c", env_code])
    if captured.returncode:
        raise DomainError("ENVIRONMENT_CAPTURE_FAILED", "Runtime descriptor could not be captured")
    environment = json.loads(captured.stdout)
    environment["private_application_root"] = True
    save("environment.json", canonical(environment), public=True)
    raw_path = output / (target + "-environment.raw.cdx.json")
    tool_command = [
        str(root / ".superpowers/tools/cyclonedx-env/bin/python"),
        "-m",
        "cyclonedx_py",
        "environment",
        str(interpreter),
        "--pyproject",
        str(project / "pyproject.toml"),
        "--spec-version",
        "1.6",
        "--output-format",
        "JSON",
        "--output-reproducible",
        "--output-file",
        str(raw_path),
    ]
    tool = capture("sbom-tool.log", tool_command)
    if tool.returncode:
        raise DomainError("SBOM_TOOL_FAILED", "Environment SBOM generation failed")
    raw = raw_path.read_bytes()
    save("original-sbom", raw)
    normalized, ownership = normalize_owned_sbom(json.loads(raw), inspect, project)
    normalized, declarations, corrections = reconcile_installed_dependencies(
        normalized, inspect, environment
    )
    save(
        "normalization-audit.json",
        canonical(ownership | corrections | {"original_sha256": hashlib.sha256(raw).hexdigest()}),
        public=True,
    )
    source = save("environment.cdx.json", canonical(normalized), public=True)
    project_id = container.snapshots.create_project(
        "Observed local environment: " + declared["name"]
    )
    # Import by exactly the same queued local CLI path, preserving single mutation ownership.
    job = container.jobs.enqueue(
        "import",
        {
            "project_id": project_id,
            "source_kind": "observed_environment",
            "source_ref": source.model_dump(mode="json"),
            "environment": environment,
            "digest": source.digest,
        },
    )
    from depscope.cli import wait

    completed = await wait(container, job.id)
    snapshot = container.snapshots.load(completed.result_id)
    constraints = save(
        "constraints.json",
        canonical(
            {
                "snapshot_digest": source.digest,
                "environment": snapshot.environment,
                "declarations": declarations,
            }
        ),
    )
    resolution_command = [str(interpreter), "-m", "pip", "check"]
    resolution = capture("pip-check.log", resolution_command)
    # Append tools after runtime paths, so production libraries come from the observed environment.
    test_code = (
        "import sys;sys.path.append("
        + repr(str(tools))
        + ');import pytest;raise SystemExit(pytest.main(["tests","-q"]))'
    )
    test_command = [str(interpreter), "-c", test_code]
    tests = capture("pytest.log", test_command)
    test_result = save(
        "test-result.json",
        canonical(
            {
                "exit_code": tests.returncode,
                "command": test_command,
                "snapshot_digest": source.digest,
                "environment": snapshot.environment,
                "output_digest": sources["pytest.log"],
            }
        ),
    )
    resolution_result = save(
        "resolution-result.json",
        canonical(
            {
                "exit_code": resolution.returncode,
                "command": resolution_command,
                "snapshot_digest": source.digest,
                "environment": snapshot.environment,
                "output_digest": sources["pip-check.log"],
            }
        ),
    )
    common = {
        "environment": snapshot.environment,
        "source_hashes": {**sources, "snapshot": source.digest, "constraints": constraints.digest},
        "observed_at": now(),
        "producer": producer,
    }
    records = (
        VerificationRecord(
            kind="resolution",
            command=tuple(resolution_command),
            exit_code=resolution.returncode,
            result_digest=resolution_result.digest,
            **common,
        ),
        VerificationRecord(
            kind="tests",
            command=tuple(test_command),
            exit_code=tests.returncode,
            result_digest=test_result.digest,
            **common,
        ),
    )
    signed = private / "signed-report.json"
    container.verifications.write_trusted_report(records, project_id, snapshot.snapshot_id, signed)
    id = container.verifications.register(signed, project_id, snapshot.snapshot_id)
    level = container.verifications.level(snapshot, snapshot, id)
    summary = {
        "project_id": project_id,
        "snapshot_id": snapshot.snapshot_id,
        "source_kind": snapshot.source_kind,
        "verification_id": id,
        "self_observation_verification_level": level,
        "upgrade_executed": False,
        "environment": snapshot.environment,
        "instances": len(snapshot.components),
        "edges": len(snapshot.edges),
        "sbom_tool_exit_code": tool.returncode,
        "resolution_exit_code": resolution.returncode,
        "test_exit_code": tests.returncode,
        "source_hashes": sources,
        "normalization_audit": ownership | corrections,
    }
    save("verification-summary.json", canonical(summary), public=True)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if resolution.returncode or tests.returncode:
        raise DomainError(
            "ENVIRONMENT_VERIFICATION_FAILED",
            "Actual installation checks or tests failed; evidence has been preserved",
        )
    return summary


if __name__ == "__main__":
    from depscope.api.services import build_services
    from depscope.runtime.config import PROJECT_ROOT, load_settings

    container = build_services(load_settings())
    try:
        asyncio.run(produce(sys.argv[1], PROJECT_ROOT, container))
    finally:
        container.close()
