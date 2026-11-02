"""The load simulation: landing batches, comparing warehouses and running the steps in order.

dbt itself is replaced by a fake here; ``make incremental-check`` runs the real thing.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

import duckdb
import pytest

from saasgen import backfill as backfill_module
from saasgen.backfill import (
    MARKER,
    BackfillError,
    BackfillReport,
    DbtRun,
    backfill,
    compare_warehouses,
    init_landing,
    land,
    main,
)
from saasgen.batches import daily_batches, write_batches
from saasgen.config import GeneratorConfig
from saasgen.generator import generate

TINY = GeneratorConfig(seed=3, months=2, scale=0.1)


def make_warehouse(path: Path, *, payment_amount: float = 10.0, rate: float = 0.25) -> None:
    """A miniature warehouse with a model, a seed and a snapshot with history."""
    with duckdb.connect(str(path)) as connection:
        for schema in ("staging", "marts", "seeds", "snapshots"):
            connection.execute(f"create schema {schema}")
        connection.execute(
            "create table staging.stg_payments as select * from (values "
            f"('pay_1', {payment_amount}::decimal(18, 2)), ('pay_2', 5.00::decimal(18, 2))) "
            "as t(payment_id, amount_usd)"
        )
        connection.execute(f"create table marts.rpt_rates as select {rate}::double as rate")
        connection.execute("create table seeds.channel_mapping as select 'x' as utm_source")
        connection.execute(
            "create table snapshots.snp_subscription_state as select * from (values "
            "('cus_1', 'growth', null::timestamp)) as t(customer_id, plan_code, dbt_valid_to)"
        )


def test_landing_appends_each_days_rows(tmp_path: Path) -> None:
    batches = daily_batches(generate(TINY))
    write_batches(batches, tmp_path / "batches")
    landing = tmp_path / "raw"
    init_landing(landing, batches.columns)
    assert all(len(list(csv.reader((landing / f"{t}.csv").open()))) == 1 for t in batches.columns)
    by_day = batches.by_day()
    days = list(by_day)[:3]
    landed = sum(land(tmp_path / "batches" / day.isoformat(), landing) for day in days)
    assert landed == sum(len(rows) for day in days for rows in by_day[day].values())
    for table in batches.columns:
        with (landing / f"{table}.csv").open(newline="") as handle:
            rows = list(csv.reader(handle))
        assert rows[0] == list(batches.columns[table])
        assert len(rows) - 1 == sum(len(by_day[day].get(table, [])) for day in days)


def test_equal_warehouses_compare_equal(tmp_path: Path) -> None:
    make_warehouse(tmp_path / "incremental.duckdb", rate=0.1 + 0.2)
    make_warehouse(tmp_path / "refreshed.duckdb", rate=0.3)  # equal once rounded
    with duckdb.connect(str(tmp_path / "incremental.duckdb")) as connection:
        # An old snapshot version: history has no full-refresh counterpart, so it is ignored.
        connection.execute(
            "insert into snapshots.snp_subscription_state "
            "values ('cus_1', 'starter', timestamp '2024-01-01')"
        )
    comparisons = compare_warehouses(tmp_path / "incremental.duckdb", tmp_path / "refreshed.duckdb")
    assert [c.relation for c in comparisons] == [
        "marts.rpt_rates",
        "seeds.channel_mapping",
        "snapshots.snp_subscription_state",
        "staging.stg_payments",
    ]
    assert all(c.equal for c in comparisons)


def test_a_differing_row_is_reported_with_both_sides(tmp_path: Path) -> None:
    make_warehouse(tmp_path / "incremental.duckdb", payment_amount=10.0)
    make_warehouse(tmp_path / "refreshed.duckdb", payment_amount=10.01)
    comparisons = compare_warehouses(tmp_path / "incremental.duckdb", tmp_path / "refreshed.duckdb")
    [different] = [c for c in comparisons if not c.equal]
    assert different.relation == "staging.stg_payments"
    assert (different.only_incremental, different.only_full_refresh) == (1, 1)
    assert any("10.01" in sample for sample in different.samples)


def test_relations_missing_from_one_warehouse_are_an_error(tmp_path: Path) -> None:
    make_warehouse(tmp_path / "incremental.duckdb")
    make_warehouse(tmp_path / "refreshed.duckdb")
    with duckdb.connect(str(tmp_path / "refreshed.duckdb")) as connection:
        connection.execute("create table marts.extra as select 1 as x")
    with pytest.raises(BackfillError, match="only one warehouse"):
        compare_warehouses(tmp_path / "incremental.duckdb", tmp_path / "refreshed.duckdb")


class FakeDbt:
    """Records each dbt command and builds a miniature warehouse instead."""

    def __init__(self, failures: Mapping[str, tuple[str, ...]] | None = None) -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []
        self.failures = failures or {}

    def __call__(self, args: Sequence[str], env: Mapping[str, str]) -> DbtRun:
        self.calls.append((tuple(args), dict(env)))
        warehouse = Path(env["SAAS_WAREHOUSE"])
        if args[0] == "build" and not warehouse.exists():
            make_warehouse(warehouse)
        return DbtRun(1.0, 0.5, self.failures.get(args[0], ()))


def test_backfill_runs_the_initial_load_the_daily_builds_and_the_checks(tmp_path: Path) -> None:
    dbt = FakeDbt()
    logged: list[str] = []
    report = backfill(
        TINY, tmp_path / "work", daily_days=3, lookback_days=2, run_dbt=dbt, log=logged.append
    )

    commands = [args for args, _ in dbt.calls]
    lookback = ("--vars", '{"incremental_lookback_days": 2}')
    daily_build = ("build", "--exclude", "resource_type:test", *lookback)
    assert commands == [daily_build] * 4 + [
        ("test", *lookback),
        ("build", "--full-refresh", *lookback),
    ]
    warehouses = [Path(env["SAAS_WAREHOUSE"]).name for _, env in dbt.calls]
    assert warehouses == ["incremental.duckdb"] * 5 + ["refreshed.duckdb"]
    assert {env["SAAS_RAW_DIR"] for _, env in dbt.calls} == {str(tmp_path / "work" / "raw")}
    assert report.daily_days == [date(2023, 2, 26), date(2023, 2, 27), date(2023, 2, 28)]
    assert len(report.daily) == 3
    assert logged[0].startswith("initial load: 56 days (2023-01-01 to 2023-02-25)")
    assert report.equal
    rendered = report.render()
    assert "daily incremental build, median of 3" in rendered
    assert rendered.endswith("Incremental build equals the full refresh.")


def test_failing_tests_are_reported_and_failing_builds_stop_the_run(tmp_path: Path) -> None:
    failing_tests = FakeDbt({"test": ("test.saas_warehouse.unique_x",)})
    report = backfill(TINY, tmp_path / "a", daily_days=1, run_dbt=failing_tests, log=lambda _: None)
    assert not report.equal
    assert "Tests FAILED on the incremental warehouse: 1" in report.render()
    assert report.render().endswith("DIFFERS from the full refresh.")

    failing_builds = FakeDbt({"build": ("model.saas_warehouse.stg_x",)})
    with pytest.raises(BackfillError, match=r"initial build failed: model\.saas_warehouse\.stg_x"):
        backfill(TINY, tmp_path / "b", daily_days=1, run_dbt=failing_builds, log=lambda _: None)


def test_the_work_directory_is_reused_only_if_this_tool_made_it(tmp_path: Path) -> None:
    work = tmp_path / "work"
    backfill(TINY, work, daily_days=1, run_dbt=FakeDbt(), log=lambda _: None)
    assert (work / MARKER).exists()
    backfill(TINY, work, daily_days=1, run_dbt=FakeDbt(), log=lambda _: None)  # replaced

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("keep me")
    with pytest.raises(BackfillError, match="not empty"):
        backfill(TINY, foreign, daily_days=1, run_dbt=FakeDbt(), log=lambda _: None)
    assert (foreign / "notes.txt").read_text() == "keep me"
    with pytest.raises(ValueError, match="daily_days"):
        backfill(TINY, tmp_path / "c", daily_days=59, run_dbt=FakeDbt(), log=lambda _: None)


def test_main_exits_non_zero_when_the_warehouses_differ(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_backfill(config: GeneratorConfig, work_dir: Path, **options: object) -> BackfillReport:
        assert (config.months, options["daily_days"], options["lookback_days"]) == (3, 5, 0)
        return BackfillReport(daily_days=[])

    monkeypatch.setattr(backfill_module, "backfill", fake_backfill)
    args = [
        "--months",
        "3",
        "--daily-days",
        "5",
        "--lookback-days",
        "0",
        "--work-dir",
        str(tmp_path),
    ]
    assert main(args) == 1
    assert "DIFFERS" in capsys.readouterr().out
