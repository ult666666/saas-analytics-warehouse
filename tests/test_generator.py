"""Tests for the generated dataset: determinism, integrity, ordering and calibration."""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

import pytest

from saasgen.config import (
    CHANNELS,
    DUPLICATE_PAYMENT_RATE,
    MESSY_UTM_RATE,
    PAYMENT_FAILURE_RATE,
    PLANS,
    RETRY_DAYS,
    TRIAL_DAYS,
    GeneratorConfig,
)
from saasgen.generator import Dataset, generate
from saasgen.records import SubscriptionEvent
from saasgen.writer import write_dataset

SOURCE_TO_CHANNEL = {
    source: channel.name for channel in CHANNELS for source, _ in channel.utm_sources
}


def signup_channels(dataset: Dataset) -> dict[str, str]:
    """Channel of every signup, using the same normalisation as the dbt staging model."""
    channels = {}
    for signup in dataset.signups:
        source = signup.utm_source.strip().lower() if signup.utm_source else None
        channels[signup.signup_id] = SOURCE_TO_CHANNEL[source]
    return channels


def events_by_customer(dataset: Dataset) -> dict[str, list[SubscriptionEvent]]:
    grouped: dict[str, list[SubscriptionEvent]] = defaultdict(list)
    for event in dataset.subscription_events:
        grouped[event.customer_id].append(event)
    for events in grouped.values():
        events.sort(key=lambda event: (event.effective_date, event.occurred_at, event.event_id))
    return grouped


def file_digests(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.glob("*.csv"))
    }


# --- determinism ---------------------------------------------------------------------------------


def test_same_config_gives_byte_identical_files(
    small_config: GeneratorConfig, tmp_path: Path
) -> None:
    write_dataset(generate(small_config), tmp_path / "first")
    write_dataset(generate(small_config), tmp_path / "second")
    first, second = file_digests(tmp_path / "first"), file_digests(tmp_path / "second")
    assert len(first) == 8
    assert first == second


def test_different_seed_gives_different_data(small_config: GeneratorConfig) -> None:
    other = generate(dataclasses.replace(small_config, seed=small_config.seed + 1))
    assert other.signups != generate(small_config).signups


def test_scale_controls_volume(small_config: GeneratorConfig) -> None:
    bigger = generate(dataclasses.replace(small_config, scale=small_config.scale * 3))
    assert len(bigger.signups) > 2 * len(generate(small_config).signups)


# --- referential integrity -----------------------------------------------------------------------


def test_primary_keys_are_unique(default_dataset: Dataset) -> None:
    keys = {
        "plans": [row.plan_price_id for row in default_dataset.plans],
        "signups": [row.signup_id for row in default_dataset.signups],
        "trials": [row.trial_id for row in default_dataset.trials],
        "customers": [row.customer_id for row in default_dataset.customers],
        "subscription_events": [row.event_id for row in default_dataset.subscription_events],
        "invoices": [row.invoice_id for row in default_dataset.invoices],
        "spend": [(row.spend_date, row.channel) for row in default_dataset.marketing_spend],
    }
    for table, values in keys.items():
        assert len(values) == len(set(values)), table


def test_foreign_keys_resolve(default_dataset: Dataset) -> None:
    signup_ids = {row.signup_id for row in default_dataset.signups}
    trial_signups = [row.signup_id for row in default_dataset.trials]
    customer_ids = {row.customer_id for row in default_dataset.customers}
    price_ids = {row.plan_price_id for row in default_dataset.plans}
    invoice_ids = {row.invoice_id for row in default_dataset.invoices}

    assert set(trial_signups) <= signup_ids
    assert len(trial_signups) == len(set(trial_signups)), "at most one trial per signup"
    assert {row.signup_id for row in default_dataset.customers} <= set(trial_signups)
    assert len({row.signup_id for row in default_dataset.customers}) == len(customer_ids)
    for event in default_dataset.subscription_events:
        assert event.customer_id in customer_ids
        assert (event.plan_price_id is None) == (event.event_type == "cancel")
        assert event.plan_price_id is None or event.plan_price_id in price_ids
    for invoice in default_dataset.invoices:
        assert invoice.customer_id in customer_ids
        assert invoice.plan_price_id in price_ids
    assert {payment.invoice_id for payment in default_dataset.payments} <= invoice_ids
    assert {event.customer_id for event in default_dataset.subscription_events} == customer_ids


# --- valid date ordering -------------------------------------------------------------------------


