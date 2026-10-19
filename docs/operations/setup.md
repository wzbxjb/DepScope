# Local setup

## Requirements

- Docker and Docker Compose v2 for the container deployment.
- Git to clone and inspect the repository.
- Python 3.11 and Node 22.23.3 for native development. The root `.nvmrc` and `frontend/.node-version` record the Node version.

The recorded development host was macOS arm64 with Python 3.11.5; the recorded application container used Python 3.11.17. CI is configured for Linux with a real Neo4j service and fixture HTTP/model boundaries.

## Container deployment

Run from the repository root:

```sh
cp .env.example .env
# Edit .env and set a private NEO4J_PASSWORD.
export DEPSCOPE_LOCAL_UID=$(id -u)
docker compose build
docker compose up -d --wait
```

Open http://127.0.0.1:8080. API documentation is at http://127.0.0.1:8101/docs and the Neo4j browser at http://127.0.0.1:17474. A generation API key is optional for graph exploration, imports, and comparisons.

`DEPSCOPE_RUNTIME_PATH` defaults to `data/runtime` and must be writable by the configured local UID. Raw source records, journals, signed records, and private model responses persist there. Database/log volumes are persistent. Use `docker compose stop` to stop the services while retaining data. See [backup/restore](backup.md) before removing volumes.

All published ports bind loopback. See [security](../../SECURITY.md) for the deployment scope and data handling.

## First workflow

1. Click **Load verified public sample** to load the archived public graph.
2. Inspect the source kind/date, advisory coverage, and unknown states.
3. Select a node or finding to follow its recorded path and original source.
4. Create a project and upload CycloneDX 1.6 JSON to investigate an application inventory.

Uploads are bounded to 10 MiB, 10,000 components, and 50,000 edges. Refreshing advisories performs real public queries and records a new collection rather than replacing an earlier run. Snapshot comparison requires matching collection context; metadata comparison alone does not demonstrate installation or upgrade compatibility.

## AI investigation

Set `DEEPSEEK_API_KEY`, `AI_MAX_CALLS`, and `AI_MAX_AMOUNT_USD` in `.env` to enable explicitly requested generation. Initialize the configured embedding model before using vector retrieval. After changing `.env`, rerun `docker compose up -d --wait` so services receive the updated configuration.

On macOS, an existing host Ollama is reached through `http://host.docker.internal:11434` by default. Override `DEPSCOPE_CONTAINER_OLLAMA_BASE_URL` if needed. A host loopback address inside a container points to that container.

To use an internal CPU Ollama instead:

```sh
docker compose -f compose.yaml -f compose.embeddings.yaml --profile embeddings up -d --wait
# Explicit initialization: application startup does not download models.
docker compose --profile embeddings exec ollama ollama pull qwen3-embedding:0.6b
```

The recorded Qwen model digest is `ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d`, with 1,024 dimensions. A changed digest gets a different index. The optional Docker CPU runtime has different performance from a host Metal GPU.

The recorded generation configuration used DeepSeek `deepseek-flash`, non-thinking JSON output, and at most 1,024 output tokens. The ledger preserves spending across restarts; limits can be explicitly increased in the UI without resetting prior usage. Unknown token usage retains conservative reservations. Cost estimates use frozen pricing and are not invoices.

## Native development

Run the following from the repository root. If `.env` already exists, retain it and check its database settings instead of copying over it.

```sh
cp .env.example .env
# Edit .env and set NEO4J_PASSWORD.
python3.11 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.lock
backend/.venv/bin/python -m pip install --no-deps -e backend

# Start only the development database.
docker compose up -d --wait neo4j
```

Run the API and a single worker in separate terminals, both from the repository root:

```sh
backend/.venv/bin/python -m uvicorn depscope.runtime.main:app --host 127.0.0.1 --port 8100 --reload
```

```sh
backend/.venv/bin/python -m depscope.jobs.worker
```

In another terminal:

```sh
# With nvm installed, select the version from the root .nvmrc.
nvm install
nvm use
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. The Vite proxy targets the native API on port 8100; the container deployment publishes its API on 8101. If the container API/worker is already running, stop those services before starting native processes against the same database:

```sh
docker compose stop api worker frontend
```

## Tests

Backend unit tests run without Neo4j:

```sh
backend/.venv/bin/python -m pytest backend/tests/unit -q
```

Integration tests use a separate test database on port 17688:

```sh
docker compose -f compose.yaml -f compose.test.yaml --profile test up -d --wait neo4j-test
backend/.venv/bin/python -m pytest backend/tests/integration -q
```

The test fixture uses `DEPSCOPE_TEST_NEO4J_URI` when supplied, otherwise `bolt://127.0.0.1:17688`, and reads the project Neo4j credentials. Keep the test database separate from the application database.

Run frontend tests and the production build from `frontend/`: `npm test -- --run` and `npm run build`. Browser checks and source-bound release receipts are described in [verification](verification.md). The controlled installed-environment producers are documented in the [source dictionary](../architecture/source_dictionary.md).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Compose refuses to start | Set `NEO4J_PASSWORD` in the project `.env`; check `docker compose ps` and `docker compose logs --tail=100 api worker neo4j`. |
| Native UI cannot reach the API | Run the native API on 8100; Vite's proxy does not target the container API on 8101. |
| Integration tests cannot connect | Start `neo4j-test` and check port 17688 and the configured credentials. |
| Vector retrieval is unavailable | Initialize the embedding model and verify the Ollama URL is reachable from the application runtime. |
| Generation is disabled or budget-limited | Check the provider key and both budget limits. Existing ledger spending persists after a restart. |
