import asyncio
import json
import re
from urllib.parse import quote

import httpx

from depscope.ingest.limits import MAX_BYTES
from depscope.ingest.models import Coordinate
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now

from .advisories import AdvisoryRevision, PackageQuery, parse_advisory
from .retry import request_with_retry

BASE="https://api.osv.dev/v1"


def _payload(coordinate: Coordinate) -> dict:
    return {"package":{"name":coordinate.name,"ecosystem":coordinate.ecosystem},
            "version":coordinate.raw_version}


def _page_ids(page: dict) -> tuple[str,...]:
    rows=page.get("vulns",[])
    if not isinstance(rows,list) or any(not isinstance(row,dict) or not isinstance(row.get("id"),str) for row in rows):
        raise DomainError("OSV_INVALID_RESPONSE", "Invalid advisory identifiers in response")
    return tuple(dict.fromkeys(row["id"] for row in rows))


def merge_page(current: PackageQuery, page: dict) -> PackageQuery:
    ids=tuple(dict.fromkeys(current.record_ids + _page_ids(page)))
    status="partial" if page.get("next_page_token") else ("matched" if ids else "no_match")
    return current.model_copy(update={"record_ids":ids,"status":status})


class OsvClient:
    def __init__(self, records, client=None, sleep=None, cancelled=lambda:False):
        self.records,self.client,self.sleep,self.cancelled=records,client,sleep,cancelled
        self.semaphore=asyncio.Semaphore(4)

    async def _call(self,method,uri,payload=None):
        refs=[]
        if payload is not None:
            raw=json.dumps(payload,ensure_ascii=False,separators=(",", ":")).encode()
            refs.append(await asyncio.to_thread(self.records.put,raw,uri,now()))
        try:
            async with self.semaphore:
                response=await request_with_retry(self.client,method,uri,payload,self.cancelled,self.sleep)
            raw=response.content
            if len(raw)>MAX_BYTES:
                raise DomainError("SOURCE_TOO_LARGE", "OSV response exceeds byte limit")
            refs.append(await asyncio.to_thread(self.records.put,raw,uri,now()))
            doc=json.loads(raw)
            if not isinstance(doc,dict):
                raise DomainError("OSV_INVALID_RESPONSE", "OSV response must be an object")
            return doc,tuple(refs),None,raw
        except DomainError as exc:
            if exc.code == "CANCELLED":
                raise
            return None,tuple(refs),exc,b""
        except (ValueError,UnicodeDecodeError):
            return None,tuple(refs),DomainError("OSV_INVALID_RESPONSE", "OSV returned invalid JSON"),b""

    async def query(self, coordinates: tuple[Coordinate,...]) -> tuple[PackageQuery,...]:
        if self.client is None:
            async with httpx.AsyncClient(trust_env=False) as client:
                return await OsvClient(self.records,client,self.sleep,self.cancelled).query(coordinates)
        batches=[coordinates[start:start+100] for start in range(0,len(coordinates),100)]
        async def batch(items):
            doc,refs,error,_=await self._call("POST",BASE+"/querybatch",{"queries":[_payload(c) for c in items]})
            if error or not isinstance(doc.get("results") if doc else None,list) or len(doc["results"]) != len(items):
                issue=error.code if error else "OSV_BATCH_LENGTH_MISMATCH"
                return tuple(PackageQuery(coordinate=c,status="error",source_refs=refs,issues=(issue,)) for c in items)
            async def complete(coordinate,page):
                result=PackageQuery(coordinate=coordinate,status="unqueried",source_refs=refs)
                seen=set()
                try:
                    if not isinstance(page,dict):
                        raise DomainError("OSV_INVALID_RESPONSE", "Query result must be an object")
                    result=merge_page(result,page)
                    token=page.get("next_page_token")
                    while token:
                        if not isinstance(token,str) or token in seen or len(seen)>=100:
                            return result.model_copy(update={"status":"partial","issues":("OSV_PAGINATION_INCOMPLETE",)})
                        seen.add(token)
                        payload=_payload(coordinate) | {"page_token":token}
                        next_page,next_refs,error,_=await self._call("POST",BASE+"/query",payload)
                        result=result.model_copy(update={"source_refs":result.source_refs+next_refs})
                        if error:
                            return result.model_copy(update={"status":"partial","issues":(error.code,)})
                        result=merge_page(result,next_page)
                        token=next_page.get("next_page_token")
                    return result
                except DomainError as exc:
                    return result.model_copy(update={"status":"partial" if result.record_ids else "error","issues":(exc.code,)})
            return tuple(await asyncio.gather(*(complete(c,page) for c,page in zip(items,doc["results"],strict=True))))
        results=await asyncio.gather(*(batch(items) for items in batches))
        return tuple(query for group in results for query in group)

    async def advisory(self, id: str) -> AdvisoryRevision:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}",id):
            raise DomainError("INVALID_ADVISORY_ID", "Advisory identifier is invalid")
        if self.client is None:
            async with httpx.AsyncClient(trust_env=False) as client:
                return await OsvClient(self.records,client,self.sleep,self.cancelled).advisory(id)
        _,refs,error,raw=await self._call("GET",BASE+"/vulns/"+quote(id,safe=""))
        if error:
            raise error
        return parse_advisory(raw,refs[-1],id)
