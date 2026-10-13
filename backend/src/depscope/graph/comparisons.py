from depscope.analysis.comparison import Comparison
from depscope.runtime.errors import DomainError


class ComparisonRepository:
    def __init__(self,driver):
        self.driver=driver

    def save(self,comparison: Comparison):
        def persist(tx):
            existing=tx.run("MATCH (c:Comparison {id:$id}) RETURN c.payload AS payload",id=comparison.id).single()
            if existing:
                if existing["payload"]!=comparison.model_dump_json():
                    raise DomainError("COMPARISON_IMMUTABLE", "Comparison cannot be modified")
                return
            row=tx.run("""
                MATCH (a:Snapshot {snapshot_id:$a,status:'ready'}),(b:Snapshot {snapshot_id:$b,status:'ready'})
                CREATE (c:Comparison {id:$id,baseline_id:$a,candidate_id:$b,observed_at:$time,payload:$payload})
                CREATE (c)-[:BASELINE]->(a)
                CREATE (c)-[:CANDIDATE]->(b)
                RETURN c.id AS id
                """,a=comparison.baseline_id,b=comparison.candidate_id,id=comparison.id,time=comparison.observed_at,payload=comparison.model_dump_json()).single()
            if row is None:
                raise DomainError("COMPARISON_CONTEXT_MISMATCH", "Both snapshots must be published")
            rows=list(tx.run("MATCH (c:Comparison {id:$id}) UNWIND $runs AS run MATCH (r:MatchRun {id:run,collection_id:$collection}) WHERE r.snapshot_id IN [$a,$b] CREATE (c)-[:USES_RUN]->(r) RETURN r.id AS id",
                      id=comparison.id,runs=list(comparison.run_ids),collection=comparison.collection_id,a=comparison.baseline_id,b=comparison.candidate_id))
            if len(rows)!=2:
                raise DomainError("COMPARISON_CONTEXT_MISMATCH", "Runs must belong to the shared comparison collection")
        with self.driver.session() as session:
            session.execute_write(persist)

    def load(self,id: str) -> Comparison:
        with self.driver.session() as session:
            row=session.run("MATCH (c:Comparison {id:$id}) RETURN c.payload AS payload",id=id).single()
        if row is None:
            raise DomainError("COMPARISON_NOT_FOUND", "Comparison is unavailable")
        return Comparison.model_validate_json(row["payload"])