def test_funnel_timestamps_are_ordered(default_dataset: Dataset) -> None:
    config = default_dataset.config
    signups = {row.signup_id: row for row in default_dataset.signups}
    trials = {row.signup_id: row for row in default_dataset.trials}
    for signup in default_dataset.signups:
        assert config.start_date <= signup.created_at.date() <= config.end_date
    for trial in default_dataset.trials:
        assert signups[trial.signup_id].created_at <= trial.started_at
        assert trial.started_at.date() <= config.end_date
        assert trial.ends_at - trial.started_at == timedelta(days=TRIAL_DAYS)
    for customer in default_dataset.customers:
        trial = trials[customer.signup_id]
        assert trial.started_at <= customer.created_at <= trial.ends_at
        assert customer.created_at.date() <= config.end_date


def test_subscription_events_follow_a_valid_lifecycle(default_dataset: Dataset) -> None:
    config = default_dataset.config
    created = {row.customer_id: row.created_at for row in default_dataset.customers}
    allowed_next = {
        "new": {"upgrade", "downgrade", "cancel"},
        "upgrade": {"upgrade", "downgrade", "cancel"},
        "downgrade": {"upgrade", "downgrade", "cancel"},
        "reactivate": {"upgrade", "downgrade", "cancel"},
        "cancel": {"reactivate"},
    }
    for customer_id, events in events_by_customer(default_dataset).items():
        assert events[0].event_type == "new"
        assert events[0].occurred_at == created[customer_id]
        for event in events:
            assert event.occurred_at.date() <= event.effective_date <= config.end_date
        for previous, current in itertools.pairwise(events):
            assert current.event_type in allowed_next[previous.event_type]
            assert current.effective_date > previous.effective_date
            assert current.occurred_at >= previous.occurred_at


def test_invoices_cover_consecutive_periods(default_dataset: Dataset) -> None:
    for invoice in default_dataset.invoices:
        assert invoice.invoice_date == invoice.period_start < invoice.period_end
        assert invoice.period_start <= default_dataset.config.end_date
    invoices = {row.invoice_id: row for row in default_dataset.invoices}
    for payment in default_dataset.payments:
        invoice = invoices[payment.invoice_id]
        assert payment.attempted_at.date() >= invoice.invoice_date
        assert payment.received_at > payment.attempted_at


# --- billing consistency -------------------------------------------------------------------------


def test_invoice_amounts_and_statuses_are_consistent(default_dataset: Dataset) -> None:
    prices = {row.plan_price_id: row.unit_amount_cents for row in default_dataset.plans}
    attempts: dict[str, dict[str, str]] = defaultdict(dict)  # invoice -> payment_id -> status
    for payment in default_dataset.payments:
        attempts[payment.invoice_id][payment.payment_id] = payment.status

    end_date = default_dataset.config.end_date
    for invoice in default_dataset.invoices:
        assert invoice.amount_due_cents == prices[invoice.plan_price_id] * invoice.seats
        statuses = Counter(attempts[invoice.invoice_id].values())
        if invoice.status == "paid":
            assert statuses["succeeded"] == 1
        elif invoice.status == "uncollectible":
            assert statuses == Counter({"failed": 1 + len(RETRY_DAYS)})
        else:
            assert invoice.status == "open"
            assert statuses["succeeded"] == 0
            assert invoice.invoice_date + timedelta(days=RETRY_DAYS[-1]) > end_date


def test_involuntary_churn_follows_uncollectible_invoices(default_dataset: Dataset) -> None:
    uncollectible = Counter(
        invoice.customer_id
        for invoice in default_dataset.invoices
        if invoice.status == "uncollectible"
    )
    payment_failed = Counter(
        event.customer_id
        for event in default_dataset.subscription_events
        if event.cancel_reason == "payment_failed"
    )
    assert uncollectible == payment_failed
    assert sum(payment_failed.values()) > 0


def test_list_price_change_is_grandfathered(default_dataset: Dataset) -> None:
    change_date = default_dataset.config.price_change_date
    for event in default_dataset.subscription_events:
        if event.event_type in {"new", "reactivate"}:
            expected_version = "v2" if event.effective_date >= change_date else "v1"
            assert event.plan_price_id is not None
            assert event.plan_price_id.endswith(expected_version)
    grandfathered = [
        invoice
        for invoice in default_dataset.invoices
        if invoice.period_start >= change_date and invoice.plan_price_id.endswith("v1")
    ]
    assert grandfathered, "existing customers keep the old price after the change"


# --- calibration: generated rates land near the configured parameters ----------------------------


