from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from depscope.runtime.errors import DomainError
from depscope.sources.retry import _retry_after, request_with_retry


def test_retry_after_supports_http_date_and_seconds():
    date=format_datetime(datetime.now(UTC)+timedelta(seconds=15),usegmt=True)
    assert 13 <= _retry_after(httpx.Response(429,headers={"Retry-After":date}),2) <= 15
    assert _retry_after(httpx.Response(429,headers={"Retry-After":"3"}),2) == 3
    assert _retry_after(httpx.Response(429,headers={"Retry-After":"invalid"}),2) == 2


async def test_auth_error_is_not_retried_or_exposed(respx_mock,caplog):
    route=respx_mock.post("https://api.osv.dev/v1/querybatch").respond(401,json={"credential":"sentinel-secret"})
    async with httpx.AsyncClient() as http:
        with pytest.raises(DomainError) as exc:
            await request_with_retry(http,"POST","https://api.osv.dev/v1/querybatch",{})
    assert route.call_count == 1 and "sentinel-secret" not in str(exc.value)
    assert "sentinel-secret" not in caplog.text
