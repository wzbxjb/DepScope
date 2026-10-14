# Private backup and new-instance restore

Backups are private: they contain raw/model evidence and the local verification signing key. They exclude `.env`, API keys, system user/role metadata and disposable embedding/corpus computation caches. The native Neo4j dump includes the graph, indexes, jobs, immutable experiment anchors and the full generation cost ledger. Source bytes, observation journal and verification records are copied and hashed separately.

Stop any native API/worker and finish active generation first. The CLI refuses active jobs/pending calls, stops the selected local Compose writers and database, creates an offline dump, copies sources, verifies digests, then restarts the original services. Existing volumes are retained. A source-state mismatch fails the backup. The process requires a local Docker Compose instance matching the configured loopback database; it does not back up an arbitrary remote server.

```sh
backend/.venv/bin/python -m depscope.cli backup --output artifacts/private/backups/local-v1
backend/.venv/bin/python -m depscope.cli restore --input artifacts/private/backups/local-v1 --new-instance --instance depscope-restore-validation
```

Restore always requires a **new** instance/volume and a new private data directory. Defaults: database 17790, console 17791, API 18101, UI 18080. Supply explicit distinct ports if occupied. The source instance remains intact. The loader verifies every declared file digest/path, uses a fixed pinned Neo4j image/command and refuses an existing target. No uploaded command string is executed.

After startup, compare node/relationship counts, all ready snapshot IDs, complete budget summaries and every copied evidence hash with the source manifest. The restore result records those checks. Browse historical experiments/source records through the restored API without calling a generation service. New authentication comes from the local `.env`; the source `system` database is deliberately not restored.

Reference: [Neo4j offline dump/load](https://neo4j.com/docs/operations-manual/current/docker/dump-load/). The actual 5.26 image CLI is used; no Enterprise online-backup feature is claimed.
