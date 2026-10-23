"""Orchestrates the simulation and returns every raw table in memory."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from saasgen.acquisition import simulate_acquisition
from saasgen.config import GeneratorConfig
from saasgen.lifecycle import BillingSimulator
from saasgen.pricing import PriceBook, build_price_book
from saasgen.records import (
    Customer,
    Invoice,
    MarketingSpend,
    Payment,
    Plan,
    Signup,
    SubscriptionEvent,
    Trial,
)


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[str, ...]
    rows: Sequence[tuple[object, ...]]


@dataclass(frozen=True)
class Dataset:
    config: GeneratorConfig
    plans: list[Plan]
    marketing_spend: list[MarketingSpend]
    signups: list[Signup]
    trials: list[Trial]
    customers: list[Customer]
    subscription_events: list[SubscriptionEvent]
    invoices: list[Invoice]
    payments: list[Payment]

    def tables(self) -> list[Table]:
        """The raw tables in the order they are written."""
        return [
            Table("plans", Plan._fields, self.plans),
            Table("marketing_spend", MarketingSpend._fields, self.marketing_spend),
            Table("signups", Signup._fields, self.signups),
            Table("trials", Trial._fields, self.trials),
            Table("customers", Customer._fields, self.customers),
            Table("subscription_events", SubscriptionEvent._fields, self.subscription_events),
            Table("invoices", Invoice._fields, self.invoices),
            Table("payments", Payment._fields, self.payments),
        ]


def generate(config: GeneratorConfig) -> Dataset:
    """Generate a complete dataset. Identical configs always give identical datasets."""
    # Independent random streams, so that changing one stage does not reshuffle the other.
    acquisition_seed, lifecycle_seed = np.random.SeedSequence(config.seed).spawn(2)
    prices = build_price_book(config)
    acquisition = simulate_acquisition(config, np.random.default_rng(acquisition_seed))

    billing = BillingSimulator(config, np.random.default_rng(lifecycle_seed), PriceBook(prices))
    for conversion in acquisition.conversions:
        billing.simulate(conversion.customer, conversion.company_size)

    return Dataset(
        config=config,
        plans=prices,
        marketing_spend=acquisition.marketing_spend,
        signups=acquisition.signups,
        trials=acquisition.trials,
        customers=[conversion.customer for conversion in acquisition.conversions],
        subscription_events=billing.events,
        invoices=billing.invoices,
        payments=billing.payments,
    )
