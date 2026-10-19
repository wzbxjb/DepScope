# Contributing to DepScope

Bug reports, reproducible fixes, and documentation improvements are welcome. For a larger feature, open an issue describing the problem and proposed behavior before starting implementation.

## Set up development

Use Python 3.11 and Node 22.23.3. Follow [native development](docs/operations/setup.md#native-development) to install the locked dependencies and start the API, worker, and frontend.

Keep changes focused. Add a regression test for a behavior fix and update the relevant documentation when a command, configuration setting, or API contract changes.

## Run checks

From the repository root, with the backend environment installed:

```sh
# Unit tests do not require Neo4j or live model services.
backend/.venv/bin/python -m pytest backend/tests/unit -q

# Integration tests use the dedicated test database on port 17688.
docker compose -f compose.yaml -f compose.test.yaml --profile test up -d --wait neo4j-test
backend/.venv/bin/python -m pytest backend/tests/integration -q
```

Then run frontend checks:

```sh
cd frontend
npm test -- --run
npm run build
```

The same backend and frontend checks run in [CI](.github/workflows/ci.yml). Integration tests exercise real Neo4j persistence, leases, context isolation, and budgets; public HTTP/model requests use fixtures. Changes to browser workflows should also be checked against a running application; see [verification](docs/operations/verification.md).

## Preserve evidence

`artifacts/corpus/`, `artifacts/benchmark/`, and `artifacts/experiments/` contain frozen source records and experiment results. Their hashes and manifests depend on their original bytes. Record a new version when changing a benchmark or rerunning an experiment; retain the original run and its failures.

Keep constructed test data separate from observed environment records and public source receipts. Do not replace historical receipts with a new success flag. Signed release checks apply to the source digest they recorded, so a changed source tree requires new verification records.

Paid generation and full benchmark runs are opt-in operations outside ordinary CI. A pull request should not require a maintainer to supply a model API key just to run its unit tests.

## Open a pull request

Describe the concrete problem, resulting behavior, and checks you ran. Include screenshots for visible interface changes and a small reproducible example for ingestion or graph bugs. Keep credentials, runtime data, private backups, and local environments out of the diff.

For a security issue, follow [SECURITY.md](SECURITY.md) instead of posting sensitive details in a public issue.
