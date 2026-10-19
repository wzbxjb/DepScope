import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from depscope.generation.budget import BudgetLedger, BudgetPolicy
from depscope.generation.models import Message
from depscope.runtime.errors import DomainError


@pytest.fixture
def ledger(driver):
    instance = BudgetLedger(driver)
    instance.test_run = "test-budget:" + uuid.uuid4().hex
    yield instance
    with driver.session() as session:
        session.run(
            "MATCH (b:GenerationBudget {id:$id}) OPTIONAL MATCH (b)-[:HAS_CALL]->(c) DETACH DELETE c,b",
            id=instance.test_run,
        ).consume()


def test_timeout_retains_reservation_and_retry_consumes_limit(ledger):
    run = ledger.test_run
    ledger.open_run(run, BudgetPolicy(currency="USD", max_amount=Decimal("0.10"), max_calls=1))
    first = ledger.reserve(run, Decimal("0.03"))
    ledger.settle(first.id, None)
    assert ledger.summary(run).reserved == Decimal("0.03")
    assert ledger.summary(run).estimated_spent is None
    with pytest.raises(DomainError, match="CALL_LIMIT"):
        ledger.reserve(run, Decimal("0.03"))


def test_atomic_concurrent_reservations_and_restart_do_not_reset(ledger):
    run = ledger.test_run
    policy = BudgetPolicy(currency="USD", max_amount=Decimal("0.10"), max_calls=10)
    ledger.open_run(run, policy)

    def attempt(n):
        try:
            return ledger.reserve(run, Decimal("0.03")).id
        except DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count("AMOUNT_LIMIT") == 5
    restarted = BudgetLedger(ledger.driver)
    restarted.open_run(run, policy)
    assert (
        restarted.summary(run).reserved == Decimal("0.09")
        and restarted.summary(run).call_count == 3
    )
    with pytest.raises(DomainError):
        restarted.open_run(run, policy.model_copy(update={"max_calls": 99}))


def test_settlement_is_idempotent_and_preserves_usage_request(ledger):
    run = ledger.test_run
    ledger.open_run(run, BudgetPolicy(currency="USD", max_amount=Decimal("1"), max_calls=3))
    reservation = ledger.reserve(run, Decimal("0.03"))
    usage = {"prompt_tokens": 100, "completion_tokens": 10}
    ledger.settle(reservation.id, usage, model_id="deepseek-flash", request_id="request-1")
    ledger.settle(reservation.id, usage, model_id="deepseek-flash", request_id="request-1")
    summary = ledger.summary(run)
    assert summary.reserved == 0 and summary.estimated_spent == Decimal("0.000042")
    with pytest.raises(DomainError):
        ledger.settle(reservation.id, {"prompt_tokens": 999, "completion_tokens": 10})
    assert ledger.calls(run)[0]["request_id"] == "request-1"


def test_explicit_limit_increase_preserves_calls_and_rejects_reset(ledger):
    run = ledger.test_run
    ledger.open_run(run, BudgetPolicy(currency="USD", max_amount=Decimal("0.10"), max_calls=1))
    ledger.reserve(run, Decimal("0.03"))
    ledger.increase_limits(run, Decimal("0.20"), 2)
    assert ledger.summary(run).call_count == 1 and ledger.summary(run).reserved == Decimal("0.03")
    assert ledger.summary(run).remaining_calls == 1
    with pytest.raises(DomainError):
        ledger.increase_limits(run, Decimal("0.10"), 1)


async def test_cancelled_generation_retains_pending_charge(ledger):
    from depscope.generation.budget import BudgetedGeneration

    class Cancelled:
        async def generate(self, *args):
            raise asyncio.CancelledError

    run = ledger.test_run
    ledger.open_run(run, BudgetPolicy(currency="USD", max_amount=Decimal("1"), max_calls=2))
    with pytest.raises(asyncio.CancelledError):
        await BudgetedGeneration(Cancelled(), ledger).generate(
            run, (Message(role="user", content="Return JSON"),), 16
        )
    assert ledger.summary(run).call_count == 1 and ledger.summary(run).reserved > 0
