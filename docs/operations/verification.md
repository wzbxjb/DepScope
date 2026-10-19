# Verification evidence

## Contributor checks

For current-source unit tests, Neo4j integration tests, frontend tests, and a production build, follow [the contribution guide](../../CONTRIBUTING.md#run-checks). These checks work from a fresh clone after installing dependencies and starting the dedicated test database. They do not need a private signing key or a generation API key.

The [CI workflow](../../.github/workflows/ci.yml) runs these checks independently. A workflow definition is not proof of a successful remote run; inspect the repository's Actions page for that run's status after publication.

## Historical evidence and signed release checks

Committed experiment and check records describe the revision and source digest recorded in each artifact. They remain historical evidence when the working tree changes. Do not interpret an old signed check as verification of the current source tree.

The full release verifier additionally requires the original local database, source store, private signing keys, and completed acceptance records. It is not the fresh-clone contributor test command. After source changes, rerun the applicable checks and record new evidence before claiming a newly verified release. A live-generation check is a separately authorized paid operation.

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
