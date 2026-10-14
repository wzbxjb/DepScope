# Local setup

Requirements: Docker Compose v2, Git; native development additionally uses Python 3.11 and Node 22.23.3. Verified host: macOS arm64/Python 3.11.5; verified application container: Python 3.11.17. Linux CI uses a real Neo4j service with offline HTTP/model fixtures; no paid calls occur in ordinary CI. This local repository has not triggered a remote CI run or been published.

From the repository root, copy `.env.example` to `.env`, set a private Neo4j password, and optionally configure your own model API key. Keep the file private. Model startup is optional; database/graph/import/comparison features work without paid generation.

```sh
export DEPSCOPE_LOCAL_UID=$(id -u)
docker compose build
docker compose up -d --wait
```

Open http://127.0.0.1:8080. API: http://127.0.0.1:8101/docs. Neo4j browser: http://127.0.0.1:17474. All published ports bind loopback. `DEPSCOPE_RUNTIME_PATH` defaults to `data/runtime` and must be writable by the configured local UID; raw source records, journals, signed records and private model responses persist there. Database/log volumes are persistent. Never use `down -v` on a needed instance.

Use “Load verified public sample” for the archived public graph, then inspect advisory coverage and unknowns. Refreshing advisories performs real public queries and records a new collection; it never silently replaces an older run. Upload accepts CycloneDX 1.6 JSON, at most 10 MiB / 10,000 components / 50,000 edges. Source kinds and dates are always retained.

## Embeddings and API

On macOS, an existing host Ollama can be reached through `DEPSCOPE_CONTAINER_OLLAMA_BASE_URL=http://host.docker.internal:11434`. Do not put a host `127.0.0.1` endpoint into a container. For an internal CPU Ollama instead:

```sh
docker compose -f compose.yaml -f compose.embeddings.yaml --profile embeddings up -d
# Explicit model initialization; startup does not download a model automatically.
docker compose --profile embeddings exec ollama ollama pull qwen3-embedding:0.6b
```

The verified Qwen model digest is `ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d`, with 1,024 dimensions. A changed digest gets a different index and cannot query an old one. Docker Desktop does not provide the host Metal GPU to this optional container; CPU performance is a separate environment.

DeepSeek official `deepseek-flash`, non-thinking JSON output and at most 1,024 output tokens are verified. GPT has no supplied endpoint/model and is not an automatic fallback. Configure `AI_MAX_AMOUNT_USD` and `AI_MAX_CALLS` before real use; the interactive ledger persists usage across restarts and permits explicit higher limits in the UI without resetting spent amounts. Unknown token usage keeps conservative reservations and makes a total expense unavailable. Estimates use frozen peak pricing and are not invoices.

## Native development

Create a backend virtual environment, install `backend/requirements-dev.lock` then `pip install --no-deps -e backend`; run the API on loopback port 8100 and one `python -m depscope.jobs.worker`. In `frontend`, run `npm ci` then `npm run dev`. The development proxy targets 8100. Do not run an extra native worker after moving to the container worker.

The two controlled observed-environment producers require separately installed runtime, CycloneDX and test-tool environments; see [source dictionary](../architecture/source_dictionary.md). They execute only the two repository-owned applications, never commands found in uploaded SBOMs.
