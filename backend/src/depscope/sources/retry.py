"""Bounded public HTTP retries, with interruptible waits and safe errors."""
import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from depscope.runtime.errors import DomainError


async def _interruptible_wait(seconds: float, cancelled: Callable[[], bool]):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cancelled():
            raise DomainError("CANCELLED", "Source collection cancelled")
        await asyncio.sleep(min(.1, max(0, end - time.monotonic())))


def _retry_after(response: httpx.Response, fallback: float) -> float:
    value = response.headers.get("Retry-After")
    if not value:
        return fallback
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            seconds = (date - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return fallback
    return max(0, seconds) if seconds < float("inf") else fallback


async def request_with_retry(client: httpx.AsyncClient, method: str, uri: str,
                             payload: dict | None = None,
                             cancelled: Callable[[], bool] = lambda: False,
                             sleep: Callable[[float], Awaitable] | None = None) -> httpx.Response:
    for attempt in range(4):
        if cancelled():
            raise DomainError("CANCELLED", "Source collection cancelled")
        response = None
        try:
            response = await client.request(method, uri, json=payload, timeout=20,
                                            follow_redirects=False)
            if 200 <= response.status_code < 300:
                return response
            retryable = response.status_code == 429 or response.status_code >= 500
            if not retryable:
                raise DomainError("SOURCE_HTTP_ERROR", "Public source rejected the request",
                                  retryable=False)
        except (httpx.TimeoutException, httpx.NetworkError):
            pass
        if attempt == 3:
            break
        delay = float((2,4,8)[attempt])
        if response is not None and response.status_code == 429:
            delay = _retry_after(response, delay)
        if sleep is None:
            await _interruptible_wait(delay, cancelled)
        else:
            await sleep(delay)
        if cancelled():
            raise DomainError("CANCELLED", "Source collection cancelled")
    raise DomainError("SOURCE_UNAVAILABLE", "Public source failed after bounded retries",
                      retryable=True)
