"""Tests for the report package against a small hand-built copy of the marts.

The fixture creates only the mart columns the report reads. The real marts are exercised
end to end by `make all` and in CI, where the report runs after `dbt build`.
"""

from __future__ import annotations

import runpy
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import duckdb
import pytest

from saasreport.charts import plot_mrr_bridge
from saasreport.cli import build_report, main
from saasreport.data import CohortCell, load_report_data, pooled_retention
from saasreport.formatting import (
    month_label,
    optional,
    pct,
    signed_usd,
    signed_usd_compact,
    usd,
    usd_compact,
)
from saasreport.markdown import table

MART_DDL = """
    create schema marts;
    create table marts.rpt_mrr_bridge (
        month_start date, starting_mrr_usd decimal(18, 2), new_mrr_usd decimal(18, 2),
        expansion_mrr_usd decimal(18, 2), reactivation_mrr_usd decimal(18, 2),
        contraction_mrr_usd decimal(18, 2), churned_mrr_usd decimal(18, 2),
        involuntary_churned_mrr_usd decimal(18, 2), ending_mrr_usd decimal(18, 2),
        starting_customers integer, new_customers integer, churned_customers integer,
        ending_customers integer
    );
    create table marts.rpt_cohort_retention (
        cohort_month date, months_since_cohort_start integer, cohort_customers integer,
        active_customers integer, cohort_starting_mrr_usd decimal(18, 2), mrr_usd decimal(18, 2)
    );
    create table marts.rpt_unit_economics (
        channel varchar, marketing_spend_usd decimal(18, 2), new_customers integer,
        cac_usd decimal(18, 2), arpa_usd decimal(18, 2), gross_margin_pct double,
        monthly_logo_churn_rate double, ltv_usd decimal(18, 2), cac_payback_months double,
        ltv_to_cac_ratio double
    );
    create table marts.rpt_funnel (
        signup_month date, channel varchar, signups integer, trials integer,
        paid_customers integer, is_complete_cohort boolean
    );
    create table marts.dim_plans (
        plan_price_id varchar, plan_name varchar, plan_tier integer, is_current_price boolean
    );
    create table marts.fct_mrr (
        customer_id varchar, month_start date, plan_price_id varchar, mrr_usd decimal(18, 2),
        is_active boolean
    );
"""


