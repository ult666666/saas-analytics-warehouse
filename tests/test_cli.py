"""Tests for the CSV writer and the ``saasgen`` command line."""

from __future__ import annotations

import csv
import runpy
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from saasgen.cli import main
from saasgen.config import GeneratorConfig
from saasgen.generator import generate
from saasgen.writer import format_value, write_dataset


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (datetime(2024, 3, 5, 7, 8, 9), "2024-03-05 07:08:09"),
        (date(2024, 3, 5), "2024-03-05"),
        (1250, "1250"),
        ("growth", "growth"),
    ],
)
def test_format_value(value: object, expected: str) -> None:
    assert format_value(value) == expected


def test_write_dataset_writes_headers_and_rows(
    small_config: GeneratorConfig, tmp_path: Path
) -> None:
    dataset = generate(small_config)
    counts = write_dataset(dataset, tmp_path)
    assert set(counts) == {table.name for table in dataset.tables()}
    for table in dataset.tables():
        with (tmp_path / f"{table.name}.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        assert tuple(rows[0]) == table.columns
        assert len(rows) - 1 == counts[table.name] == len(table.rows)


def test_cli_generates_files_and_prints_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--seed", "3", "--months", "3", "--scale", "0.1", "--out", str(tmp_path)])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "seed=3" in output
    assert "2023-01-01 to 2023-03-31" in output
    assert sorted(path.name for path in tmp_path.glob("*.csv")) == [
        "customers.csv",
        "invoices.csv",
        "marketing_spend.csv",
        "payments.csv",
        "plans.csv",
        "signups.csv",
        "subscription_events.csv",
        "trials.csv",
    ]


def test_cli_rejects_invalid_configuration(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--start", "2023-01-15"])
    assert excinfo.value.code == 2
    assert "first day of a month" in capsys.readouterr().err


def test_module_entry_point_shows_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["saasgen", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("saasgen", run_name="__main__")
    assert excinfo.value.code == 0
    assert "usage: saasgen" in capsys.readouterr().out
