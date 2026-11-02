"""Daily batches: the same seeded rows, arriving over time, some of them late."""

from __future__ import annotations

import csv
from collections import Counter
from datetime import timedelta
from math import sqrt
from pathlib import Path

import pytest

from saasgen.batches import DailyBatches, daily_batches, invoice_versions, write_batches
from saasgen.cli import main
from saasgen.config import LATE_ARRIVAL_SHARE, MAX_ARRIVAL_DELAY_DAYS, GeneratorConfig
from saasgen.generator import Dataset, generate
from saasgen.writer import format_value

NEVER_LATE = {"plans", "marketing_spend", "payments"}


@pytest.fixture(scope="module")
def small_dataset(small_config: GeneratorConfig) -> Dataset:
    return generate(small_config)


@pytest.fixture(scope="module")
def default_batches(default_dataset: Dataset) -> DailyBatches:
    return daily_batches(default_dataset)


def test_loading_every_batch_gives_back_the_dataset(
    default_dataset: Dataset, default_batches: DailyBatches
) -> None:
    arrived: dict[str, Counter[tuple[object, ...]]] = {}
    for arrival in default_batches.arrivals:
        arrived.setdefault(arrival.table, Counter())[arrival.row] += 1
    for table in default_dataset.tables():
        if table.name == "invoices":
            continue
        assert arrived[table.name] == Counter(table.rows), table.name
    # Invoices can arrive twice; the newest version of each is the final invoice.
    newest: dict[str, tuple[object, ...]] = {}
    for arrival in default_batches.arrivals:
        if arrival.table == "invoices":
            row = arrival.row
            current = newest.get(str(row[0]))
            if current is None or row[-1] > current[-1]:  # type: ignore[operator]
                newest[str(row[0])] = row
    assert sorted(newest.values()) == sorted(default_dataset.invoices)


def test_rows_arrive_on_or_after_the_day_they_are_known(
    default_dataset: Dataset, default_batches: DailyBatches
) -> None:
    end = default_dataset.config.end_date
    for arrival in default_batches.arrivals:
        assert arrival.known_on <= arrival.arrives_on <= end
        assert arrival.arrives_on - arrival.known_on <= timedelta(days=MAX_ARRIVAL_DELAY_DAYS)
        if arrival.table in NEVER_LATE:
            assert arrival.arrives_on == arrival.known_on, arrival


def test_the_late_share_matches_the_configured_share(default_batches: DailyBatches) -> None:
    may_be_late = [a for a in default_batches.arrivals if a.table not in NEVER_LATE]
    end = max(a.arrives_on for a in default_batches.arrivals)
    # Rows known in the last days can only be delayed up to the last day; leave them out.
    measurable = [a for a in may_be_late if a.known_on <= end - timedelta(MAX_ARRIVAL_DELAY_DAYS)]
    late = sum(a.arrives_on > a.known_on for a in measurable)
    expected = LATE_ARRIVAL_SHARE * len(measurable)
    sigma = sqrt(len(measurable) * LATE_ARRIVAL_SHARE * (1 - LATE_ARRIVAL_SHARE))
    assert abs(late - expected) < 4 * sigma
    delays = Counter(
        (a.arrives_on - a.known_on).days for a in measurable if a.arrives_on > a.known_on
    )
    assert set(delays) == set(range(1, MAX_ARRIVAL_DELAY_DAYS + 1))


def test_batches_are_deterministic(small_dataset: Dataset) -> None:
    assert daily_batches(small_dataset) == daily_batches(small_dataset)
    later = daily_batches(small_dataset, late_share=1.0, max_delay_days=2)
    assert all(
        a.arrives_on > a.known_on
        for a in later.arrivals
        if a.table not in NEVER_LATE and a.known_on < small_dataset.config.end_date
    )


@pytest.mark.parametrize(("late_share", "max_delay_days"), [(-0.1, 3), (1.5, 3), (0.1, 0)])
def test_rejects_impossible_settings(
    small_dataset: Dataset, late_share: float, max_delay_days: int
) -> None:
    with pytest.raises(ValueError, match="must be"):
        daily_batches(small_dataset, late_share=late_share, max_delay_days=max_delay_days)


def test_an_invoice_arrives_again_when_its_status_changes(default_dataset: Dataset) -> None:
    first_charges = {p.invoice_id: p for p in default_dataset.payments if p.attempt_number == 1}
    seen = Counter()
    for invoice in default_dataset.invoices:
        first = first_charges[invoice.invoice_id]
        versions = invoice_versions(invoice, first.attempted_at)
        assert versions[-1] == invoice
        if first.status == "succeeded":
            assert versions == [invoice]
            seen["paid by the first charge"] += 1
        elif invoice.status == "open":
            assert versions == [invoice]
            seen["still open"] += 1
        else:
            opened, final = versions
            assert (opened.status, opened.updated_at) == ("open", first.attempted_at)
            assert opened.updated_at.date() == invoice.invoice_date
            assert final.updated_at > opened.updated_at
            seen[f"two versions, {invoice.status}"] += 1
    assert set(seen) == {
        "paid by the first charge",
        "still open",
        "two versions, paid",
        "two versions, uncollectible",
    }


def test_write_batches_writes_one_folder_per_day(small_dataset: Dataset, tmp_path: Path) -> None:
    batches = daily_batches(small_dataset)
    rows_per_day = write_batches(batches, tmp_path)
    assert sum(rows_per_day.values()) == len(batches.arrivals)
    by_day = batches.by_day()
    assert list(rows_per_day) == list(by_day)
    day = next(iter(by_day))
    for table, rows in by_day[day].items():
        with (tmp_path / day.isoformat() / f"{table}.csv").open(newline="") as handle:
            written = list(csv.reader(handle))
        assert tuple(written[0]) == batches.columns[table]
        assert written[1:] == [[format_value(v) for v in row] for row in rows]


def test_cli_writes_daily_batches(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "batches"
    args = ["--months", "2", "--scale", "0.1", "--daily-batches", str(out), "--late-share", "0.5"]
    assert main(args) == 0
    summary = capsys.readouterr().out
    assert "daily batches" in summary and "late" in summary
    assert (out / "2023-01-01" / "plans.csv").exists()
    with pytest.raises(SystemExit):
        main([*args[:-1], "1.5"])
