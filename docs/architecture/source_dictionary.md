# Source dictionary / 数据来源与证据边界

The public corpus in `artifacts/corpus/manifest.json` freezes 15 PyPI roots, 45 complete public dependency snapshots, 10 families and 30 comparisons. The selection cutoff is **2026-10-13T23:59:59-05:00**; acquisition dates are recorded separately. Historical roots are selected by actual PyPI upload timestamps. Their graphs are **current public resolutions acquired in October 2026**, not reconstructions of historical installations. Cases are `ecosystem_case`, not enterprise deployments or users.

| Record | Origin | Meaning and limits |
| --- | --- | --- |
| Root releases | [PyPI JSON API](https://docs.pypi.org/api/json/) | Frozen metadata, upload dates, selected versions and exclusions; no performance-based replacement. |
| Dependency graphs | [deps.dev API](https://docs.deps.dev/api/v3alpha/) | Resolver graphs and declarations, always `public_resolution`; no installation or test proof. |
| Advisory records | [OSV API](https://google.github.io/osv.dev/api/) | Requests, responses, pagination, alias groups and withdrawn status. No known match does not establish safety. Comparisons reuse one frozen collection. |
| Local inventories | [CycloneDX Python environment command](https://cyclonedx-bom-tool.readthedocs.io/en/latest/usage.html#environment) | Two actual isolated Python environments, interpreter/platform and original SBOM. Shared application source is hashed separately. Inventory covers installed distributions, not the whole operating system. |
| Controlled validation | Fixed backend and example workflows | Actual installation check and pytest commands, exit codes, source manifests and locally signed records. No uploaded commands are executed. |
| AI example | `example-api-contract.json` | Actual response, supplied source ID, usage and estimated cost; test fixtures do not count as live API success. |

## Observed environment normalization

Original tool output remains in `*-environment.raw.cdx.json`. The controlled producer independently checks **actual installed Requires-Dist metadata**, environment markers and propagated explicit extras. It records all missing/extra tool edges before emitting the reconciled `*-environment.cdx.json`. Empty dependency lists require metadata proof. Missing distributions or unsatisfied active declarations fail verification.

Some tool outputs represent the same application as both an application root and an installed distribution. Only matching name/version plus `pip inspect` file-source ownership proof allows merging those representations. Ordinary duplicate instances are preserved. The explicitly private application root is never queried against a public PyPI package of the same name.

`*-verification-summary.json` contains real context IDs, counts, exit codes and hashes. `tests_verified` verifies **that observed environment against itself**; `upgrade_executed: false` is explicit. It is not a tested upgrade or a guarantee for another application. Public-resolution comparisons stay `metadata_comparison`.

Signed reports, installation metadata and full logs are private under ignored `artifacts/private/` and the local content-addressed store. Credentials and registry signing keys are excluded from public artifacts. CycloneDX and pytest tools use separate environments; test tools are appended after the observed interpreter's own runtime packages.

## Reproduction

Install the exact runtime locks into separate `.venv-runtime` environments and install each application editable with `--no-deps`. Install CycloneDX and test tools into separate tool environments, inspecting actual CLI help. With the database and single worker running, invoke `python -m depscope.analysis.environment_runner backend` and `... example` from the backend development interpreter. Each producer imports through the durable queue and registers signed reports. New observations do not replace the frozen public corpus.

Raw public bytes are content addressed under `raw/`; `sources.json` retains digests and public observations. Snapshot/MatchRun exports retain context and collection IDs. Retrieval receipts preserve upstream digests/pointers and are clearly derived evidence.
