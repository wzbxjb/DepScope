# Frozen retrieval evaluation v1

## Corpus and labels

The source manifest selects 15 public PyPI roots and 45 current public dependency resolutions, grouped into 10 root families. Selection uses the fixed October 13 cutoff; acquisition and OSV collection times are preserved independently. Local observed environments and constructed fixtures do not enter the principal benchmark.

Exactly 200 real-source questions are selected by deterministic seeded order, with balanced family-group selection and deduplication of facts/evidence combinations. The first three families in `SHA256("20261013:" + family)` order are development families: **datasets, llama-index, streamlit**. The remaining seven are test families. All six LangChain/LangGraph/LangSmith roots belong to one `langchain_family`. A cross-project question uses roots from its own split only.

| Type | Dev | Frozen test | Total |
| --- | ---: | ---: | ---: |
| Single version / advisory query facts | 12 | 28 | 40 |
| Indirect dependency paths | 18 | 42 | 60 |
| Shared downstream dependency impact across projects | 12 | 28 | 40 |
| Comparison and upgrade evidence | 12 | 28 | 40 |
| Missing installed/test evidence | 6 | 14 | 20 |
| Total | 60 | 140 | 200 |

Reference labels come from original raw deps.dev nodes/edges and raw OSV request/response pages. NetworkX computes paths independently of product traversal code. Only targets with a unique shortest path are selected, so equivalent shortest paths are not unfairly penalized. Alias groups use connected components of active advisory identifiers/aliases; withdrawn records and `related` links do not merge matches. The independent comparison reference must agree with the product's frozen known-match differences before a question is admitted; disagreement is a defect, never replaced with the product's answer.

Labels are `program_reference` / `not_human_reviewed`. There is no claimed human gold standard. Required evidence IDs are bound from raw source pointers to intact, hash-verified derived receipts. Long comparison records have separate scalar receipts; a compact lineage receipt retains all upstream query/advisory hashes. The question/expected-label metadata is never supplied to generation.

## Freeze and methods

`artifacts/benchmark/v1` stores original-source manifest identity, evidence documents/chunks, model/index identity, questions, prompt/schema, source code hashes, retrieval configuration and pricing. Any unrecorded change to questions, configuration, evidence, provider/model or critical software makes the runner refuse the suite. Software-defect re-evaluation requires a new version and written change record. There is no performance tuning between this version's development and final test runs.

All four methods use the same corpus, fixed 2,000-character maximum chunks with 200-character overlap, source field boundaries, 10 chunks / 12,000 text characters, generation prompt, model and 1,024 output-token cap:

- `lexical`: Neo4j full-text ranking.
- `vector`: Neo4j vector ranking from the pinned local Qwen embedding model.
- `rrf`: reciprocal-rank fusion of those rankings.
- `graph_rrf`: the same hybrid ranking plus one-hop, explicitly snapshot-scoped graph evidence.

Exact package/version and advisory ID lookup is shared. Immutable database payloads are warmed/cached uniformly; actual ranked database queries still run. Local corpus embedding checkpoints are bound to model digest and exact batch text. No reference label influences retrieval ranking.

## Real calls and cost

The runner interleaves methods with seed 20261013 at concurrency four, completes 240 development generations before the 560 test generations, and preserves every result/status. It explicitly generates on empty retrieved context during evaluation, while normal interactive empty-evidence refusal remains free. Retrieval failures remain retrieval failures, not correct abstentions. A completed principal run requires 800 final result rows and at least 800 persistently recorded generation reservations.

The batch has a persisted **USD 10 / 1,200 call** ceiling under the user's authorization to use the configured API. Startup/ordinary tests make no paid calls. A run lock prevents two local runners from charging the same experiment. Completed results are immutable CAS/DB-anchored records and can recover missing manifest files without repeating calls. Interrupted partial results are checkpoints, not selectively discarded failures.

Pricing was rechecked on October 14 against [official DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/). The frozen peak rates are conservative upper-bound estimates, not supplier invoices. Returned model IDs, usage and call ledger are preserved. Missing usage makes the total cost unavailable; the known subtotal and conservative reservations remain visible. The unspecified GPT provider is not used as an automatic paid fallback.

## Metrics and interpretation

Report development/test and type-specific denominators, exact structured-fact accuracy, required-evidence Recall@10, citation location, correct abstention on missing-evidence questions, service failures, parse failures, unsupported output, latency median/P95, actual available token counts and estimated expense. A valid fact about the wrong target is not a correct answer. Extra irrelevant facts prevent exact-answer credit. Failures/refusals remain in answer-accuracy denominators.

Citation location only checks that an ID was supplied and can be located. It does **not** establish semantic support. Semantic citation support and open explanation accuracy remain unavailable without a recorded audit. Missing-question source documents establish that these are public resolver records; they do not establish that an application was installed or tested.

Paired method differences use 1,000 seeded cluster-bootstrap resamples. Single-project questions cluster by root family; cross-project questions cluster by sorted family-name combination. The report retains actual group counts and marks fewer than 10 groups unstable. Composite groups can share families. These are descriptive stability intervals, not fully independent population samples or significance claims. Shared downstream packages/advisories can occur in both splits; this measures new investigation scenarios, not unseen-vulnerability detection.

Latency includes query embedding, scoped retrieval, remote generation and validation, with concurrency/hardware/cold-start exclusions recorded in configuration. Corpus indexing and warm immutable payload loading are excluded. Results are not comparisons to other machines or providers. Graph contribution means relationship-expansion contribution in this implementation; it does not show that graph databases universally outperform relational databases. A negative or zero improvement is retained.
