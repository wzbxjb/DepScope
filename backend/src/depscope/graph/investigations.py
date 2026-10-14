from depscope.ingest.models import Contract
from depscope.investigation.answers import Answer
from depscope.investigation.models import InvestigationScope
from depscope.retrieval.documents import EvidenceChunk
from depscope.runtime.errors import DomainError


class InvestigationRecord(Contract):
    id: str
    question: str
    scope: InvestigationScope
    answer: Answer
    evidence_chunks: tuple[EvidenceChunk, ...]
    observed_at: str


class InvestigationRepository:
    def __init__(self, driver):
        self.driver = driver

    def save(self, record):
        with self.driver.session() as session:
            session.run(
                "CREATE CONSTRAINT investigation_identity IF NOT EXISTS FOR (r:InvestigationResult) REQUIRE r.id IS UNIQUE"
            ).consume()
            row = session.run(
                "MERGE (r:InvestigationResult {id:$id}) ON CREATE SET r.payload=$payload,r.project_ids=$projects,r.snapshot_ids=$snapshots,r.observed_at=$time RETURN r.payload AS payload",
                id=record.id,
                payload=record.model_dump_json(),
                projects=list(record.scope.project_ids),
                snapshots=list(record.scope.snapshot_ids),
                time=record.observed_at,
            ).single()
        if row["payload"] != record.model_dump_json():
            raise DomainError("INVESTIGATION_IMMUTABLE", "Stored investigation cannot be modified")

    def load(self, id):
        with self.driver.session() as session:
            row = session.run(
                "MATCH (r:InvestigationResult {id:$id}) RETURN r.payload AS payload", id=id
            ).single()
        if not row:
            raise DomainError("INVESTIGATION_NOT_FOUND", "Investigation result is unavailable")
        return InvestigationRecord.model_validate_json(row["payload"])
