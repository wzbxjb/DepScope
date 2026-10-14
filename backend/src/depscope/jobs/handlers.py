import asyncio

from depscope.ingest.cyclonedx import parse_cyclonedx
from depscope.ingest.depsdev import parse_depsdev
from depscope.ingest.models import SourceRef
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now
from depscope.sources.http import PublicClient


def import_handler(store, repo, records):
    async def handle_import(job, cancelled):
        if cancelled():
            raise DomainError("CANCELLED", "Import cancelled")
        payload = job.payload
        if payload.get("uri"):
            await asyncio.to_thread(
                store.transition, job.id, "validating", "fetching", job.owner_token
            )
            raw = await PublicClient().get_raw(payload["uri"], cancelled=cancelled)
            source = await asyncio.to_thread(records.put, raw, payload["uri"], now())
            bound = await asyncio.to_thread(
                store.bind_import_source, job.id, job.owner_token, source.model_dump(mode="json")
            )
            if not bound:
                raise DomainError("CANCELLED", "Import no longer owns its source binding")
            expected = "fetching"
        else:
            raw = await asyncio.to_thread(records.get, payload["digest"])
            observations = await asyncio.to_thread(records.observations, payload["digest"])
            source = (
                SourceRef(**payload["source_ref"])
                if payload.get("source_ref")
                else observations[-1]
            )
            expected = "validating"
        if payload["source_kind"] == "public_resolution":
            snapshot = await asyncio.to_thread(parse_depsdev, raw, payload["project_id"], source)
        else:
            snapshot = await asyncio.to_thread(
                parse_cyclonedx, raw, payload["project_id"], source, payload.get("environment", {})
            )
        if payload["source_kind"] == "constructed":
            from depscope.identity.coordinates import snapshot_key

            snapshot = snapshot.model_copy(
                update={
                    "source_kind": "constructed",
                    "snapshot_id": snapshot_key(
                        payload["project_id"], "constructed", source.digest
                    ),
                }
            )
        if cancelled():
            raise DomainError("CANCELLED", "Import cancelled before writing")
        await asyncio.to_thread(store.transition, job.id, expected, "writing", job.owner_token)
        return await asyncio.to_thread(
            repo.publish, snapshot, job.staging_owner, cancelled=cancelled
        )

    return handle_import
