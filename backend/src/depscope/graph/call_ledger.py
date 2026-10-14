import json
import uuid
from decimal import Decimal

from depscope.generation.pricing import PriceProfile, estimate_cost
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now


class CallLedger:
    def __init__(self, driver, price):
        self.driver, self.price = driver, price

    def open_run(self, run_id, policy):
        if self.price is not None and policy.currency != self.price.currency:
            raise DomainError(
                "CURRENCY_MISMATCH", "Budget currency differs from configured pricing"
            )

        def persist(tx):
            row = tx.run(
                "MERGE (b:GenerationBudget {id:$id}) ON CREATE SET b.policy=$policy,b.price=$price,b.reserved='0',b.spent='0',b.calls=0,b.lock_version=0 RETURN b.policy AS policy,b.price AS price",
                id=run_id,
                policy=policy.model_dump_json(),
                price=self.price.model_dump_json() if self.price else None,
            ).single()
            if row["policy"] != policy.model_dump_json() or row["price"] != (
                self.price.model_dump_json() if self.price else None
            ):
                raise DomainError(
                    "BUDGET_IMMUTABLE", "An existing budget cannot be reset or silently changed"
                )

        with self.driver.session() as session:
            session.run(
                "CREATE CONSTRAINT generation_budget_identity IF NOT EXISTS FOR (b:GenerationBudget) REQUIRE b.id IS UNIQUE"
            ).consume()
            session.run(
                "CREATE CONSTRAINT generation_call_identity IF NOT EXISTS FOR (c:GenerationCall) REQUIRE c.id IS UNIQUE"
            ).consume()
            session.execute_write(persist)

    def reserve(self, run_id, amount):
        from depscope.generation.budget import BudgetPolicy, Reservation

        if not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0:
            raise DomainError(
                "INVALID_RESERVATION", "Reservation must be a finite non-negative Decimal"
            )
        id = str(uuid.uuid4())

        def persist(tx):
            # Dependent property update acquires the node write lock before reading counters.
            row = tx.run(
                "MATCH (b:GenerationBudget {id:$id}) SET b.lock_version=b.lock_version+1 RETURN b.policy AS policy,b.reserved AS reserved,b.spent AS spent,b.calls AS calls",
                id=run_id,
            ).single()
            if not row:
                raise DomainError(
                    "BUDGET_NOT_FOUND", "Open an explicit capped budget before generation"
                )
            policy = BudgetPolicy.model_validate_json(row["policy"])
            if row["calls"] >= policy.max_calls:
                raise DomainError("CALL_LIMIT", "Generation call limit reached")
            if Decimal(row["reserved"]) + Decimal(row["spent"]) + amount > policy.max_amount:
                raise DomainError(
                    "AMOUNT_LIMIT", "Generation reservation would exceed the amount limit"
                )
            tx.run(
                "MATCH (b:GenerationBudget {id:$run}) SET b.reserved=$reserved,b.calls=b.calls+1 CREATE (c:GenerationCall {id:$id,run_id:$run,reservation:$amount,status:'pending',observed_at:$time}) CREATE (b)-[:HAS_CALL]->(c)",
                run=run_id,
                id=id,
                amount=str(amount),
                reserved=str(Decimal(row["reserved"]) + amount),
                time=now(),
            ).consume()
            return Reservation(id=id, run_id=run_id, amount=amount, status="pending")

        with self.driver.session() as session:
            return session.execute_write(persist)

    def settle(self, id, usage, model_id=None, request_id=None):
        def persist(tx):
            row = tx.run(
                "MATCH (b:GenerationBudget)-[:HAS_CALL]->(c:GenerationCall {id:$id}) SET b.lock_version=b.lock_version+1 RETURN b.id AS run,b.price AS price,b.reserved AS reserved,b.spent AS spent,c.reservation AS amount,c.status AS status,c.usage AS usage,c.model_id AS model,c.request_id AS request",
                id=id,
            ).single()
            if not row:
                raise DomainError("RESERVATION_NOT_FOUND", "Generation reservation is unavailable")
            price = PriceProfile.model_validate_json(row["price"]) if row["price"] else None
            estimated = estimate_cost(usage, price)
            serialized = json.dumps(usage, sort_keys=True) if isinstance(usage, dict) else None
            if row["status"] == "settled":
                if (row["usage"], row["model"], row["request"]) != (
                    serialized,
                    model_id,
                    request_id,
                ):
                    raise DomainError("CALL_IMMUTABLE", "Settled usage cannot be modified")
                return
            if estimated is None:
                tx.run(
                    "MATCH (c:GenerationCall {id:$id}) SET c.status='usage_unknown',c.usage=$usage,c.model_id=$model,c.request_id=$request",
                    id=id,
                    usage=serialized,
                    model=model_id,
                    request=request_id,
                ).consume()
                return
            tx.run(
                "MATCH (b:GenerationBudget {id:$run})-[:HAS_CALL]->(c:GenerationCall {id:$id}) SET b.reserved=$reserved,b.spent=$spent,c.status='settled',c.estimated_cost=$cost,c.usage=$usage,c.model_id=$model,c.request_id=$request,c.settled_at=$time,c.over_reservation=$over",
                run=row["run"],
                id=id,
                reserved=str(Decimal(row["reserved"]) - Decimal(row["amount"])),
                spent=str(Decimal(row["spent"]) + estimated),
                cost=str(estimated),
                usage=serialized,
                model=model_id,
                request=request_id,
                time=now(),
                over=estimated > Decimal(row["amount"]),
            ).consume()

        with self.driver.session() as session:
            session.execute_write(persist)

    def summary(self, run_id):
        from depscope.generation.budget import BudgetPolicy, BudgetSummary

        with self.driver.session() as session:
            row = session.run(
                "MATCH (b:GenerationBudget {id:$id}) OPTIONAL MATCH (b)-[:HAS_CALL]->(c:GenerationCall) RETURN b.policy AS policy,b.price AS price,b.reserved AS reserved,b.spent AS spent,b.calls AS calls,count(CASE WHEN c.status<>'settled' THEN 1 END) AS unknown",
                id=run_id,
            ).single()
        if not row:
            raise DomainError("BUDGET_NOT_FOUND", "Generation budget is unavailable")
        policy = BudgetPolicy.model_validate_json(row["policy"])
        price = PriceProfile.model_validate_json(row["price"]) if row["price"] else None
        reserved, spent = Decimal(row["reserved"]), Decimal(row["spent"])
        return BudgetSummary(
            reserved=reserved,
            estimated_spent=None if row["unknown"] or price is None else spent,
            known_estimated_spent=spent,
            call_count=row["calls"],
            remaining=max(Decimal(0), policy.max_amount - reserved - spent),
            remaining_calls=max(0, policy.max_calls - row["calls"]),
            unknown_usage_calls=row["unknown"],
            currency=policy.currency,
            price_basis=price.basis if price else None,
        )

    def calls(self, run_id):
        with self.driver.session() as session:
            return tuple(
                row.data()
                for row in session.run(
                    "MATCH (b:GenerationBudget {id:$id})-[:HAS_CALL]->(c:GenerationCall) RETURN c.id AS id,c.status AS status,c.reservation AS reservation,c.estimated_cost AS estimated_cost,c.usage AS usage,c.model_id AS model_id,c.request_id AS request_id,c.observed_at AS observed_at,c.over_reservation AS over_reservation ORDER BY observed_at,id",
                    id=run_id,
                )
            )
