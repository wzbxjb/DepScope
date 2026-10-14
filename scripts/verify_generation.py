"""One authorized, capped real DeepSeek call plus the prior actual probe receipt."""

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from depscope.api.services import build_services
from depscope.generation.budget import BudgetLedger, BudgetPolicy, BudgetedGeneration
from depscope.generation.models import Message
from depscope.generation.deepseek import DeepSeekGeneration
from depscope.generation.pricing import official_price
from depscope.runtime.config import load_settings
from depscope.runtime.pagination import now


async def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/verification/generation-contract.json"
    if output.exists():
        print("Actual generation contract already recorded; no repeated paid probe")
        return
    settings = load_settings()
    services = build_services(settings)
    try:
        price = official_price(settings.deepseek_base_url, settings.generation_model)
        ledger = BudgetLedger(services.driver, price)
        legacy = json.loads(
            (root / "artifacts/verification/deepseek-probe.json").read_text()
        )
        legacy_run = "legacy-probe-20261013"
        ledger.open_run(
            legacy_run,
            BudgetPolicy(currency="USD", max_amount=Decimal("0.001"), max_calls=1),
        )
        calls = ledger.calls(legacy_run)
        if not calls:
            reservation = ledger.reserve(legacy_run, Decimal("0.001"))
            ledger.settle(
                reservation.id, legacy["usage"], legacy["model"], legacy["request_id"]
            )
        run = "generation-contract-20261014"
        ledger.open_run(
            run, BudgetPolicy(currency="USD", max_amount=Decimal("0.05"), max_calls=1)
        )
        provider = DeepSeekGeneration(
            settings.deepseek_api_key,
            settings.deepseek_base_url,
            settings.generation_model,
        )
        result = await BudgetedGeneration(provider, ledger).generate(
            run,
            (
                Message(
                    role="user", content='Return only this JSON object: {"ok":true}'
                ),
            ),
            64,
        )
        assert json.loads(result.text) == {"ok": True}
        artifact = {
            "observed_at": now(),
            "run_id": run,
            "result": result.model_dump(mode="json"),
            "budget": ledger.summary(run).model_dump(mode="json"),
            "calls": ledger.calls(run),
            "price": price.model_dump(mode="json") if price else None,
            "legacy_probe_budget": ledger.summary(legacy_run).model_dump(mode="json"),
            "note": "Real usage with a peak-rate upper-bound estimate; not the supplier invoice. The previous actual probe is recorded separately without another API call.",
        }
        output.write_text(json.dumps(artifact, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "model_id": result.model_id,
                    "request_id": result.request_id,
                    "usage": result.usage,
                    "budget": artifact["budget"],
                }
            )
        )
    finally:
        services.close()


if __name__ == "__main__":
    asyncio.run(main())
