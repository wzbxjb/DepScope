from collections.abc import AsyncIterable, Iterable

from depscope.runtime.errors import DomainError

MAX_BYTES = 10 * 1024 * 1024
MAX_COMPONENTS = 10_000
MAX_EDGES = 50_000


def read_limited(chunks: Iterable[bytes], limit: int = MAX_BYTES) -> bytes:
    output = bytearray()
    for chunk in chunks:
        if len(output) + len(chunk) > limit:
            raise DomainError("UPLOAD_TOO_LARGE", "Upload exceeds byte limit")
        output.extend(chunk)
    return bytes(output)


async def async_read_limited(chunks: AsyncIterable[bytes], limit: int = MAX_BYTES) -> bytes:
    output = bytearray()
    async for chunk in chunks:
        if len(output) + len(chunk) > limit:
            raise DomainError("UPLOAD_TOO_LARGE", "Upload exceeds byte limit")
        output.extend(chunk)
    return bytes(output)
