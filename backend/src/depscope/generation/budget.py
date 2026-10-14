import asyncio
from decimal import Decimal

from pydantic import Field

from depscope.generation.pricing import official_price, reservation_cost
from depscope.ingest.models import Contract


class BudgetPolicy(Contract):
    currency: str
    max_amount: Decimal = Field(ge=0, allow_inf_nan=False)
    max_calls: int = Field(ge=0)


class Reservation(Contract):
    id: str
    run_id: str
    amount: Decimal
    status: str


class BudgetSummary(Contract):
    reserved: Decimal
    estimated_spent: Decimal | None
    known_estimated_spent: Decimal
    call_count: int
    remaining: Decimal
    remaining_calls: int
    unknown_usage_calls: int
    currency: str
    price_basis: str | None
    max_amount: Decimal
    max_calls: int


class BudgetLedger:
    def __init__(self, driver, price=...):
        from depscope.graph.call_ledger import CallLedger

        self.driver = driver
        self.price = official_price() if price is ... else price
        self.store = CallLedger(driver, self.price)

    def open_run(self, run_id, policy):
        return self.store.open_run(run_id, policy)

    def reserve(self, run_id, amount):
        return self.store.reserve(run_id, amount)

    def settle(self, id, usage, model_id=None, request_id=None):
        return self.store.settle(id, usage, model_id, request_id)

    def summary(self, run_id):
        return self.store.summary(run_id)

    def increase_limits(self, run_id, max_amount, max_calls):
        return self.store.increase_limits(run_id, max_amount, max_calls)

    def price_for(self, run_id):
        return self.store.price_for(run_id)

    def calls(self, run_id):
        return self.store.calls(run_id)


class BudgetedGeneration:
    def __init__(self, provider, ledger):
        self.provider, self.ledger = provider, ledger

    async def generate(self, run_id, messages, max_output=1024):
        if self.ledger.price_for(run_id) != self.ledger.price:
            from depscope.runtime.errors import DomainError

            raise DomainError(
                "PRICING_CHANGED", "Use a new recorded budget when the pricing profile changes"
            )
        amount = reservation_cost(messages, max_output, self.ledger.price)
        reservation = await asyncio.to_thread(self.ledger.reserve, run_id, amount)
        try:
            result = await self.provider.generate(messages, max_output)
        except BaseException:
            # Unknown/possibly charged calls are never released to zero, including cancellation.
            await asyncio.shield(asyncio.to_thread(self.ledger.settle, reservation.id, None))
            raise
        await asyncio.to_thread(
            self.ledger.settle, reservation.id, result.usage, result.model_id, result.request_id
        )
        return result
