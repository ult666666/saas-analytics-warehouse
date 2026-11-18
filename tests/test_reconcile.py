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
        "event_id,customer_id,event_type,effective_date,occurred_at,plan_price_id,seats,cancel_reason\n"
        "3,b,new,2024-02-29,2024-02-29,monthly,2,\n"
        "1,a,new,2024-01-31,2024-01-31,annual,3,\n"
        "2,a,cancel,2024-02-29,2024-02-24,,,payment_failed\n"
        "4,c,new,2024-03-12,2024-03-12,monthly,1,\n"
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
            create table marts.rpt_mrr_bridge (
                month_start date, starting_mrr_usd decimal(18,2), new_mrr_usd decimal(18,2),
                expansion_mrr_usd decimal(18,2), reactivation_mrr_usd decimal(18,2),
                contraction_mrr_usd decimal(18,2), churned_mrr_usd decimal(18,2),
                involuntary_churned_mrr_usd decimal(18,2), net_new_mrr_usd decimal(18,2),
                ending_mrr_usd decimal(18,2), starting_customers int, new_customers int,
                reactivated_customers int, churned_customers int, ending_customers int
            );
            insert into marts.rpt_mrr_bridge values
                ('2024-01-01', 0,    3.03, 0, 0, 0, 0,     0,      3.03,  3.03, 0, 1, 0, 0, 1),
                ('2024-02-01', 3.03, 20,   0, 0, 0, -3.03, -3.03, 16.97, 20,   1, 1, 0, 1, 1);
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
    assert "0 monthly MRR bridge rows and 6 channel spend rows" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("change", "metric"),
    [
        ("delete from marts.rpt_mrr_bridge where month_start='2024-02-01'", "month_start"),
        ("update marts.rpt_mrr_bridge set ending_customers=2", "ending_customers"),
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


@pytest.mark.parametrize(
    ("table", "contents", "message"),
    [
        ("marketing_spend", "", "missing columns"),
        ("marketing_spend", "unrelated\n", "missing columns"),
        ("marketing_spend", "spend_date,channel,spend_cents\n", "no spend dates"),
        ("plans", "plan_price_id\n", "missing columns"),
        ("subscription_events", "", "missing columns"),
        (
            "subscription_events",
            "event_id,customer_id,event_type,effective_date,occurred_at,plan_price_id,seats,cancel_reason\n"
            "1,a,new,2024-01-31,2024-01-10,monthly\n",
            "line 2",
        ),
    ],
)
def test_cli_names_incomplete_sources(
    source_and_warehouse: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    table: str,
    contents: str,
    message: str,
) -> None:
    raw, database = source_and_warehouse
    (raw / f"{table}.csv").write_text(contents)
    assert main(["--raw-dir", str(raw), "--database", str(database)]) == 1
    error = capsys.readouterr().err
    assert f"{table}.csv" in error and message in error


@pytest.mark.parametrize("field", ["effective_date", "occurred_at"])
def test_rejects_invalid_event_dates_even_after_reporting_cutoff(
    source_and_warehouse: tuple[Path, Path], capsys: pytest.CaptureFixture[str], field: str
) -> None:
    raw, database = source_and_warehouse
    values = {"effective_date": "2024-03-31", "occurred_at": "2024-03-15"}
    values[field] = "invalid"
    with (raw / "subscription_events.csv").open("a") as stream:
        stream.write(
            f"bad,a,cancel,{values['effective_date']},{values['occurred_at']},,,voluntary\n"
        )
    assert main(["--raw-dir", str(raw), "--database", str(database), "--lookback-months", "1"]) == 1
    assert field in capsys.readouterr().err


def test_same_day_events_are_ordered_by_timestamp_then_event_id(
    source_and_warehouse: tuple[Path, Path],
) -> None:
    raw, database = source_and_warehouse
    with (raw / "subscription_events.csv").open("a") as stream:
        stream.write(
            "tie3,b,upgrade,2024-02-29,2024-02-29 17:00:00,monthly,2,\n"
            "tie2,b,upgrade,2024-02-29,2024-02-29T17:00:00,monthly,5,\n"
            "tie1,b,upgrade,2024-02-29,2024-02-29T08:30:00,monthly,4,\n"
        )
    assert reconcile(raw, database, lookback_months=1) == (2, 6)


def test_complete_months_can_have_zero_subscriptions(
    source_and_warehouse: tuple[Path, Path],
) -> None:
    raw, database = source_and_warehouse
    events = raw / "subscription_events.csv"
    events.write_text(events.read_text().splitlines()[0] + "\n")
    with duckdb.connect(str(database)) as connection:
        connection.execute("delete from marts.rpt_mrr_bridge")
        connection.execute(
            "insert into marts.rpt_mrr_bridge values "
            "('2024-01-01', 0,0,0,0,0,0,0,0,0,0,0,0,0,0), "
            "('2024-02-01', 0,0,0,0,0,0,0,0,0,0,0,0,0,0)"
        )
    assert reconcile(raw, database, lookback_months=1) == (2, 6)


def test_new_sales_cannot_be_relabelled_as_reactivations(
    source_and_warehouse: tuple[Path, Path],
) -> None:
    raw, database = source_and_warehouse
    with duckdb.connect(str(database)) as connection:
        # Both dollar and customer bridges still roll forward to the right closing totals.
        connection.execute(
            """update marts.rpt_mrr_bridge set
                   reactivation_mrr_usd = new_mrr_usd, new_mrr_usd = 0,
                   reactivated_customers = new_customers, new_customers = 0
               where month_start = '2024-02-01'"""
        )
    with pytest.raises(ValueError, match=r"2024-02-01.*new_mrr_usd.*20.00.*0.00"):
        reconcile(raw, database, lookback_months=1)


@pytest.mark.parametrize(
    "column",
    [
        "starting_mrr_usd",
        "new_mrr_usd",
        "expansion_mrr_usd",
        "reactivation_mrr_usd",
        "contraction_mrr_usd",
        "churned_mrr_usd",
        "involuntary_churned_mrr_usd",
        "net_new_mrr_usd",
        "ending_mrr_usd",
        "starting_customers",
        "new_customers",
        "reactivated_customers",
        "churned_customers",
        "ending_customers",
    ],
)
def test_identifies_the_month_and_field_for_each_dollar_and_customer_total(
    source_and_warehouse: tuple[Path, Path], column: str
) -> None:
    raw, database = source_and_warehouse
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            f"update marts.rpt_mrr_bridge set {column}={column}+1 where month_start='2024-02-01'"
        )
    with pytest.raises(ValueError, match=rf"2024-02-01 {column} mismatch:"):
        reconcile(raw, database, lookback_months=1)


