"""Accept only locally signed verification reports from the two controlled project workflows."""
import hashlib
import hmac
import json
import os
import re
from pathlib import Path
from typing import Literal

from packaging.requirements import InvalidRequirement, Requirement

from depscope.identity.coordinates import normalized_name
from depscope.ingest.models import Contract
from depscope.runtime.errors import DomainError
from depscope.sources.records import RecordStore

TRUSTED_PRODUCERS={"depscope.local-backend-v1","depscope.example-assistant-v1"}


class VerificationRecord(Contract):
    kind: Literal["resolution","tests"]
    environment: dict
    source_hashes: dict[str,str]
    command: tuple[str,...]
    exit_code: int | None
    observed_at: str
    result_digest: str
    producer: str


def verification_level(resolution_ok: bool, tests_ok: bool,
                       environment_known: bool, constraints_complete: bool) -> str:
    if not resolution_ok or not environment_known or not constraints_complete:
        return "metadata_comparison"
    return "tests_verified" if tests_ok else "resolution_verified"


def environment_known(environment: dict) -> bool:
    keys=("os","architecture","python_version")
    return all(isinstance(environment.get(k),str) and environment[k] not in ("","unknown") for k in keys) and isinstance(environment.get("extras"),list)


def constraints_satisfied(snapshot,declarations: list[dict]) -> bool:
    if snapshot.root_id is None or any(not c.dependencies_known or c.coordinate is None for c in snapshot.components):
        return False
    components={c.local_id:c for c in snapshot.components}
    declared={(r.get("from_id"),r.get("to_id")):r.get("requirement") for r in declarations}
    for edge in snapshot.edges:
        expression=edge.requirement or declared.get((edge.from_id,edge.to_id))
        if not isinstance(expression,str) or not expression:
            return False
        coordinate=components[edge.to_id].coordinate
        try:
            requirement=Requirement(expression)
            if normalized_name(requirement.name) != coordinate.name:
                return False
            if not requirement.specifier.contains(coordinate.version,prereleases=True):
                return False
            if requirement.marker:
                markers=snapshot.environment.get("marker_environment")
                if not isinstance(markers,dict):
                    return False
                if "extra" in str(requirement.marker):
                    return False  # selected transitive extras are not proven by an installed inventory
                if not requirement.marker.evaluate(markers):
                    return False
        except (InvalidRequirement,ValueError,KeyError):
            return False
    return True


class VerificationRegistry:
    def __init__(self,root: Path):
        self.root=Path(root)
        self.directory=self.root/"verifications"
        self.records=RecordStore(self.root)

    def _key(self,create=False) -> bytes:
        path=self.directory/".signing-key"
        if create:
            path.parent.mkdir(parents=True,exist_ok=True)
            try:
                descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(descriptor,"wb") as file:
                    file.write(os.urandom(32))
            except FileExistsError:
                pass
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise DomainError("UNTRUSTED_VERIFICATION", "No trusted local verification exists") from None

    @staticmethod
    def _canonical(payload):
        return json.dumps(payload,sort_keys=True,separators=(",", ":"),ensure_ascii=False).encode()

    def write_trusted_report(self,records: tuple[VerificationRecord,...],project_id: str,
                             snapshot_id: str,output: Path) -> None:
        # Called only by controlled local runners, never exposed through an HTTP upload route.
        if any(r.producer not in TRUSTED_PRODUCERS for r in records):
            raise DomainError("UNTRUSTED_VERIFICATION", "Unknown local verification producer")
        payload={"project_id":project_id,"snapshot_id":snapshot_id,
                 "records":[record.model_dump(mode="json") for record in records]}
        signature=hmac.new(self._key(create=True),self._canonical(payload),hashlib.sha256).hexdigest()
        output=Path(output)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps({"payload":payload,"signature":signature},indent=2)+"\n")

    def _read(self,raw: bytes) -> dict:
        try:
            doc=json.loads(raw)
            payload=doc["payload"]
            expected=hmac.new(self._key(),self._canonical(payload),hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected,doc["signature"]):
                raise ValueError
            typed=tuple(VerificationRecord.model_validate_json(json.dumps(r)) for r in payload["records"])
            if any(r.producer not in TRUSTED_PRODUCERS for r in typed):
                raise ValueError
            for record in typed:
                for digest in (*record.source_hashes.values(),record.result_digest):
                    self.records.get(digest)
            return payload | {"typed_records":typed}
        except (ValueError,TypeError,KeyError):
            raise DomainError("UNTRUSTED_VERIFICATION", "Verification report is unsigned or modified") from None

    def register(self,report_path: Path,project_id: str,snapshot_id: str) -> str:
        raw=Path(report_path).read_bytes()
        payload=self._read(raw)
        if payload["project_id"]!=project_id or payload["snapshot_id"]!=snapshot_id:
            raise DomainError("VERIFICATION_CONTEXT_MISMATCH", "Verification belongs to another context")
        id=hashlib.sha256(raw).hexdigest()
        self.directory.mkdir(parents=True,exist_ok=True)
        (self.directory/(id+".json")).write_bytes(raw)
        return id

    def lookup(self,id: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{64}",id):
            raise DomainError("UNTRUSTED_VERIFICATION", "Invalid verification identifier")
        try:
            raw=(self.directory/(id+".json")).read_bytes()
        except FileNotFoundError:
            raise DomainError("UNTRUSTED_VERIFICATION", "Verification is not locally registered") from None
        if hashlib.sha256(raw).hexdigest()!=id:
            raise DomainError("UNTRUSTED_VERIFICATION", "Verification registry digest mismatch")
        return self._read(raw)

    def level(self,before,after,verification_id: str | None) -> str:
        if verification_id is None:
            return "metadata_comparison"
        payload=self.lookup(verification_id)
        if payload["project_id"]!=after.project_id or payload["snapshot_id"]!=after.snapshot_id:
            raise DomainError("VERIFICATION_CONTEXT_MISMATCH", "Verification is not for this candidate")
        records=payload["typed_records"]
        known=(before.source_kind==after.source_kind=="observed_environment" and
               before.project_id==after.project_id and environment_known(before.environment) and
               before.environment==after.environment)
        resolution=next((r for r in records if r.kind=="resolution"),None)
        tests=next((r for r in records if r.kind=="tests"),None)
        constraints=False
        resolution_ok=False
        if resolution and resolution.environment==after.environment and resolution.source_hashes.get("snapshot")==after.source.digest:
            if resolution.source_hashes.get("constraints"):
                report=json.loads(self.records.get(resolution.source_hashes["constraints"]))
                constraints=(report.get("snapshot_digest")==after.source.digest and
                             report.get("environment")==after.environment and
                             constraints_satisfied(after,report.get("declarations",[])))
            resolution_ok=resolution.exit_code==0 and bool(resolution.command)
        tests_ok=False
        if tests and tests.exit_code==0 and tests.command and tests.environment==after.environment and tests.source_hashes.get("snapshot")==after.source.digest:
            report=json.loads(self.records.get(tests.result_digest))
            tests_ok=(report.get("exit_code")==0 and tuple(report.get("command",[]))==tests.command and
                      report.get("snapshot_digest")==after.source.digest and report.get("environment")==after.environment)
        return verification_level(resolution_ok,tests_ok,known,constraints)
