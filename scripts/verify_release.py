"""Run from the repository root with the configured backend interpreter."""

import json

from depscope.operations.release import verify_release
from depscope.runtime.config import PROJECT_ROOT

result = verify_release(PROJECT_ROOT)
path = PROJECT_ROOT / "artifacts/verification/release-manifest.json"
path.write_text(result.model_dump_json(indent=2) + "\n")
print(
    json.dumps(
        {
            "status": "verified",
            "commit": result.commit,
            "checks": result.checks,
            "manifest": str(path),
        }
    )
)
