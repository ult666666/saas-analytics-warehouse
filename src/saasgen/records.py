"""Row types of the eight raw tables.

Field order is the CSV column order. Money is stored in integer cents, as most
billing systems do, so the raw files contain no floating-point values.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import NamedTuple


class Plan(NamedTuple):
    plan_price_id: str
    plan_code: str
    plan_name: str
    plan_tier: int
    billing_interval: str  # "month" or "year"
    unit_amount_cents: int  # price per seat per billing interval
    currency: str
    valid_from: date
    valid_to: date | None  # exclusive; None for the current price


class MarketingSpend(NamedTuple):
    spend_date: date
    channel: str
    spend_cents: int


class Signup(NamedTuple):
    signup_id: str
    created_at: datetime
    utm_source: str | None
    country_code: str
    company_size: str


class Trial(NamedTuple):
    trial_id: str
    signup_id: str
    started_at: datetime
    ends_at: datetime


class Customer(NamedTuple):
    customer_id: str
    signup_id: str
    created_at: datetime


class SubscriptionEvent(NamedTuple):
    event_id: str
    customer_id: str
    event_type: str  # new, upgrade, downgrade, cancel, reactivate
    occurred_at: datetime  # when the change was requested or recorded
    effective_date: date  # when the change takes effect
    plan_price_id: str | None  # None for cancel events
    seats: int | None  # None for cancel events
    cancel_reason: str | None  # voluntary or payment_failed; cancel events only


class Invoice(NamedTuple):
    invoice_id: str
    customer_id: str
    invoice_date: date
    period_start: date
    period_end: date  # exclusive
    plan_price_id: str
    seats: int
    amount_due_cents: int
    status: str  # paid, open (still in dunning at the end of the data) or uncollectible


class Payment(NamedTuple):
    payment_id: str
    invoice_id: str
    attempt_number: int
    attempted_at: datetime
    amount_cents: int
    status: str  # succeeded or failed
    failure_code: str | None
    received_at: datetime  # when the payment webhook reached the warehouse
