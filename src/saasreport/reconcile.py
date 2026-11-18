"""Check monthly bridge balances and unit economics spend directly against the raw CSVs."""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from itertools import zip_longest
from pathlib import Path

import duckdb

from saasgen.config import CHANNELS_BY_NAME
from saasgen.dates import add_months, month_end, month_start


def _read(raw_dir: Path, table: str) -> list[dict[str, str]]:
    with (raw_dir / f"{table}.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _closed_months(spend: list[dict[str, str]]) -> list[date]:
    days = [date.fromisoformat(row["spend_date"]) for row in spend]
    if not days:
        return []
    first, last = min(days), max(days)
    month = month_start(first)
    if first != month:
        month = add_months(month, 1)
    closed = []
    while month_end(month) <= last:
        closed.append(month)
        month = add_months(month, 1)
    return closed


def _balances(raw_dir: Path, months: list[date]) -> list[tuple[date, int, Decimal]]:
    """Replay events in effective order, observing the customer balances at each month end."""
    prices = {row["plan_price_id"]: row for row in _read(raw_dir, "plans")}
    events = sorted(
        _read(raw_dir, "subscription_events"),
        key=lambda row: (row["effective_date"], row["occurred_at"], row["event_id"]),
    )
    current: dict[str, Decimal] = {}
    balances = []
    index = 0
    for month in months:
        cutoff = month_end(month).isoformat()
        while index < len(events) and events[index]["effective_date"] <= cutoff:
            event = events[index]
            index += 1
            customer = event["customer_id"]
            if event["event_type"] == "cancel":
                current.pop(customer, None)
                continue
            price = prices[event["plan_price_id"]]
            cents = int(event["seats"]) * int(price["unit_amount_cents"])
            interval = {"month": 1, "year": 12}[price["billing_interval"]]
            current[customer] = (Decimal(cents) / (100 * interval)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        balances.append(
            (month, sum(mrr > 0 for mrr in current.values()), sum(current.values(), Decimal(0)))
        )
    return balances


def _channel_spend(
    spend: list[dict[str, str]], window: list[date]
) -> list[tuple[str, date | None, date | None, Decimal]]:
    first = window[0] if window else None
    last = month_end(window[-1]) if window else None
    cents = dict.fromkeys(CHANNELS_BY_NAME, 0)
    for row in spend:
        day = date.fromisoformat(row["spend_date"])
        if first is not None and last is not None and first <= day <= last:
            cents[row["channel"]] += int(row["spend_cents"])
    cents["all_channels"] = sum(cents.values())
    return [(name, first, last, Decimal(total) / 100) for name, total in sorted(cents.items())]


def _compare(
    measure: str, expected: Sequence[tuple[object, ...]], observed: Sequence[tuple[object, ...]]
) -> None:
    for raw, mart in zip_longest(expected, observed):
        if raw != mart:
            raise ValueError(f"{measure} mismatch: raw CSVs give {raw}, warehouse gives {mart}")


def reconcile(raw_dir: Path, database: Path, lookback_months: int = 12) -> tuple[int, int]:
    """Raise on the first mismatch. Return the number of months and spend rows checked."""
    if lookback_months < 1:
        raise ValueError("lookback months must be positive")
    spend = _read(raw_dir, "marketing_spend")
    months = _closed_months(spend)
    expected_spend = _channel_spend(spend, months[-lookback_months:])
    with duckdb.connect(str(database), read_only=True) as connection:
        _compare(
            "month, paying customers, ending MRR",
            _balances(raw_dir, months),
            connection.execute(
                """select month_start, ending_customers, ending_mrr_usd
                   from marts.rpt_mrr_bridge order by month_start"""
            ).fetchall(),
        )
        _compare(
            "channel, window start, window end, spend",
            expected_spend,
            connection.execute(
                """select channel, window_start, window_end, marketing_spend_usd
                   from marts.rpt_unit_economics order by channel"""
            ).fetchall(),
        )
    return len(months), len(expected_spend)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--database", type=Path, default=Path("data/warehouse.duckdb"))
    parser.add_argument(
        "--lookback-months", type=int, default=12, help="dbt unit_economics_lookback_months (12)"
    )
    args = parser.parse_args(argv)
    try:
        months, rows = reconcile(args.raw_dir, args.database, args.lookback_months)
    except (OSError, ValueError, KeyError, duckdb.Error) as error:
        print(f"Reconciliation failed: {error}", file=sys.stderr)
        return 1
    print(f"Raw CSVs agree with {months} monthly balances and {rows} channel spend rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