def create_marts(path: Path, months: int = 14) -> None:
    """Write a consistent miniature warehouse: the bridge reconciles month by month."""
    with duckdb.connect(str(path)) as connection:
        connection.execute(MART_DDL)
        ending, customers = 0.0, 0
        for index in range(months):
            month = date(2024 + (index // 12), index % 12 + 1, 1)
            new, expansion, reactivation = 1_000.0 + 100 * index, 200.0, 50.0 * (index % 2)
            contraction, churned = (-80.0, -300.0) if index else (0.0, 0.0)
            starting, starting_customers = ending, customers
            ending = starting + new + expansion + reactivation + contraction + churned
            customers = starting_customers + 10 - (3 if index else 0)
            connection.execute(
                "insert into marts.rpt_mrr_bridge values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    month,
                    starting,
                    new,
                    expansion,
                    reactivation,
                    contraction,
                    churned,
                    churned / 3,
                    ending,
                    starting_customers,
                    10,
                    3 if index else 0,
                    customers,
                ],
            )
        for cohort in range(4):
            for offset in range(4 - cohort):
                connection.execute(
                    "insert into marts.rpt_cohort_retention values (?, ?, ?, ?, ?, ?)",
                    [
                        date(2024, cohort + 1, 1),
                        offset,
                        10 * (cohort + 1),
                        10 * (cohort + 1) - offset,
                        1_000.0,
                        1_000.0 - 50 * offset,
                    ],
                )
        connection.execute(
            """
            insert into marts.rpt_unit_economics values
                ('organic', 0, 40, null, 450, 0.8, 0.03, 12000, null, null),
                ('paid_search', 200000, 40, 5000, 500, 0.8, 0.025, 16000, 12.5, 3.2),
                ('paid_social', 120000, 20, 6000, 400, 0.8, 0.033, 9700, 18.75, 1.6),
                ('content', 30000, 12, 2500, 480, 0.8, 0.031, 12400, 6.5, 5.0),
                ('partner', 60000, 13, 4615, 850, 0.8, 0.028, 24300, 6.8, 5.3),
                ('all_channels', 410000, 125, 3280, 520, 0.8, 0.029, 14300, 7.9, 4.4)
            """
        )
        connection.execute(
            """
            insert into marts.rpt_funnel values
                ('2024-01-01', 'paid_search', 100, 75, 15, true),
                ('2024-02-01', 'paid_search', 120, 90, 18, true),
                ('2024-01-01', 'organic', 80, 56, 12, true),
                ('2024-01-01', 'partner', 20, 17, 5, true),
                ('2024-03-01', 'partner', 25, 20, 1, false)
            """
        )
        connection.execute(
            """
            insert into marts.dim_plans values
                ('growth_monthly_v1', 'Growth', 2, false),
                ('growth_monthly_v2', 'Growth', 2, true),
                ('starter_monthly_v2', 'Starter', 1, true)
            """
        )
        last_month = date(2024 + ((months - 1) // 12), (months - 1) % 12 + 1, 1)
        connection.execute(
            """
            insert into marts.fct_mrr values
                ('c1', ?, 'growth_monthly_v1', 290, true),
                ('c2', ?, 'growth_monthly_v2', 340, true),
                ('c3', ?, 'starter_monthly_v2', 28, true),
                ('c4', ?, null, 0, false)
            """,
            [last_month] * 4,
        )


@pytest.fixture
def marts_db(tmp_path: Path) -> Path:
    path = tmp_path / "warehouse.duckdb"  # a file named marts.duckdb would clash with the schema
    create_marts(path)
    return path


def test_report_writes_every_figure_and_the_markdown(
    marts_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "reports"
    assert main(["--database", str(marts_db), "--output-dir", str(output)]) == 0

    figures = sorted(path.name for path in (output / "figures").glob("*.png"))
    assert figures == [
        "cac_payback.png",
        "cohort_retention.png",
        "funnel.png",
        "mrr_bridge.png",
        "mrr_trend.png",
    ]
    for path in (output / "figures").glob("*.png"):
        content = path.read_bytes()
        assert content.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(content) < 300_000
    assert capsys.readouterr().out.count("wrote ") == 6

    report = (output / "report.md").read_text(encoding="utf-8")
    with duckdb.connect(str(marts_db), read_only=True) as connection:
        data = load_report_data(connection)
    assert "**All data is synthetic.**" in report
    assert f"| Ending MRR | {usd(data.last_month.ending_mrr)} |" in report
    assert "| Organic | $0 | 40 | n/a |" in report  # no spend, so no CAC
    assert "| Paid search | 220 | 165 | 33 | 75.0% | 20.0% | 15.0% |" in report
    assert "| Partner | 20 |" in report  # the incomplete March cohort is excluded
    assert "| Growth | 2 | $630 | 95.7% | 46.0% |" in report  # 630 of 658; 290 grandfathered
    assert str(tmp_path) not in report  # links are relative, so the report is portable


def test_report_is_byte_for_byte_reproducible(marts_db: Path, tmp_path: Path) -> None:
    first = build_report(marts_db, tmp_path / "first")
    second = build_report(marts_db, tmp_path / "second")
    for one, two in zip(first, second, strict=True):
        assert one.read_bytes() == two.read_bytes(), one.name


def test_short_history_shrinks_the_trailing_window(tmp_path: Path) -> None:
    database = tmp_path / "short.duckdb"
    create_marts(database, months=3)
    build_report(database, tmp_path / "reports")
    report = (tmp_path / "reports" / "report.md").read_text(encoding="utf-8")
    assert "## MRR bridge, Jan 2024 to Mar 2024" in report


def test_missing_database_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--database", str(tmp_path / "missing.duckdb")])
    assert excinfo.value.code == 2
    assert "run 'make build' first" in capsys.readouterr().err


def test_empty_bridge_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "empty.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(MART_DDL)
    with (
        duckdb.connect(str(database), read_only=True) as connection,
        pytest.raises(ValueError, match="empty"),
    ):
        load_report_data(connection)


def test_bridge_chart_refuses_a_bridge_that_does_not_reconcile(
    marts_db: Path, tmp_path: Path
) -> None:
    with duckdb.connect(str(marts_db), read_only=True) as connection:
        data = load_report_data(connection)
    broken_last = replace(data.bridge[-1], ending_mrr=data.bridge[-1].ending_mrr + 1)
    broken = replace(data, bridge=[*data.bridge[:-1], broken_last])
    with pytest.raises(ValueError, match="does not reconcile"):
        plot_mrr_bridge(broken, tmp_path / "bridge.png")


def test_pooled_retention_is_a_ratio_of_sums() -> None:
    cells = [
        CohortCell(
            date(2024, 1, 1),
            1,
            cohort_customers=100,
            active_customers=90,
            starting_mrr=1_000,
            mrr=1_100,
        ),
        CohortCell(
            date(2024, 2, 1), 1, cohort_customers=10, active_customers=5, starting_mrr=100, mrr=50
        ),
    ]
    [point] = pooled_retention(cells)
    assert point.cohorts == 2
    assert point.logo_retention == pytest.approx(95 / 110)  # not the mean of 90% and 50%
    assert point.net_revenue_retention == pytest.approx(1_150 / 1_100)


def test_formatting_helpers() -> None:
    assert usd(1_147_877.4) == "$1,147,877"
    assert usd(-56_929.2) == "-$56,929"
    assert signed_usd(556_409) == "+$556,409"
    assert signed_usd(-212_404) == "-$212,404"
    assert signed_usd(0.2) == "$0"
    assert usd_compact(1_147_877) == "$1.15M"
    assert usd_compact(56_929) == "$56.9k"
    assert usd_compact(-950) == "-$950"
    assert signed_usd_compact(19_475) == "+$19.5k"
    assert pct(0.70123) == "70.1%"
    assert pct(0.5, 0) == "50%"
    assert optional(None) == "n/a"
    assert optional(12.25, "{:.1f}") == "12.2"
    assert month_label(date(2025, 12, 1)) == "Dec 2025"


def test_markdown_table_right_aligns_numeric_columns() -> None:
    assert table(["Metric", "Value"], [["MRR", "$1"]]) == [
        "| Metric | Value |",
        "| --- | ---: |",
        "| MRR | $1 |",
    ]


def test_module_entry_point_shows_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["saasreport", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("saasreport", run_name="__main__")
    assert excinfo.value.code == 0
    assert "usage: saasreport" in capsys.readouterr().out
