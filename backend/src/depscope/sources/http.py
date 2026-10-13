from urllib.parse import urlsplit

import httpx

from depscope.ingest.limits import MAX_BYTES
from depscope.runtime.errors import DomainError

from .retry import request_with_retry


def validate_public_uri(uri: str) -> None:
    try:
        parsed = urlsplit(uri)
        accepted = (parsed.scheme == "https" and parsed.hostname in
                    {"pypi.org", "api.deps.dev", "api.osv.dev"} and parsed.port in (None,443)
                    and not parsed.username and not parsed.password and not parsed.fragment
                    and not parsed.query)
    except ValueError:
        accepted = False
    if not accepted:
        raise DomainError("SOURCE_URL_REJECTED", "Only fixed official public source URLs are allowed")


class PublicClient:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client

    async def get_raw(self, uri: str, cancelled=lambda:False) -> bytes:
        validate_public_uri(uri)
        if self.client is None:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await request_with_retry(client, "GET", uri,cancelled=cancelled)
        else:
            response = await request_with_retry(self.client, "GET", uri,cancelled=cancelled)
        if len(response.content) > MAX_BYTES:
            raise DomainError("SOURCE_TOO_LARGE", "Public source response exceeds byte limit")
        return response.content

    async def get_json(self, uri: str) -> dict:
        import json
        try:
            result = json.loads(await self.get_raw(uri))
        except (ValueError, UnicodeDecodeError):
            raise DomainError("SOURCE_INVALID_JSON", "Public source returned invalid JSON") from None
        if not isinstance(result, dict):
            raise DomainError("SOURCE_INVALID_JSON", "Public source response must be an object")
        return result
