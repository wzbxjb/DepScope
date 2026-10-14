# Résumé evidence / 简历证据

Every number below refers to this actual local project and frozen corpus. No users, enterprise deployments, ROI or security-impact reductions have been measured.

| Claim | Verifiable evidence | Limit |
| --- | --- | --- |
| Neo4j/FastAPI/React dependency investigation product | Source, real browser workflow, Docker/check receipts | Local repository; no remote production release |
| 45 public resolutions / 15 roots / 10 families / 30 comparisons | `artifacts/corpus/manifest.json`, original raw records | Current public resolutions, not historical deployed environments |
| Two actual installed-environment SBOMs | `artifacts/corpus/*-verification-summary.json` | Repository-owned backend/example only; self tests, not upgrade compatibility |
| Four methods / 200 questions / 800 real API calls | Frozen suite, experiment manifest, 800 result files/call ledger | Program labels; 60 dev / 140 test; no human semantic gold |
| Hybrid 39.7% vs full-text 24.6% exact facts on test | `docs/evaluation/results.md`, `report.json` | 50/126 vs 31/126 non-missing facts; not a general-population result |
| Graph expansion 38.1%, no gain over hybrid | Same frozen report | Retain the negative result; no “GraphRAG uplift” claim |
| Persisted usage/cost caps | Generation/budget source and real call ledger | USD1.638689922 peak upper-bound estimate, not invoice |
| Backup/restore | Final `restore-validation.json` and release gates | Only cite “verified” after those actual artifacts exist/pass |

## Chinese résumé wording

**DepScope｜基于 Neo4j 与 AI 的依赖风险调查平台**

- 独立设计并开发 Neo4j、FastAPI、React 全栈产品，实现依赖快照隔离、OSV 公告别名去重、间接影响路径、快照比较及原始证据追溯。
- 采集 15 个 AI 相关根包的 45 份公开依赖解析快照，构建按家族隔离的 200 题评估集，完成四种检索策略的 800 次真实 API 对照评估；测试集混合检索事实准确率为 39.7%，全文检索为 24.6%，同时报告图扩展未提升的结果。
- 实现结构化事实与引用校验、持久化调用限额和费用账本；提供真实 Neo4j 集成测试、容器运行和新实例备份恢复验证流程。

## English résumé wording

**DepScope — Evidence-grounded dependency risk investigation**

- Built a Neo4j/FastAPI/React application with immutable dependency snapshots, OSV advisory normalization, source-linked impact paths and scoped AI investigation.
- Curated 45 public resolution snapshots across 10 package families; evaluated four retrieval strategies over 200 frozen questions with 800 live API calls. Hybrid exact-fact accuracy was 39.7% (50/126) versus 24.6% (31/126) for full-text on the test set; graph expansion did not improve it.
- Implemented structured-fact/citation validation, persistent API cost limits, real Neo4j integration checks and container/backup-restore workflows.

Choose two or three bullets for a specific role. For data-science applications, emphasize independent labels, failure denominators and descriptive family bootstrap. For platform/AI engineering, emphasize context isolation, provenance, bounded persistence and cost safety. Do not change program labels to “human-reviewed,” public cases to customers, or workflow availability to verified deployment without corresponding records.