def test_cost_per_signup_matches_configuration(default_dataset: Dataset) -> None:
    spend: Counter[str] = Counter()
    for row in default_dataset.marketing_spend:
        spend[row.channel] += row.spend_cents
    signups = Counter(signup_channels(default_dataset).values())
    for channel in CHANNELS:
        if channel.daily_spend_usd == 0:
            assert spend[channel.name] == 0
            continue
        observed = spend[channel.name] / 100 / signups[channel.name]
        assert observed == pytest.approx(channel.cost_per_signup_usd, rel=0.05), channel.name


def test_funnel_conversion_matches_configuration(default_dataset: Dataset) -> None:
    channels = signup_channels(default_dataset)
    cutoff = default_dataset.config.end_date - timedelta(days=TRIAL_DAYS + 1)
    trial_signups = {row.signup_id for row in default_dataset.trials}
    mature_trials = {
        row.signup_id for row in default_dataset.trials if row.started_at.date() <= cutoff
    }
    paid_signups = {row.signup_id for row in default_dataset.customers}
    mature_signups = {
        row.signup_id for row in default_dataset.signups if row.created_at.date() <= cutoff
    }
    for channel in CHANNELS:
        signups = {s for s in mature_signups if channels[s] == channel.name}
        trials = {s for s in mature_trials if channels[s] == channel.name}
        signup_to_trial = len(signups & trial_signups) / len(signups)
        trial_to_paid = len(trials & paid_signups) / len(trials)
        assert signup_to_trial == pytest.approx(channel.signup_to_trial, abs=0.03), channel.name
        assert trial_to_paid == pytest.approx(channel.trial_to_paid, abs=0.04), channel.name


def test_annual_billing_share_matches_configuration(default_dataset: Dataset) -> None:
    intervals = {row.plan_price_id: row.billing_interval for row in default_dataset.plans}
    plan_codes = {row.plan_price_id: row.plan_code for row in default_dataset.plans}
    totals: Counter[str] = Counter()
    annual: Counter[str] = Counter()
    for event in default_dataset.subscription_events:
        if event.event_type == "new" and event.plan_price_id is not None:
            totals[plan_codes[event.plan_price_id]] += 1
            annual[plan_codes[event.plan_price_id]] += intervals[event.plan_price_id] == "year"
    for plan in PLANS:
        observed = annual[plan.code] / totals[plan.code]
        assert observed == pytest.approx(plan.annual_share, abs=0.05), plan.code


def test_payment_failure_and_duplicate_rates_match_configuration(default_dataset: Dataset) -> None:
    first_invoice_ids = set()
    seen_customers = set()
    for invoice in default_dataset.invoices:  # invoices are written in billing order per customer
        if invoice.customer_id not in seen_customers:
            first_invoice_ids.add(invoice.invoice_id)
            seen_customers.add(invoice.customer_id)
    first_attempts = {
        payment.payment_id: payment
        for payment in default_dataset.payments
        if payment.attempt_number == 1 and payment.invoice_id not in first_invoice_ids
    }
    failure_rate = sum(p.status == "failed" for p in first_attempts.values()) / len(first_attempts)
    assert failure_rate == pytest.approx(PAYMENT_FAILURE_RATE, abs=0.01)

    payment_ids = [payment.payment_id for payment in default_dataset.payments]
    duplicate_rate = (len(payment_ids) - len(set(payment_ids))) / len(set(payment_ids))
    assert duplicate_rate == pytest.approx(DUPLICATE_PAYMENT_RATE, abs=0.002)


def test_messy_utm_rate_matches_configuration(default_dataset: Dataset) -> None:
    raw = [row.utm_source for row in default_dataset.signups if row.utm_source is not None]
    messy = sum(value != value.strip().lower() for value in raw)
    assert messy / len(raw) == pytest.approx(MESSY_UTM_RATE, abs=0.01)


def test_cheaper_plans_churn_more(default_dataset: Dataset) -> None:
    """Voluntary churn per monthly renewal invoice is ordered starter > growth > enterprise."""
    plan_codes = {row.plan_price_id: row.plan_code for row in default_dataset.plans}
    intervals = {row.plan_price_id: row.billing_interval for row in default_dataset.plans}
    exposure: Counter[str] = Counter()
    for invoice in default_dataset.invoices:
        if intervals[invoice.plan_price_id] == "month":
            exposure[plan_codes[invoice.plan_price_id]] += 1
    churned: Counter[str] = Counter()
    for events in events_by_customer(default_dataset).values():
        for previous, current in itertools.pairwise(events):
            price_id = previous.plan_price_id
            if current.cancel_reason == "voluntary" and price_id and intervals[price_id] == "month":
                churned[plan_codes[price_id]] += 1
    rates = {code: churned[code] / exposure[code] for code in ("starter", "growth", "enterprise")}
    assert rates["starter"] > rates["growth"] > rates["enterprise"] > 0
