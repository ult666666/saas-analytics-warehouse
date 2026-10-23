"""The price book: list prices per plan and billing interval, with one price change."""

from __future__ import annotations

from datetime import date

from saasgen.config import ANNUAL_DISCOUNT, CURRENCY, PLANS, GeneratorConfig
from saasgen.records import Plan

BILLING_INTERVALS = ("month", "year")


def unit_amount_cents(monthly_price_usd: int, billing_interval: str) -> int:
    """Price per seat for one billing interval, in cents."""
    if billing_interval == "month":
        return monthly_price_usd * 100
    return round(monthly_price_usd * 12 * (1 - ANNUAL_DISCOUNT) * 100)


def build_price_book(config: GeneratorConfig) -> list[Plan]:
    """Two price versions per plan and interval: before and after the list-price change."""
    versions = (
        (1, config.start_date, config.price_change_date),
        (2, config.price_change_date, None),
    )
    rows: list[Plan] = []
    for plan in PLANS:
        for version, valid_from, valid_to in versions:
            monthly_price = (
                plan.price_before_change_usd if version == 1 else plan.price_after_change_usd
            )
            for interval in BILLING_INTERVALS:
                interval_label = "monthly" if interval == "month" else "annual"
                rows.append(
                    Plan(
                        plan_price_id=f"{plan.code}_{interval_label}_v{version}",
                        plan_code=plan.code,
                        plan_name=plan.name,
                        plan_tier=plan.tier,
                        billing_interval=interval,
                        unit_amount_cents=unit_amount_cents(monthly_price, interval),
                        currency=CURRENCY,
                        valid_from=valid_from,
                        valid_to=valid_to,
                    )
                )
    return rows


class PriceBook:
    """Looks up the list price that applies to a plan on a given day."""

    def __init__(self, prices: list[Plan]) -> None:
        self._prices = prices

    def price_on(self, plan_code: str, billing_interval: str, day: date) -> Plan:
        for price in self._prices:
            if (
                price.plan_code == plan_code
                and price.billing_interval == billing_interval
                and price.valid_from <= day
                and (price.valid_to is None or day < price.valid_to)
            ):
                return price
        raise LookupError(f"no {billing_interval} price for {plan_code} on {day}")
