# Verification evidence

Run fixed checks from the repository root with the configured backend environment and Node on PATH:

```sh
backend/.venv/bin/python scripts/record_check.py backend-tests
backend/.venv/bin/python scripts/record_check.py frontend-build
backend/.venv/bin/python scripts/record_check.py docker-build
backend/.venv/bin/python scripts/record_check.py docker-start
backend/.venv/bin/python scripts/record_check.py browser-full
# Explicitly paid; requires the private provider key, local embeddings and remaining ledger limits.
backend/.venv/bin/python scripts/record_check.py browser-live --allow-paid
backend/.venv/bin/python scripts/verify_release.py
```

A check runs only a fixed repository command, captures its real exit code/output digest/commit and signs the receipt with the local private key. The release verifier checks original source digests, frozen questions/configuration, database-anchored experiment results, locally signed observed-environment reports, actual check records, fresh reproduction/restore results and A1–A10. It never executes commands stored in reports/uploads.

Ordinary unit/integration tests replace external HTTP/model boundaries with clearly constructed fixtures, while using actual Neo4j for graph/lease/budget isolation. Tests do not secretly run the 800-call benchmark. Paid live generation has a separate explicit flag. Historical completed benchmark rows, failures and original frozen configurations are retained; code-defect re-evaluation needs a recorded version/change.

The committed CI workflow is ready to run after a user-authorized remote push. Local checks are recorded separately; they are not described as a successful GitHub Actions run.
