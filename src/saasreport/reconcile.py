"""Check monthly bridge balances and unit economics spend directly against the raw CSVs."""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from itertools import zip_longest
from pathlib import Path

import duckdb

from saasgen.config import CHANNELS_BY_NAME
from saasgen.dates import add_months, month_end, month_start


def _read(raw_dir: Path, table: str, columns: set[str]) -> list[dict[str, str]]:
    path = raw_dir / f"{table}.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        try:
            header = reader.fieldnames or []
            missing = columns.difference(header)
            if missing:
                raise ValueError(f"{path.name}: missing columns {', '.join(sorted(missing))}")
            if len(set(header)) != len(header):
                raise ValueError(f"{path.name}: duplicate column names")
            rows = []
            for row in reader:
                if None in row or None in row.values():
                    raise ValueError(
                        f"{path.name} line {reader.line_num}: expected {len(header)} fields"
                    )
                rows.append(row)
        except csv.Error as error:
            raise ValueError(f"{path.name} line {reader.line_num}: {error}") from error
    return rows


def _closed_months(spend: list[dict[str, str]]) -> list[date]:
    try:
        days = [date.fromisoformat(row["spend_date"]) for row in spend]
    except ValueError as error:
        raise ValueError(f"marketing_spend.csv: invalid spend_date: {error}") from error
    if not days:
        raise ValueError("marketing_spend.csv: no spend dates to establish the reporting calendar")
    first, last = min(days), max(days)
    month = month_start(first)
    if first != month:
        month = add_months(month, 1)
    closed = []
    while month_end(month) <= last:
        closed.append(month)
        month = add_months(month, 1)
    return closed


def _event_order(event: dict[str, str]) -> tuple[date, datetime, str]:
    try:
        effective = date.fromisoformat(event["effective_date"])
    except ValueError as error:
        raise ValueError(
            f"subscription_events.csv event {event['event_id']}: invalid effective_date: {error}"
        ) from error
    try:
        occurred = datetime.fromisoformat(event["occurred_at"])
    except ValueError as error:
        raise ValueError(
            f"subscription_events.csv event {event['event_id']}: invalid occurred_at: {error}"
        ) from error
    # The raw timestamps are UTC wall-clock times, stored in a TIMESTAMP without a time zone.
    return effective, occurred.replace(tzinfo=None), event["event_id"]


def _balances(raw_dir: Path, months: list[date]) -> list[tuple[date, int, Decimal]]:
    """Replay events in effective order, observing the customer balances at each month end."""
    plans = _read(raw_dir, "plans", {"plan_price_id", "unit_amount_cents", "billing_interval"})
    prices = {row["plan_price_id"]: row for row in plans}
    events = sorted(
        _read(
            raw_dir,
            "subscription_events",
            {
                "effective_date",
                "occurred_at",
                "event_id",
                "customer_id",
                "event_type",
                "plan_price_id",
                "seats",
            },
        ),
        key=_event_order,
    )
    current: dict[str, Decimal] = {}
    balances = []
    index = 0
    for month in months:
        cutoff = month_end(month)
        while index < len(events) and date.fromisoformat(events[index]["effective_date"]) <= cutoff:
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
    spend = _read(raw_dir, "marketing_spend", {"spend_date", "channel", "spend_cents"})
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
