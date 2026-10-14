import asyncio
import hashlib
import json
import os
import uuid
from datetime import UTC
from pathlib import Path

from depscope.analysis.comparison import Comparison, compare_known_findings, compare_packages
from depscope.identity.coordinates import identify, normalized_name
from depscope.ingest.depsdev import parse_depsdev
from depscope.ingest.models import Contract, SourceRef
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now
from depscope.sources.depsdev import dependencies_uri
from depscope.sources.http import PublicClient
from depscope.sources.pypi import package_uri, select_versions

from .selection import family_name, missing_years


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as file:
        json.dump(value, file, ensure_ascii=False, sort_keys=True, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


class PublicCase(Contract):
    id: str
    package: str
    version: str
    family_name: str
    project_id: str
    snapshot_id: str
    run_id: str
    source_kind: str = "public_resolution"
    source_digest: str
    observed_at: str
    completeness: str


class CorpusManifest(Contract):
    id: str
    cutoff: str
    case_ids: tuple[str, ...]
    source_hashes: dict[str, str]
    exclusions: tuple[dict, ...]
    actual_counts: dict[str, int]
    cases: tuple[PublicCase, ...]
    comparison_ids: tuple[str, ...]
    observed_at: str
    notes: tuple[str, ...]


class CorpusCollector:
    def __init__(
        self, services, public=None, checkpoint_root=None, cancelled=lambda: False, owner=None
    ):
        self.services = services
        self.public = public or PublicClient()
        self.checkpoint_root = Path(checkpoint_root or services.records.root / "corpus-checkpoints")
        self.cancelled = cancelled
        self.owner = owner or "corpus:" + uuid.uuid4().hex

    async def collect(self, packages, cutoff):
        if cutoff.tzinfo is None:
            raise DomainError("INVALID_CUTOFF", "Explicit timezone-aware corpus cutoff required")
        packages = tuple(dict.fromkeys(normalized_name(p) for p in packages))
        plan = {
            "packages": packages,
            "cutoff": cutoff.astimezone(UTC).isoformat(),
            "selection": "latest-earliest2024-earliest2025-v1",
        }
        home = self.checkpoint_root / _digest(plan)
        checkpoint = home / "checkpoint.json"
        completed = home / "manifest.json"
        if completed.exists():
            manifest = CorpusManifest.model_validate_json(completed.read_bytes())
            if _digest(manifest.model_dump(mode="json", exclude={"id"})) != manifest.id:
                raise DomainError("CORPUS_INTEGRITY", "Frozen corpus manifest was modified")
            for digest in manifest.source_hashes.values():
                await asyncio.to_thread(self.services.records.get, digest)
            return manifest
        state = (
            json.loads(checkpoint.read_bytes())
            if checkpoint.exists()
            else {
                "plan": plan,
                "roots": {},
                "exclusions": [],
                "sources": {},
                "snapshots": [],
                "collection_id": uuid.uuid4().hex,
            }
        )

        def save():
            _save(checkpoint, state)

        def remember(source):
            state["sources"][source.digest] = source.digest

        for package in packages:
            if self.cancelled():
                raise DomainError("CANCELLED", "Corpus collection cancelled")
            root = state["roots"].setdefault(package, {})
            if "metadata" not in root and "metadata_error" not in root:
                uri = package_uri(package)
                try:
                    raw = await self.public.get_raw(uri, cancelled=self.cancelled)
                    metadata = json.loads(raw)
                    if normalized_name(metadata["info"]["name"]) != package:
                        raise DomainError(
                            "SOURCE_IDENTITY_MISMATCH",
                            "PyPI metadata package differs from requested root",
                        )
                    source = await asyncio.to_thread(self.services.records.put, raw, uri, now())
                    remember(source)
                    root["metadata"] = source.model_dump(mode="json")
                    root["versions"] = list(select_versions(metadata, cutoff))
                    root["selected_count"] = len(root["versions"])
                    state["exclusions"].extend(
                        {"package": package, "year": year, "reason": "missing_year"}
                        for year in missing_years(metadata, cutoff)
                    )
                    if not root["versions"]:
                        state["exclusions"].append(
                            {"package": package, "reason": "no_stable_version"}
                        )
                    root["project_id"] = await asyncio.to_thread(
                        self.services.snapshots.create_project,
                        package + " · public cases " + cutoff.date().isoformat(),
                        "ecosystem_case",
                    )
                except (DomainError, ValueError, KeyError, TypeError) as exc:
                    if isinstance(exc, DomainError) and exc.code == "CANCELLED":
                        raise
                    root["metadata_error"] = (
                        exc.code if isinstance(exc, DomainError) else "SOURCE_INVALID_JSON"
                    )
                    state["exclusions"].append(
                        {
                            "package": package,
                            "reason": "metadata_error",
                            "code": root["metadata_error"],
                            "uri": uri,
                        }
                    )
                save()
            if "metadata_error" in root:
                continue
            for version in root["versions"]:
                outcome = root.setdefault("outcomes", {}).setdefault(version, {})
                if "snapshot_id" in outcome or "error" in outcome:
                    continue
                coordinate = identify(package, version, None)
                uri = dependencies_uri(coordinate)
                try:
                    if "source" not in outcome:
                        raw = await self.public.get_raw(uri, cancelled=self.cancelled)
                        source = await asyncio.to_thread(self.services.records.put, raw, uri, now())
                        remember(source)
                        outcome["source"] = source.model_dump(mode="json")
                        save()
                    source = SourceRef.model_validate_json(json.dumps(outcome["source"]))
                    raw = await asyncio.to_thread(self.services.records.get, source.digest)
                    snapshot = parse_depsdev(raw, root["project_id"], source)
                    if (
                        not snapshot.components
                        or snapshot.components[0].coordinate is None
                        or (
                            snapshot.components[0].coordinate.name,
                            snapshot.components[0].coordinate.raw_version,
                        )
                        != (package, version)
                    ):
                        raise DomainError(
                            "SOURCE_IDENTITY_MISMATCH",
                            "Resolved root differs from requested package/version",
                        )
                    sid = await asyncio.to_thread(
                        self.services.snapshots.publish,
                        snapshot,
                        self.owner,
                        cancelled=self.cancelled,
                    )
                    outcome["snapshot_id"] = sid
                    state["snapshots"].append(sid)
                except (DomainError, ValueError, KeyError, TypeError) as exc:
                    if isinstance(exc, DomainError) and exc.code == "CANCELLED":
                        raise
                    outcome["error"] = (
                        exc.code if isinstance(exc, DomainError) else "SOURCE_INVALID_JSON"
                    )
                    state["exclusions"].append(
                        {
                            "package": package,
                            "version": version,
                            "reason": "resolution_error",
                            "code": outcome["error"],
                            "uri": uri,
                            "source_digest": outcome.get("source", {}).get("digest"),
                        }
                    )
                save()
                print(
                    "Corpus:",
                    package,
                    version,
                    "ready" if "snapshot_id" in outcome else outcome["error"],
                    flush=True,
                )
        from depscope.analysis.metrics import completeness

        if "run_map" not in state:
            runs = (
                await self.services.match_service.collect(
                    tuple(state["snapshots"]), state["collection_id"]
                )
                if state["snapshots"]
                else {}
            )
            state["run_map"] = {sid: run.id for sid, run in runs.items()}
            save()
        cases = []
        comparisons = []
        for package, root in state["roots"].items():
            for version, outcome in root.get("outcomes", {}).items():
                if "snapshot_id" not in outcome:
                    continue
                snapshot = await asyncio.to_thread(
                    self.services.snapshots.load, outcome["snapshot_id"]
                )
                run = await asyncio.to_thread(
                    self.services.runs.load, state["run_map"][snapshot.snapshot_id]
                )
                for query in run.queries:
                    for source in query.source_refs:
                        remember(source)
                for rid in run.revision_ids:
                    remember((await asyncio.to_thread(self.services.runs.revision, rid)).source)
                if completeness(snapshot).state != "complete" and not any(
                    row.get("snapshot_id") == snapshot.snapshot_id for row in state["exclusions"]
                ):
                    state["exclusions"].append(
                        {
                            "package": package,
                            "version": version,
                            "reason": "partial_resolution",
                            "snapshot_id": snapshot.snapshot_id,
                            "source_digest": snapshot.source.digest,
                            "issues": list(snapshot.issues),
                        }
                    )
                cases.append(
                    PublicCase(
                        id=_digest([snapshot.snapshot_id, run.id]),
                        package=package,
                        version=version,
                        family_name=family_name(package),
                        project_id=snapshot.project_id,
                        snapshot_id=snapshot.snapshot_id,
                        run_id=run.id,
                        source_digest=snapshot.source.digest,
                        observed_at=snapshot.source.observed_at,
                        completeness=completeness(snapshot).state,
                    )
                )
            relevant = [c for c in cases if c.package == package]
            if len(relevant) < 2:
                continue
            latest = next((c for c in relevant if c.version == root["versions"][0]), None)
            if latest is None:
                continue
            for baseline in relevant:
                if baseline.id == latest.id:
                    continue
                a, b = await asyncio.gather(
                    asyncio.to_thread(self.services.snapshots.load, baseline.snapshot_id),
                    asyncio.to_thread(self.services.snapshots.load, latest.snapshot_id),
                )
                ra, rb = (
                    self.services.runs.load(baseline.run_id),
                    self.services.runs.load(latest.run_id),
                )
                diff = compare_known_findings(ra, rb, a, b)
                comparison = Comparison(
                    id=_digest([state["collection_id"], a.snapshot_id, b.snapshot_id]),
                    baseline_id=a.snapshot_id,
                    candidate_id=b.snapshot_id,
                    run_ids=(ra.id, rb.id),
                    collection_id=state["collection_id"],
                    diff=compare_packages(a, b),
                    removed_known_matches=diff.removed_known_matches,
                    unknown=diff.unknown,
                    level="metadata_comparison",
                    limitations=(
                        "Current public resolutions; no verified installation or historical deployed environment.",
                    ),
                    observed_at=ra.observed_at,
                    added_known_matches=diff.added_known_matches,
                    remaining_known_matches=diff.remaining_known_matches,
                )
                await asyncio.to_thread(self.services.comparisons.save, comparison)
                comparisons.append(comparison.id)
        content = {
            "cutoff": plan["cutoff"],
            "case_ids": tuple(c.id for c in cases),
            "source_hashes": state["sources"],
            "exclusions": tuple(state["exclusions"]),
            "actual_counts": {
                "requested_roots": len(packages),
                "selected_versions": sum(
                    r.get("selected_count", 0) for r in state["roots"].values()
                ),
                "successful_snapshots": sum(c.completeness == "complete" for c in cases),
                "published_snapshots": len(cases),
                "partial_or_unknown_snapshots": sum(c.completeness != "complete" for c in cases),
                "successful_families": len({c.family_name for c in cases}),
                "source_records": len(state["sources"]),
                "comparisons": len(comparisons),
            },
            "cases": tuple(cases),
            "comparison_ids": tuple(comparisons),
            "observed_at": now(),
            "notes": (
                "Root release selection respects the explicit cutoff. Dependency resolution and advisory acquisition are current at collection, not reconstructed historical environments.",
                "No selected version is replaced because of a failure or its benchmark performance.",
            ),
        }
        draft = CorpusManifest(id="pending", **content)
        manifest = draft.model_copy(
            update={"id": _digest(draft.model_dump(mode="json", exclude={"id"}))}
        )
        _save(completed, manifest.model_dump(mode="json"))
        save()
        return manifest

    def export(self, manifest, output):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        observations = {}
        for digest in manifest.source_hashes.values():
            path = output / "raw" / digest
            raw = self.services.records.get(digest)
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise DomainError("CORPUS_INTEGRITY", "Exported raw source was modified")
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            observations[digest] = [
                s.model_dump(mode="json")
                for s in self.services.records.observations(digest)
                if s.uri.startswith(
                    ("https://pypi.org/", "https://api.deps.dev/", "https://api.osv.dev/")
                )
            ]
        for case in manifest.cases:
            _save(
                output / "snapshots" / (case.snapshot_id + ".json"),
                self.services.snapshots.load(case.snapshot_id).model_dump(mode="json"),
            )
            _save(
                output / "match-runs" / (case.run_id + ".json"),
                self.services.runs.load(case.run_id).model_dump(mode="json"),
            )
        for id in manifest.comparison_ids:
            _save(
                output / "comparisons" / (id + ".json"),
                self.services.comparisons.load(id).model_dump(mode="json"),
            )
        _save(output / "sources.json", observations)
        _save(output / "manifest.json", manifest.model_dump(mode="json"))
