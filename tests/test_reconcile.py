"""Independent fixtures for the raw-to-mart command. CI also checks its generated warehouse."""

from pathlib import Path

import duckdb
import pytest

from saasreport.reconcile import main, reconcile


@pytest.fixture
def source_and_warehouse(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "plans.csv").write_text(
        "plan_price_id,billing_interval,unit_amount_cents\nannual,year,1210\nmonthly,month,1000\n"
    )
    (tmp_path / "subscription_events.csv").write_text(
        "event_id,customer_id,event_type,effective_date,occurred_at,plan_price_id,seats\n"
        "3,b,new,2024-02-29,2024-02-29,monthly,2\n"
        "1,a,new,2024-01-31,2024-01-31,annual,3\n"
        "2,a,cancel,2024-02-29,2024-02-24,,\n"
        "4,c,new,2024-03-12,2024-03-12,monthly,1\n"
    )
    (tmp_path / "marketing_spend.csv").write_text(
        "spend_date,channel,spend_cents\n"
        "2024-01-01,paid_search,33\n2024-01-31,content,12\n"
        "2024-02-01,content,5500\n2024-02-29,paid_search,6\n"
        "2024-03-15,content,42000\n"
    )
    database = tmp_path / "warehouse.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            create schema marts;
            create table marts.rpt_mrr_bridge
                (month_start date, ending_customers int, ending_mrr_usd decimal(18,2));
            insert into marts.rpt_mrr_bridge values
                ('2024-01-01', 1, 3.03), ('2024-02-01', 1, 20.00);
            create table marts.rpt_unit_economics as
                select channel, date '2024-02-01' as window_start, date '2024-02-29' as window_end,
                       spend as marketing_spend_usd
                from (values ('content',55.00), ('paid_search',0.06), ('organic',0),
                             ('paid_social',0), ('partner',0), ('all_channels',55.06))
                     as totals(channel,spend);
            """
        )
    return tmp_path, database


def test_replays_month_end_events_and_measures_spend_only_in_the_configured_window(
    source_and_warehouse: tuple[Path, Path],
) -> None:
    raw, database = source_and_warehouse
    # Annual MRR is rounded after multiplying by all three seats ($3.025 -> $3.03).
    # The February cancellation and new account both take effect on leap day.
    assert reconcile(raw, database, lookback_months=1) == (2, 6)


def test_before_the_first_complete_month(
    source_and_warehouse: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw, database = source_and_warehouse
    (raw / "marketing_spend.csv").write_text(
        "spend_date,channel,spend_cents\n2024-01-15,content,100\n2024-02-15,content,100\n"
    )
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            delete from marts.rpt_mrr_bridge;
            update marts.rpt_unit_economics
            set window_start=null, window_end=null, marketing_spend_usd=0;
            """
        )
    assert main(["--raw-dir", str(raw), "--database", str(database)]) == 0
    assert "0 monthly balances and 6 channel spend rows" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("change", "metric"),
    [
        ("delete from marts.rpt_mrr_bridge where month_start='2024-02-01'", "ending MRR"),
        ("update marts.rpt_mrr_bridge set ending_customers=2", "paying customers"),
        (
            "update marts.rpt_unit_economics set marketing_spend_usd=55.01 where channel='content'",
            "spend",
        ),
        ("update marts.rpt_unit_economics set window_end='2024-03-15'", "window end"),
    ],
)
def test_cli_fails_on_an_omitted_month_or_incorrect_measure(
    source_and_warehouse: tuple[Path, Path],
    change: str,
    metric: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw, database = source_and_warehouse
    with duckdb.connect(str(database)) as connection:
        connection.execute(change)
    assert main(["--raw-dir", str(raw), "--database", str(database), "--lookback-months", "1"]) == 1
    error = capsys.readouterr().err
    assert metric in error and "raw CSVs give" in error and "warehouse gives" in error
