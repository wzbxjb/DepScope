import json
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from depscope.generation.deepseek import DeepSeekGeneration
from depscope.generation.models import Message
from depscope.generation.pricing import estimate_cost, official_price, reservation_cost
from depscope.runtime.errors import DomainError


def test_official_estimates_use_cache_split_and_never_unknown_as_zero():
    price = official_price("https://api.deepseek.com", "deepseek-flash")
    assert estimate_cost({"prompt_tokens": 100, "completion_tokens": 10}, price) == Decimal(
        "0.000042"
    )
    assert estimate_cost(
        {
            "prompt_tokens": 100,
            "prompt_cache_hit_tokens": 60,
            "prompt_cache_miss_tokens": 40,
            "completion_tokens": 10,
        },
        price,
    ) == Decimal("0.00002436")
    for usage in (None, {}, {"prompt_tokens": -1, "completion_tokens": 1}, {"prompt_tokens": 1}):
        assert estimate_cost(usage, price) is None
    assert official_price("https://proxy.test", "deepseek-flash") is None
    assert estimate_cost({"prompt_tokens": 1, "completion_tokens": 1}, None) is None
    assert reservation_cost((Message(role="user", content="中文"),), 16, price) > Decimal(
        "0.0000192"
    )


async def test_deepseek_http_contract_and_actual_usage(respx_mock):
    route = respx_mock.post("https://api.deepseek.com/chat/completions").respond(
        json={
            "id": "request-1",
            "model": "deepseek-flash",
            "choices": [{"message": {"content": '{"body":"answer"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }
    )
    async with httpx.AsyncClient() as http:
        result = await DeepSeekGeneration(
            SecretStr("unit-secret"), "https://api.deepseek.com", "deepseek-flash", http
        ).generate((Message(role="user", content="Return JSON"),), 1024)
    body = json.loads(route.calls[0].request.content)
    assert body["thinking"] == {"type": "disabled"} and body["max_tokens"] == 1024
    assert body["response_format"] == {"type": "json_object"}
    assert result.request_id == "request-1" and result.usage["prompt_tokens"] == 5
    assert result.model_id == "deepseek-flash"


async def test_authentication_failure_is_secret_safe_and_no_fallback(respx_mock):
    route = respx_mock.post("https://api.deepseek.com/chat/completions").respond(
        status_code=401, json={"error": {"message": "unit-secret"}}
    )
    provider = DeepSeekGeneration(
        SecretStr("unit-secret"), "https://api.deepseek.com", "deepseek-flash"
    )
    with pytest.raises(DomainError) as error:
        await provider.generate((Message(role="user", content="Return JSON"),), 16)
    assert error.value.code == "GENERATION_AUTH_FAILED" and "unit-secret" not in str(error.value)
    assert route.call_count == 1
    with pytest.raises(DomainError):
        await provider.generate((Message(role="user", content="test"),), 1025)
