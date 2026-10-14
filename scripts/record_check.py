"""Execute one fixed local check and bind its actual output/exit code to a signed receipt."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from depscope.operations.release import sign_check, source_digest
from depscope.runtime.config import PROJECT_ROOT, load_settings
from depscope.runtime.pagination import now
from depscope.sources.records import RecordStore

parser = argparse.ArgumentParser()
parser.add_argument(
    "name",
    choices=[
        "backend-tests",
        "frontend-build",
        "browser-full",
        "browser-live",
        "docker-build",
        "docker-start",
    ],
)
parser.add_argument("--allow-paid", action="store_true")
args = parser.parse_args()
root = PROJECT_ROOT
python = root / "backend/.venv/bin/python"
npm = str(Path(shutil.which("npm")).resolve())
commands = {
    "backend-tests": (
        [str(python), "-m", "pytest", "tests/unit", "tests/integration", "-q"],
        root / "backend",
    ),
    "frontend-build": ([npm, "run", "build"], root / "frontend"),
    "browser-full": (
        [
            npm,
            "exec",
            "--",
            "playwright",
            "test",
            "e2e/full-workflow.spec.ts",
            "-g",
            "shows scoped evidence",
            "--reporter=line,json",
        ],
        root / "frontend",
    ),
    "browser-live": (
        [
            npm,
            "exec",
            "--",
            "playwright",
            "test",
            "e2e/full-workflow.spec.ts",
            "-g",
            "explicit live generation",
            "--reporter=line,json",
        ],
        root / "frontend",
    ),
    "docker-build": (["docker", "compose", "build"], root),
    "docker-start": (["docker", "compose", "up", "-d", "--wait"], root),
}
if args.name == "browser-live" and not args.allow_paid:
    raise SystemExit(
        "Live generation requires --allow-paid and configured private API credentials/limits."
    )
env = dict(os.environ)
env["PATH"] = os.pathsep.join(
    str(Path(entry).resolve())
    for entry in env.get("PATH", "").split(os.pathsep)
    if entry
)
env["DEPSCOPE_LOCAL_UID"] = str(os.getuid())
env["DEPSCOPE_LIVE_GENERATION"] = "1" if args.name == "browser-live" else "0"
env["PLAYWRIGHT_JSON_OUTPUT_FILE"] = str(
    root / "artifacts/verification" / (args.name + "-browser.json")
)
command, cwd = commands[args.name]
before_source = source_digest(root)
run = subprocess.run(
    command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
)
if source_digest(root) != before_source:
    raise SystemExit(
        "Source changed while the check was running; rerun the fixed check."
    )
settings = load_settings()
source = RecordStore(settings.data_root).put(
    run.stdout, "local-verifier://release/" + args.name, now()
)
commit = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=root, text=True
).strip()
payload = {
    "name": args.name,
    "source_digest": before_source,
    "command": command,
    "cwd": str(cwd.relative_to(root)),
    "exit_code": run.returncode,
    "log_digest": source.digest,
    "observed_at": now(),
    "commit": commit,
    "paid_opt_in": args.allow_paid,
}
output = root / "artifacts/verification/checks"
output.mkdir(parents=True, exist_ok=True)
(output / (args.name + ".json")).write_text(
    json.dumps(sign_check(payload, settings.data_root), indent=2) + "\n"
)
print(json.dumps(payload))
print(run.stdout.decode(errors="replace")[-1200:])
raise SystemExit(run.returncode)