def test_classifies_month_end_changes_from_the_first_complete_month(
    source_and_warehouse: tuple[Path, Path],
) -> None:
    raw, database = source_and_warehouse
    # January is partial. A and B were already paying before it, C paid only during January,
    # and D starts in February. February opens at zero and A, B and D are new at its close.
    # In March A contracts, B expands and C first appears at a published close. D cancels
    # and returns before its final cancellation. Tied cancellations use event ID for the reason.
    # April brings D back, while A's brief cancel/return leaves its month-end amount unchanged.
    events = [
        ("a1", "a", "new", "2023-12-01", "monthly", "2", ""),
        ("b1", "b", "new", "2023-12-15", "monthly", "1", ""),
        ("c1", "c", "new", "2024-01-11", "monthly", "1", ""),
        ("c2", "c", "cancel", "2024-01-29", "", "", "voluntary"),
        ("d1", "d", "new", "2024-02-15", "monthly", "1", ""),
        ("a2", "a", "downgrade", "2024-03-01", "monthly", "1", ""),
        ("b2", "b", "upgrade", "2024-03-05", "monthly", "3", ""),
        ("c3", "c", "reactivate", "2024-03-10", "monthly", "2", ""),
        ("d2", "d", "cancel", "2024-03-20", "", "", "voluntary"),
        ("d3", "d", "reactivate", "2024-03-25", "monthly", "1", ""),
        ("d4a", "d", "cancel", "2024-03-31", "", "", "voluntary"),
        ("d4b", "d", "cancel", "2024-03-31", "", "", "payment_failed"),
        ("d5", "d", "reactivate", "2024-04-01", "monthly", "1", ""),
        ("a3", "a", "cancel", "2024-04-12", "", "", "payment_failed"),
        ("a4", "a", "reactivate", "2024-04-15", "monthly", "1", ""),
        ("c4", "c", "cancel", "2024-04-22", "", "", "voluntary"),
    ]
    with (raw / "subscription_events.csv").open("w") as stream:
        stream.write(
            "event_id,customer_id,event_type,effective_date,occurred_at,plan_price_id,seats,cancel_reason\n"
        )
        for event_id, customer, kind, day, price, seats, reason in reversed(events):
            stream.write(f"{event_id},{customer},{kind},{day},{day},{price},{seats},{reason}\n")
    (raw / "marketing_spend.csv").write_text(
        "spend_date,channel,spend_cents\n2024-01-15,organic,0\n2024-04-30,organic,0\n"
    )
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            delete from marts.rpt_mrr_bridge;
            insert into marts.rpt_mrr_bridge values
                ('2024-02-01', 0,  40, 0,  0,  0,   0,   0,    40, 40, 0, 3, 0, 0, 3),
                ('2024-03-01', 40, 20, 20, 0, -10, -10, -10,   20, 60, 3, 1, 0, 1, 3),
                ('2024-04-01', 60, 0,  0,  10, 0,  -20,  0,   -10, 50, 3, 0, 1, 1, 3);
            update marts.rpt_unit_economics set
                window_start='2024-04-01', window_end='2024-04-30', marketing_spend_usd=0;
            """
        )
    assert reconcile(raw, database, lookback_months=1) == (3, 6)
