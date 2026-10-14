"""Independent labels from frozen original public bytes; no product paths or matching."""

import hashlib
import json
import re
from pathlib import Path

import networkx as nx

from depscope.runtime.errors import DomainError


def name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def instance(sid, index):
    return hashlib.sha256(json.dumps([sid, str(index)], separators=(",", ":")).encode()).hexdigest()


class RawReference:
    def __init__(self, home):
        self.home = Path(home)
        self.graphs = {}
        self.advisories = {}
        self.active_source_digests = set()
        for file in sorted((self.home / "raw").iterdir()):
            raw = file.read_bytes()
            if hashlib.sha256(raw).hexdigest() != file.name:
                raise DomainError("REFERENCE_INTEGRITY", "Raw reference digest differs")
            doc = json.loads(raw)
            if (
                isinstance(doc, dict)
                and "id" in doc
                and "affected" in doc
                and not doc.get("withdrawn")
            ):
                self.advisories[doc["id"]] = doc
                self.active_source_digests.add(file.name)
        aliases = nx.Graph()
        for id, doc in self.advisories.items():
            aliases.add_node(id)
            aliases.add_edges_from((id, a) for a in doc.get("aliases", []))
        self.aliases = {
            node: tuple(sorted(group))
            for group in nx.connected_components(aliases)
            for node in group
        }

    def graph(self, case):
        if case.snapshot_id not in self.graphs:
            raw = (self.home / "raw" / case.source_digest).read_bytes()
            if hashlib.sha256(raw).hexdigest() != case.source_digest:
                raise DomainError("REFERENCE_INTEGRITY", "Raw graph digest differs")
            doc = json.loads(raw)
            graph = nx.DiGraph()
            graph.add_nodes_from(range(len(doc["nodes"])))
            graph.add_edges_from((e["fromNode"], e["toNode"]) for e in doc["edges"])
            self.graphs[case.snapshot_id] = (doc, graph)
        return self.graphs[case.snapshot_id]

    def version(self, case, index):
        doc, _ = self.graph(case)
        key = doc["nodes"][index]["versionKey"]
        return {
            "kind": "version",
            "value": {
                "snapshot_id": case.snapshot_id,
                "instance_id": instance(case.snapshot_id, index),
                "package": name(key["name"]),
                "version": key["version"],
            },
        }

    def query_fact(self, case, index):
        doc, _ = self.graph(case)
        key = doc["nodes"][index]["versionKey"]
        run = json.loads((self.home / "match-runs" / (case.run_id + ".json")).read_bytes())
        query = next(
            q
            for q in run["queries"]
            if q["coordinate"]["name"] == name(key["name"])
            and q["coordinate"]["raw_version"] == key["version"]
        )
        references = query["source_refs"]
        if len(references) < 2:
            return None
        request = json.loads((self.home / "raw" / references[0]["digest"]).read_bytes())
        response = json.loads((self.home / "raw" / references[1]["digest"]).read_bytes())
        position = next(
            i
            for i, row in enumerate(request["queries"])
            if name(row["package"]["name"]) == name(key["name"])
            and row["version"] == key["version"]
        )
        pages = [response["results"][position]] + [
            json.loads((self.home / "raw" / references[i + 1]["digest"]).read_bytes())
            for i in range(2, len(references), 2)
        ]
        if pages[-1].get("next_page_token"):
            return None
        status = "matched" if any(page.get("vulns") for page in pages) else "no_match"
        if status != query["status"]:
            raise DomainError(
                "REFERENCE_DISAGREEMENT", "Original query pages disagree with recorded status"
            )
        receipt = {
            "kind": "package_query",
            "snapshot_id": case.snapshot_id,
            "run_id": case.run_id,
            "query": query,
            "observed_at": run["observed_at"],
        }
        if len(json.dumps(receipt, ensure_ascii=False, sort_keys=True)) > 2000:
            return None
        value = {
            "snapshot_id": case.snapshot_id,
            "package": name(key["name"]),
            "version": key["version"],
            "status": status,
        }
        locator = {
            "query_key": [case.snapshot_id, case.run_id, name(key["name"]), key["version"]],
            "upstream_source_ids": [ref["digest"] for ref in references],
        }
        return {"kind": "query", "value": value}, locator

    def path(self, case, target):
        doc, graph = self.graph(case)
        # Deterministic lexicographically first shortest reference path, on raw graph indices.
        path = min(nx.all_shortest_paths(graph, 0, target))
        locators = []
        for origin, destination in zip(path, path[1:], strict=False):
            i = next(
                i
                for i, e in enumerate(doc["edges"])
                if (e["fromNode"], e["toNode"]) == (origin, destination)
            )
            locators.append({"source_digest": case.source_digest, "pointer": f"/edges/{i}"})
        return {
            "kind": "path",
            "value": {
                "snapshot_id": case.snapshot_id,
                "instance_ids": [instance(case.snapshot_id, i) for i in path],
            },
        }, locators

    def recorded_groups(self, case):
        run = json.loads((self.home / "match-runs" / (case.run_id + ".json")).read_bytes())
        groups = {}
        for query in run["queries"]:
            refs = query["source_refs"]
            pages = []
            if len(refs) < 2:
                raise DomainError("REFERENCE_INCOMPLETE", "Original query response is unavailable")
            request = json.loads((self.home / "raw" / refs[0]["digest"]).read_bytes())
            response = json.loads((self.home / "raw" / refs[1]["digest"]).read_bytes())
            coordinate = query["coordinate"]
            index = next(
                i
                for i, row in enumerate(request["queries"])
                if name(row["package"]["name"]) == coordinate["name"]
                and row["version"] == coordinate["raw_version"]
            )
            pages.append(response["results"][index])
            for offset in range(2, len(refs), 2):
                pages.append(
                    json.loads((self.home / "raw" / refs[offset + 1]["digest"]).read_bytes())
                )
            if pages[-1].get("next_page_token"):
                raise DomainError("REFERENCE_INCOMPLETE", "Original query pagination is incomplete")
            found = set()
            for page in pages:
                for row in page.get("vulns", []):
                    id = row["id"]
                    if id in self.advisories and any(
                        a.get("package", {}).get("ecosystem") == "PyPI"
                        and name(a.get("package", {}).get("name", "")) == coordinate["name"]
                        for a in self.advisories[id]["affected"]
                    ):
                        found.add(self.aliases[id])
            groups.setdefault(coordinate["name"], set()).update(found)
        return groups

    def comparison_sources(self, cases):
        sources = set()
        for case in cases:
            run = json.loads((self.home / "match-runs" / (case.run_id + ".json")).read_bytes())
            sources.update(
                ref["digest"] for query in run["queries"] for ref in query["source_refs"]
            )
        # Connected-component alias labels use the frozen active advisory corpus.
        sources.update(self.active_source_digests)
        return sources

    def comparison(self, before, after, comparison_id):
        a, b = self.recorded_groups(before), self.recorded_groups(after)
        return {
            "level": "metadata_comparison",
            "removed_known_matches": sum(
                len(values - b.get(package, set())) for package, values in a.items()
            ),
            "added_known_matches": sum(
                len(values - a.get(package, set())) for package, values in b.items()
            ),
            "remaining_known_matches": sum(len(values) for values in b.values()),
            "unknown": 0,
        }
