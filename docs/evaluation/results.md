# Actual evaluation results / 实际评估结果

Run: `benchmark-v1-20261014`  
Suite SHA-256: `18076e9625595a7cd5fdb43e0fe564553a187b04947afeb4a6b02944be80dcc0`

800 unique returned request IDs, 800 usage records, 5,212,843 input tokens and 246,258 output tokens. Peak-rate upper-bound estimated cost: **USD 1.638689922**, not an invoice. All 800 final attempts are retained: 428 admitted answers, 273 insufficient-evidence responses, 48 parse failures and 51 unsupported outputs withheld. No model-service failure occurred in this run.

Frozen test: 140 questions; exact fact accuracy uses the **126 non-missing questions**. Correct abstention uses the **14 missing-evidence questions**.

| Method | Correct facts / 126 | Exact accuracy | Evidence Recall@10 | Correct abstention / 14 | Median / P95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| lexical | 31 | 24.6% | 36.9% | 11 | 1.92s / 4.10s |
| vector | 47 | 37.3% | 57.7% | 4 | 2.52s / 4.76s |
| rrf | 50 | 39.7% | 62.6% | 9 | 2.50s / 4.54s |
| graph_rrf | 48 | 38.1% | 54.6% | 9 | 2.41s / 4.69s |

Hybrid exact accuracy exceeds full-text by **15.1 percentage points on this test set**. Graph expansion does **not** improve on hybrid: exact accuracy is lower by 1.6 points and evidence recall by 7.9 points. These are descriptive results for this corpus/configuration. They do not establish a general advantage, business impact or a database comparison.

The implementation inserts one-hop evidence into a fixed ten-chunk budget. Displacement of useful hybrid evidence is a plausible explanation for the recall loss; it is an engineering hypothesis, not a demonstrated causal mechanism. No post-test prompt/parameter tuning or selective replacement of failures was performed.

## Uncertainty and limits

The test split has **seven underlying root families**. Single-family labels plus the 21 possible cross-family combinations produce 28 bootstrap group labels. Those 28 labels are **not 28 independent families**. The stored `unstable` flag only applies a small-label-count threshold; its false value for these 28 labels does not demonstrate statistical stability or independence. Treat all intervals as descriptive and fragile because the combinations overlap and underlying family coverage is limited. No significance claim is made.

The provider uses an API model alias and default sampling behavior; no deterministic provider seed or repeated generation replicates are claimed. Returned IDs are all `deepseek-flash`, which does not expose every backend deployment detail. Latency includes actual concurrent retrieval/generation/validation and persistent-ledger retry time.

Visible citation location is enforced by the application. Its rate is conditional on admitted outputs containing citations (428 questions across both splits); it is not an ungated model citation-accuracy score. No human semantic citation-support audit was performed, so semantic support remains unavailable.

Reference labels are program-generated from original raw records with an independent NetworkX traversal and raw-query alias comparison. Human review status remains `not_human_reviewed`. Local SBOMs and constructed test data do not fill the public benchmark. No user study, enterprise deployment count, ROI or security-impact claim is supported.

See [protocol](protocol.md), [machine-readable report](../../artifacts/experiments/benchmark-v1-20261014/report.json), [manifest](../../artifacts/experiments/benchmark-v1-20261014/manifest.json), [frozen questions](../../artifacts/benchmark/v1/questions.json), and [call ledger](../../artifacts/experiments/benchmark-v1-20261014/call-ledger.json).
