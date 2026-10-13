from typing import Literal

from pydantic import Field

from depscope.ingest.models import Contract

IMPORT_TRANSITIONS = {
    "queued": {"validating", "cancelled"},
    "validating": {"fetching", "writing", "failed", "cancelled", "interrupted"},
    "fetching": {"writing", "failed", "cancelled", "interrupted"},
    "writing": {"ready", "failed", "cancelled", "interrupted"},
    "interrupted": {"queued", "cancelled"},
}
ACTIVE = ("validating", "fetching", "writing")
TERMINAL = ("ready", "failed", "cancelled", "interrupted")


def can_transition(source: str, target: str) -> bool:
    return target in IMPORT_TRANSITIONS.get(source,set())


class Job(Contract):
    id: str
    kind: str
    payload: dict
    status: Literal["queued","validating","fetching","writing","ready","failed","cancelled","interrupted"]
    phase: str
    owner_token: str | None
    progress: float = Field(ge=0,le=1)
    error: dict | None
    next_attempt_at: str | None = None
    result_id: str | None = None
    cancel_requested: bool = False

    @property
    def staging_owner(self) -> str:
        return self.id + ":" + (self.owner_token or "unclaimed")
