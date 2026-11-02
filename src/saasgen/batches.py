"""Split a generated dataset into the daily batches a warehouse would receive.

``write_dataset`` writes each table as it looks at the end of the simulation.
A warehouse that loads every day sees the same rows arrive over time instead:

* a signup, trial or customer on the day it was created, a subscription event on
  the day it was recorded (``occurred_at``) and a payment when its webhook
  arrived (``received_at``, which is never late by definition);
* an invoice on the day it was issued and, if its status changed later (paid on
  a retry, or uncollectible), again on that day: a newer version of the same
  ``invoice_id``, which the warehouse must use in place of the first;
* the price book and the marketing spend on time, every day. Marketing spend
  defines the warehouse's calendar (``int_date_spine``), so it is never late.

A seeded share of the other rows arrives late, by one to a few days, as late
webhooks and delayed exports do. Rows due after the last simulated day arrive on
that day. Loading every batch gives back exactly the rows of ``write_dataset``,
keeping the newest version of each invoice.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from saasgen.config import LATE_ARRIVAL_SHARE, MAX_ARRIVAL_DELAY_DAYS
from saasgen.generator import Dataset
from saasgen.records import Invoice
from saasgen.writer import format_value

Row = tuple[object, ...]


@dataclass(frozen=True)
class Arrival:
    """One row reaching the warehouse."""

    table: str
    row: Row
    known_on: date
    """The day the row would arrive if nothing were late."""
    arrives_on: date


@dataclass(frozen=True)
class DailyBatches:
    columns: dict[str, tuple[str, ...]]
    """Column names of every raw table, in CSV order."""
    arrivals: list[Arrival]

    def by_day(self) -> dict[date, dict[str, list[Row]]]:
        """The rows arriving on each day, by table, in day order."""
        days: dict[date, dict[str, list[Row]]] = defaultdict(lambda: defaultdict(list))
        for arrival in self.arrivals:
            days[arrival.arrives_on][arrival.table].append(arrival.row)
        return {day: dict(days[day]) for day in sorted(days)}


def daily_batches(
    dataset: Dataset,
    *,
    late_share: float = LATE_ARRIVAL_SHARE,
    max_delay_days: int = MAX_ARRIVAL_DELAY_DAYS,
) -> DailyBatches:
    """Assign every row of ``dataset`` the day it reaches the warehouse."""
    if not 0 <= late_share <= 1:
        raise ValueError("late_share must be between 0 and 1")
    if max_delay_days < 1:
        raise ValueError("max_delay_days must be at least 1")
    config = dataset.config
    # A third random stream: the first two drive the simulation itself
    # (generator.generate), so the arrival pattern never changes the data.
    rng = np.random.default_rng(np.random.SeedSequence(config.seed).spawn(3)[2])
    arrivals = []
    for table, row, known_on, may_be_late in _known_rows(dataset):
        delay = 0
        if may_be_late and rng.random() < late_share:
            delay = int(rng.integers(1, max_delay_days + 1))
        arrives_on = min(known_on + timedelta(days=delay), config.end_date)
        arrivals.append(Arrival(table, row, known_on, arrives_on))
    columns = {table.name: table.columns for table in dataset.tables()}
    return DailyBatches(columns, arrivals)


def write_batches(batches: DailyBatches, out_dir: Path) -> dict[date, int]:
    """Write ``<out_dir>/<YYYY-MM-DD>/<table>.csv`` for every table with rows that day.

    Returns the number of rows in each day's batch.
    """
    rows_per_day: dict[date, int] = {}
    for day, tables in batches.by_day().items():
        day_dir = out_dir / day.isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        for table, rows in tables.items():
            write_rows(day_dir / f"{table}.csv", batches.columns[table], rows)
        rows_per_day[day] = sum(len(rows) for rows in tables.values())
    return rows_per_day


def write_rows(path: Path, columns: Sequence[str], rows: Sequence[Row]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows([format_value(value) for value in row] for row in rows)


def _known_rows(dataset: Dataset) -> Iterator[tuple[str, Row, date, bool]]:
    """Every row with the day it becomes known and whether it may arrive late."""
    start = dataset.config.start_date
    for plan in dataset.plans:
        yield "plans", plan, start, False
    for spend in dataset.marketing_spend:
        yield "marketing_spend", spend, spend.spend_date, False
    for signup in dataset.signups:
        yield "signups", signup, signup.created_at.date(), True
    for trial in dataset.trials:
        yield "trials", trial, trial.started_at.date(), True
    for customer in dataset.customers:
        yield "customers", customer, customer.created_at.date(), True
    for event in dataset.subscription_events:
        yield "subscription_events", event, event.occurred_at.date(), True
    first_charge = {
        payment.invoice_id: payment.attempted_at
        for payment in dataset.payments
        if payment.attempt_number == 1
    }
    for invoice in dataset.invoices:
        for version in invoice_versions(invoice, first_charge[invoice.invoice_id]):
            yield "invoices", version, version.updated_at.date(), True
    # received_at is when the webhook reached the warehouse, so payments are never late:
    # their lateness is the gap after attempted_at, which crosses midnight at times.
    for payment in dataset.payments:
        yield "payments", payment, payment.received_at.date(), False


def invoice_versions(invoice: Invoice, first_charge: datetime) -> list[Invoice]:
    """The states an invoice goes through: open when the first charge fails, then final.

    An invoice paid by its first charge, or still open when the data ends, has
    one version; one paid on a retry or written off has two.
    """
    if invoice.updated_at == first_charge:
        return [invoice]
    return [invoice._replace(status="open", updated_at=first_charge), invoice]
