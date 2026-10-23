"""Subscription lifecycle and billing: subscription events, invoices and payments.

Billing rules of the fictional company (documented in docs/METRICS.md):

* A subscription renews on the anniversary of its start date, monthly or yearly.
* Plan and seat changes are requested during a billing period and take effect at
  the next renewal, so invoices never need proration.
* Existing subscriptions keep their price after a list-price change until they
  change plan or reactivate (grandfathering); seat changes keep the price.
* Voluntary cancellations take effect at the end of the paid period.
* A failed renewal charge is retried 3, 7 and 14 days after the invoice date. If
  every retry fails the invoice becomes uncollectible and the subscription is
  cancelled on the day of the last retry (involuntary churn).
* The first invoice of a new or reactivated subscription is always paid: a
  checkout whose card is declined never becomes a subscription.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np

from saasgen.config import (
    ANNUAL_CHURN_FACTOR,
    CHURN_MULTIPLIER_BY_SIZE,
    DUPLICATE_PAYMENT_RATE,
    EARLY_TENURE_CHURN_MULTIPLIER,
    EARLY_TENURE_RENEWALS,
    EXPANSION_RAMP_MONTHS,
    FAILURE_CODES,
    PAYMENT_FAILURE_RATE,
    PLAN_MIX_BY_SIZE,
    PLANS,
    PLANS_BY_TIER,
    REACTIVATE_SAME_PLAN_SHARE,
    REACTIVATION_DELAY_DAYS,
    REACTIVATION_PROBABILITY,
    REACTIVATION_SEAT_FACTOR,
    RETRY_DAYS,
    RETRY_SUCCESS_RATE,
    SEAT_DECREASE_FRACTION,
    SEAT_DECREASE_RATE,
    SEAT_INCREASE_FRACTION,
    SEAT_INCREASE_RATE,
    SEATS_BY_SIZE,
    GeneratorConfig,
    PlanParams,
)
from saasgen.dates import add_months
from saasgen.pricing import PriceBook
from saasgen.records import Customer, Invoice, Payment, Plan, SubscriptionEvent
from saasgen.sampling import (
    chance,
    compound_probability,
    midnight,
    random_time_between,
    random_time_on,
    weighted_choice,
)

FAILURE_CODE_NAMES = tuple(code for code, _ in FAILURE_CODES)
FAILURE_CODE_WEIGHTS = tuple(weight for _, weight in FAILURE_CODES)


@dataclass
class SubscriptionState:
    """What a customer is subscribed to right now."""

    plan: PlanParams
    billing_interval: str
    seats: int
    price: Plan  # the price-book row this subscription is billed at

    @property
    def months_per_period(self) -> int:
        return 1 if self.billing_interval == "month" else 12


class BillingSimulator:
    """Simulates each customer's subscription history and appends the resulting rows."""

    def __init__(self, config: GeneratorConfig, rng: np.random.Generator, prices: PriceBook):
        self.config = config
        self.rng = rng
        self.prices = prices
        self.events: list[SubscriptionEvent] = []
        self.invoices: list[Invoice] = []
        self.payments: list[Payment] = []

    # --- public API ------------------------------------------------------------------------------

    def simulate(self, customer: Customer, company_size: str) -> None:
        """Simulate one customer from conversion to the last simulated day."""
        started_at = customer.created_at
        state = self._initial_state(company_size, started_at.date())
        self._record_event(customer.customer_id, "new", started_at, started_at.date(), state)
        while True:
            ended = self._run_subscription(customer.customer_id, company_size, started_at, state)
            if ended is None:
                return  # still subscribed when the data ends
            reason, ended_on = ended
            restarted_at = self._reactivation_time(reason, ended_on)
            if restarted_at is None:
                return
            state = self._reactivated_state(state, company_size, restarted_at.date())
            self._record_event(
                customer.customer_id, "reactivate", restarted_at, restarted_at.date(), state
            )
            started_at = restarted_at

    # --- one subscription, from start to cancellation --------------------------------------------

    def _run_subscription(
        self,
        customer_id: str,
        company_size: str,
        started_at: datetime,
        state: SubscriptionState,
    ) -> tuple[str, date] | None:
        """Bill period after period until the subscription is cancelled or the data ends.

        Returns ``(cancel reason, cancel date)``, or None if still active at the end.
        """
        anchor = started_at.date()
        renewals = 0
        while True:
            period_start = add_months(anchor, state.months_per_period * renewals)
            period_end = add_months(anchor, state.months_per_period * (renewals + 1))
            opened_at = started_at if renewals == 0 else midnight(period_start)
            charged_at = started_at if renewals == 0 else random_time_on(self.rng, period_start)
            failed_at = self._bill_period(
                customer_id, state, period_start, period_end, charged_at, renewals == 0
            )
            if failed_at is not None:
                self._record_cancel(customer_id, failed_at, failed_at.date(), "payment_failed")
                return "payment_failed", failed_at.date()
            if period_end > self.config.end_date:
                return None  # the next renewal is after the data ends

            # Decisions are requested during this period and take effect at the renewal date.
            if chance(self.rng, self._churn_probability(state, company_size, renewals)):
                requested_at = random_time_between(self.rng, opened_at, midnight(period_end))
                self._record_cancel(customer_id, requested_at, period_end, "voluntary")
                return "voluntary", period_end
            tenure_months = state.months_per_period * (renewals + 1)
            self._maybe_change_plan(customer_id, state, opened_at, period_end, tenure_months)
            renewals += 1

    def _churn_probability(
        self, state: SubscriptionState, company_size: str, renewals: int
    ) -> float:
        monthly = state.plan.monthly_churn * CHURN_MULTIPLIER_BY_SIZE[company_size]
        if state.billing_interval == "year":
            return compound_probability(monthly * ANNUAL_CHURN_FACTOR, 12)
        if renewals < EARLY_TENURE_RENEWALS:
            return monthly * EARLY_TENURE_CHURN_MULTIPLIER
        return monthly

    def _maybe_change_plan(
        self,
        customer_id: str,
        state: SubscriptionState,
        opened_at: datetime,
        period_end: date,
        tenure_months: int,
    ) -> None:
        """At most one plan or seat change per renewal; expansion grows with tenure."""
        months = state.months_per_period
        ramp = 0.6 + 0.8 * min(tenure_months, EXPANSION_RAMP_MONTHS) / EXPANSION_RAMP_MONTHS
        higher_plan = PLANS_BY_TIER.get(state.plan.tier + 1)
        lower_plan = PLANS_BY_TIER.get(state.plan.tier - 1)
        p_upgrade = (
            compound_probability(state.plan.upgrade_rate * ramp, months) if higher_plan else 0
        )
        p_add_seats = compound_probability(SEAT_INCREASE_RATE * ramp, months)
        p_downgrade = compound_probability(state.plan.downgrade_rate, months) if lower_plan else 0
        p_remove_seats = compound_probability(SEAT_DECREASE_RATE, months) if state.seats > 1 else 0

        roll = self.rng.random()
        if higher_plan is not None and roll < p_upgrade:
            event_type = "upgrade"
            self._switch_plan(state, higher_plan, period_end)
        elif roll < p_upgrade + p_add_seats:
            event_type = "upgrade"
            state.seats += max(1, round(state.seats * self.rng.uniform(*SEAT_INCREASE_FRACTION)))
        elif lower_plan is not None and roll < p_upgrade + p_add_seats + p_downgrade:
            event_type = "downgrade"
            self._switch_plan(state, lower_plan, period_end)
        elif roll < p_upgrade + p_add_seats + p_downgrade + p_remove_seats:
            event_type = "downgrade"
            removed = max(1, round(state.seats * self.rng.uniform(*SEAT_DECREASE_FRACTION)))
            state.seats = max(1, state.seats - removed)
        else:
            return
        requested_at = random_time_between(self.rng, opened_at, midnight(period_end))
        self._record_event(customer_id, event_type, requested_at, period_end, state)

    def _switch_plan(self, state: SubscriptionState, plan: PlanParams, effective: date) -> None:
        """A plan change moves the subscription onto the list price in effect at that date."""
        state.plan = plan
        state.price = self.prices.price_on(plan.code, state.billing_interval, effective)

    # --- billing ---------------------------------------------------------------------------------

    def _bill_period(
        self,
        customer_id: str,
        state: SubscriptionState,
        period_start: date,
        period_end: date,
        charged_at: datetime,
        is_first_invoice: bool,
    ) -> datetime | None:
        """Invoice one period and attempt payment.

        Returns the time of the final failed retry when the invoice becomes
        uncollectible, otherwise None.
        """
        invoice_id = f"inv_{len(self.invoices) + 1:07d}"
        amount_cents = state.price.unit_amount_cents * state.seats
        attempt_times = [charged_at] + [
            random_time_on(self.rng, period_start + timedelta(days=days)) for days in RETRY_DAYS
        ]
        status = "open"
        for attempt_number, attempted_at in enumerate(attempt_times, start=1):
            if attempted_at.date() > self.config.end_date:
                break  # remaining retries fall after the data ends: the invoice stays open
            if is_first_invoice:
                succeeded = True
            elif attempt_number == 1:
                succeeded = not chance(self.rng, PAYMENT_FAILURE_RATE)
            else:
                succeeded = chance(self.rng, RETRY_SUCCESS_RATE)
            self._record_payment(invoice_id, attempt_number, attempted_at, amount_cents, succeeded)
            if succeeded:
                status = "paid"
                break
            if attempt_number == len(attempt_times):
                status = "uncollectible"

        self.invoices.append(
            Invoice(
                invoice_id=invoice_id,
                customer_id=customer_id,
                invoice_date=period_start,
                period_start=period_start,
                period_end=period_end,
                plan_price_id=state.price.plan_price_id,
                seats=state.seats,
                amount_due_cents=amount_cents,
                status=status,
            )
        )
        return attempt_times[-1] if status == "uncollectible" else None

    def _record_payment(
        self,
        invoice_id: str,
        attempt_number: int,
        attempted_at: datetime,
        amount_cents: int,
        succeeded: bool,
    ) -> None:
        failure_code = (
            None
            if succeeded
            else weighted_choice(self.rng, FAILURE_CODE_NAMES, FAILURE_CODE_WEIGHTS)
        )
        payment = Payment(
            payment_id=f"pay_{len(self.payments) + 1:07d}",
            invoice_id=invoice_id,
            attempt_number=attempt_number,
            attempted_at=attempted_at,
            amount_cents=amount_cents,
            status="succeeded" if succeeded else "failed",
            failure_code=failure_code,
            received_at=attempted_at + timedelta(seconds=int(self.rng.integers(1, 300))),
        )
        self.payments.append(payment)
        if chance(self.rng, DUPLICATE_PAYMENT_RATE):
            # At-least-once webhook delivery: the same payment arrives a second time.
            redelivered_at = payment.received_at + timedelta(minutes=int(self.rng.integers(1, 60)))
            self.payments.append(payment._replace(received_at=redelivered_at))

    # --- events ----------------------------------------------------------------------------------

    def _record_event(
        self,
        customer_id: str,
        event_type: str,
        occurred_at: datetime,
        effective_date: date,
        state: SubscriptionState,
    ) -> None:
        self.events.append(
            SubscriptionEvent(
                event_id=f"evt_{len(self.events) + 1:07d}",
                customer_id=customer_id,
                event_type=event_type,
                occurred_at=occurred_at,
                effective_date=effective_date,
                plan_price_id=state.price.plan_price_id,
                seats=state.seats,
                cancel_reason=None,
            )
        )

    def _record_cancel(
        self, customer_id: str, occurred_at: datetime, effective_date: date, reason: str
    ) -> None:
        self.events.append(
            SubscriptionEvent(
                event_id=f"evt_{len(self.events) + 1:07d}",
                customer_id=customer_id,
                event_type="cancel",
                occurred_at=occurred_at,
                effective_date=effective_date,
                plan_price_id=None,
                seats=None,
                cancel_reason=reason,
            )
        )

    # --- choosing plans --------------------------------------------------------------------------

    def _initial_state(self, company_size: str, day: date) -> SubscriptionState:
        plan = weighted_choice(self.rng, PLANS, PLAN_MIX_BY_SIZE[company_size])
        low, high = SEATS_BY_SIZE[company_size]
        seats = int(self.rng.integers(low, high + 1))
        return self._new_state(plan, seats, day)

    def _reactivated_state(
        self, previous: SubscriptionState, company_size: str, day: date
    ) -> SubscriptionState:
        if chance(self.rng, REACTIVATE_SAME_PLAN_SHARE):
            plan = previous.plan
        else:
            plan = weighted_choice(self.rng, PLANS, PLAN_MIX_BY_SIZE[company_size])
        seats = max(1, round(previous.seats * self.rng.uniform(*REACTIVATION_SEAT_FACTOR)))
        return self._new_state(plan, seats, day)

    def _new_state(self, plan: PlanParams, seats: int, day: date) -> SubscriptionState:
        billing_interval = "year" if chance(self.rng, plan.annual_share) else "month"
        price = self.prices.price_on(plan.code, billing_interval, day)
        return SubscriptionState(plan, billing_interval, seats, price)

    def _reactivation_time(self, reason: str, ended_on: date) -> datetime | None:
        if not chance(self.rng, REACTIVATION_PROBABILITY[reason]):
            return None
        low, high = REACTIVATION_DELAY_DAYS
        day = ended_on + timedelta(days=int(self.rng.integers(low, high + 1)))
        if day > self.config.end_date:
            return None
        return random_time_on(self.rng, day)
