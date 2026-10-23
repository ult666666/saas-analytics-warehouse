"""Writes a dataset to one CSV file per raw table."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from saasgen.generator import Dataset


def format_value(value: object) -> str:
    """Render a value the way the raw CSV files store it."""
    if value is None:
        return ""
    if isinstance(value, datetime):  # check before date: datetime is a subclass of date
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def write_dataset(dataset: Dataset, out_dir: Path) -> dict[str, int]:
    """Write every table as ``<out_dir>/<table>.csv`` and return the row counts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    row_counts: dict[str, int] = {}
    for table in dataset.tables():
        path = out_dir / f"{table.name}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(table.columns)
            writer.writerows([format_value(value) for value in row] for row in table.rows)
        row_counts[table.name] = len(table.rows)
    return row_counts
