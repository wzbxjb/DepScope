from decimal import Decimal

from depscope.ingest.models import Contract
from depscope.runtime.errors import DomainError


class PriceProfile(Contract):
    provider: str
    model: str
    currency: str
    observed_at: str
    rates: dict[str, Decimal]
    source_uri: str
    basis: str = "Peak-rate upper-bound estimate; not a supplier invoice"


def official_price(base_url="https://api.deepseek.com", model="deepseek-flash"):
    if (
        base_url.rstrip("/") not in ("https://api.deepseek.com", "https://api.deepseek.com/v1")
        or model != "deepseek-flash"
    ):
        return None
    return PriceProfile(
        provider="DeepSeek official",
        model=model,
        currency="USD",
        observed_at="2026-10-14",
        rates={
            "input_hit": Decimal("0.006"),
            "input_miss": Decimal("0.30"),
            "output": Decimal("1.20"),
        },
        source_uri="https://api-docs.deepseek.com/quick_start/pricing/",
    )


def _tokens(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def estimate_cost(usage, price):
    if (
        price is None
        or not isinstance(usage, dict)
        or not _tokens(usage.get("prompt_tokens"))
        or not _tokens(usage.get("completion_tokens"))
    ):
        return None
    prompt, output = usage["prompt_tokens"], usage["completion_tokens"]
    hit, miss = usage.get("prompt_cache_hit_tokens"), usage.get("prompt_cache_miss_tokens")
    if _tokens(hit) and _tokens(miss) and hit + miss == prompt:
        input_cost = (
            Decimal(hit) * price.rates["input_hit"] + Decimal(miss) * price.rates["input_miss"]
        )
    else:
        input_cost = Decimal(prompt) * price.rates["input_miss"]
    return (input_cost + Decimal(output) * price.rates["output"]) / Decimal(1000000)


def reservation_cost(messages, max_output, price):
    if price is None:
        raise DomainError(
            "PRICE_UNAVAILABLE",
            "Configure verified pricing before a monetary-capped generation call",
        )
    # UTF-8 bytes bound byte-level tokens; extra overhead covers role/format markers.
    prompt = sum(len(m.content.encode("utf-8")) + 256 for m in messages) + 1024
    return (
        Decimal(prompt) * price.rates["input_miss"] + Decimal(max_output) * price.rates["output"]
    ) / Decimal(1000000)
