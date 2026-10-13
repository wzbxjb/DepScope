import json
import time
import uuid

from depscope.graph.jobs import locked_lease
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now

from .models import ACTIVE, TERMINAL, Job, can_transition


class JobStore:
    def __init__(self, driver, clock=time.time, lease_seconds=30):
        self.driver=driver
        self.clock=clock
        self.lease_seconds=lease_seconds
        self._cancelled=set()

    def enqueue(self, kind: str, payload: dict) -> Job:
        job_id=str(uuid.uuid4())
        with self.driver.session() as session:
            session.run("CREATE (:Job {id:$id,kind:$kind,payload:$payload,status:'queued',phase:'queued',progress:0.0,cancel_requested:false,created_at:$time})",
                        id=job_id,kind=kind,payload=json.dumps(payload),time=now()).consume()
        return self.get(job_id)

    def get(self, job_id: str) -> Job:
        with self.driver.session() as session:
            row=session.run("MATCH (j:Job {id:$id}) RETURN properties(j) AS job",id=job_id).single()
        if row is None:
            raise DomainError("JOB_NOT_FOUND", "Job is unavailable")
        value=row["job"]
        return Job(id=value["id"],kind=value["kind"],payload=json.loads(value["payload"]),
                   status=value["status"],phase=value["phase"],owner_token=value.get("owner_token"),
                   progress=float(value["progress"]),error=json.loads(value["error"]) if value.get("error") else None,
                   next_attempt_at=value.get("next_attempt_at"),result_id=value.get("result_id"),
                   cancel_requested=value.get("cancel_requested",False))

    def pending(self) -> tuple[str, ...]:
        with self.driver.session() as session:
            return tuple(row["id"] for row in session.run("MATCH (j:Job {status:'queued'}) RETURN j.id AS id ORDER BY j.created_at,j.id LIMIT 50"))

    def claim(self, job_id: str, owner_token: str) -> bool:
        def acquire(tx):
            lease=locked_lease(tx)
            if lease.get("owner_token"):
                return False
            row=tx.run("MATCH (j:Job {id:$id}) SET j.lock_version=coalesce(j.lock_version,0)+1 RETURN j.status AS status,j.cancel_requested AS cancelled",id=job_id).single()
            if row is None or row["status"] != "queued" or row["cancelled"]:
                return False
            tx.run("MATCH (j:Job {id:$id}),(l:MutationLease {id:'global'}) SET j.status='validating',j.phase='validating',j.owner_token=$owner,l.owner_token=$owner,l.job_id=$id,l.heartbeat=$time",
                   id=job_id,owner=owner_token,time=self.clock()).consume()
            return True
        with self.driver.session() as session:
            claimed=session.execute_write(acquire)
        if claimed:
            self._cancelled.discard(job_id)
        return claimed

    def transition(self, job_id: str, expected: str, target: str, owner_token: str | None = None,
                   error: dict | None = None, result_id: str | None = None) -> bool:
        if not can_transition(expected,target):
            raise DomainError("INVALID_JOB_TRANSITION", "Job transition is not permitted")
        def move(tx):
            locked_lease(tx)
            row=tx.run("MATCH (j:Job {id:$id}) SET j.lock_version=coalesce(j.lock_version,0)+1 RETURN j.status AS status,j.owner_token AS owner",id=job_id).single()
            if row is None or row["status"] != expected or (owner_token is not None and row["owner"] != owner_token):
                return False
            tx.run("MATCH (j:Job {id:$id}) SET j.status=$target,j.phase=$target,j.error=$error,j.result_id=$result,j.progress=$progress,j.updated_at=$time",
                   id=job_id,target=target,error=json.dumps(error) if error else None,result=result_id,
                   progress=1.0 if target=="ready" else {"queued":0.0,"validating":.1,"fetching":.3,"writing":.7}.get(target,0.0),time=now()).consume()
            if target in TERMINAL:
                tx.run("MATCH (l:MutationLease {id:'global',job_id:$id}) SET l.owner_token=null,l.job_id=null,l.heartbeat=null",id=job_id).consume()
            return True
        with self.driver.session() as session:
            return session.execute_write(move)

    def request_cancel(self, job_id: str) -> None:
        def cancel(tx):
            locked_lease(tx)
            row=tx.run("MATCH (j:Job {id:$id}) SET j.lock_version=coalesce(j.lock_version,0)+1 RETURN j.status AS status",id=job_id).single()
            if row is None:
                raise DomainError("JOB_NOT_FOUND", "Job is unavailable")
            if row["status"] in ("ready","failed","cancelled"):
                return False
            tx.run("MATCH (j:Job {id:$id}) SET j.cancel_requested=true",id=job_id).consume()
            if row["status"] in ("queued","interrupted"):
                tx.run("MATCH (j:Job {id:$id}) SET j.status='cancelled',j.phase='cancelled'",id=job_id).consume()
            return True
        with self.driver.session() as session:
            if session.execute_write(cancel):
                self._cancelled.add(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        # Poller refreshes cross-process state; same-process requests update immediately.
        return job_id in self._cancelled

    def heartbeat(self, job_id: str, owner_token: str) -> bool:
        def refresh(tx):
            locked_lease(tx)
            row=tx.run("MATCH (l:MutationLease {id:'global',owner_token:$owner,job_id:$id}),(j:Job {id:$id,owner_token:$owner}) WHERE j.status IN $active SET l.heartbeat=$time RETURN j.cancel_requested AS cancelled",
                       owner=owner_token,id=job_id,active=list(ACTIVE),time=self.clock()).single()
            return None if row is None else row["cancelled"]
        with self.driver.session() as session:
            cancelled=session.execute_write(refresh)
        if cancelled is None or cancelled:
            self._cancelled.add(job_id)
        return cancelled is not None

    def mark_interrupted(self, only_stale: bool = False) -> int:
        """Forced recovery is reserved for explicit exclusive lifecycle operations."""
        def recover(tx):
            lease=locked_lease(tx)
            if only_stale and lease.get("owner_token") and lease.get("heartbeat",0)>self.clock()-self.lease_seconds:
                return 0
            count=tx.run("MATCH (j:Job) WHERE j.status IN $active SET j.status='interrupted',j.phase='interrupted',j.owner_token=null RETURN count(j) AS n",active=list(ACTIVE)).single()["n"]
            tx.run("MATCH (l:MutationLease {id:'global'}) SET l.owner_token=null,l.job_id=null,l.heartbeat=null").consume()
            return count
        with self.driver.session() as session:
            return session.execute_write(recover)
