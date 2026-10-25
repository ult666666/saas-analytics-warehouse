"""Consumer-visible churn investigations over real, hand-built DuckDB marts."""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from saasreport.churn import build_investigation, main


@pytest.fixture
def churn_db(tmp_path: Path) -> Path:
    database = tmp_path / "warehouse.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("""
            create schema marts;
            create table marts.rpt_mrr_bridge (
                month_start date, churned_mrr_usd decimal(18, 2),
                involuntary_churned_mrr_usd decimal(18, 2), churned_customers integer
            );
            create table marts.dim_customers (
                customer_id varchar, acquisition_channel varchar, is_active boolean
            );
            create table marts.fct_mrr_movements (
                customer_id varchar, month_start date, movement_type varchar,
                previous_mrr_usd decimal(18, 2), mrr_usd decimal(18, 2),
                mrr_change_usd decimal(18, 2), churn_reason varchar
            );
            insert into marts.rpt_mrr_bridge values
                ('2024-03-01', -155.50, -101.40, 3), ('2024-04-01', 0, 0, 0);
            insert into marts.dim_customers values
                ('cus_a', 'paid_search', true), ('cus_b', 'organic', false),
                ('cus_c', 'partner', false), ('cus_d', 'content', true);
            insert into marts.fct_mrr_movements values
                ('cus_c', '2024-03-01', 'churn', 0.15, 0, -0.15, 'payment_failed'),
                ('cus_a', '2024-03-01', 'churn', 101.25, 0, -101.25, 'payment_failed'),
                ('cus_b', '2024-03-01', 'churn', 54.10, 0, -54.10, 'voluntary'),
                ('cus_d', '2024-03-01', 'contraction', 20, 18, -2, null),
                ('cus_b', '2024-02-01', 'churn', 70, 0, -70, 'payment_failed'),
                ('cus_a', '2024-04-01', 'reactivation', 0, 120, 120, null);
        """)
    return database


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def test_exact_customer_losses_groups_and_subset_use_historical_month(
    churn_db: Path, tmp_path: Path
) -> None:
    # A latest-active filter, contraction inclusion, float summation, wrong sign or
    # a missing month predicate would break these hand-derived observable exports.
    original = churn_db.read_bytes()
    output = tmp_path / "investigation"
    written = build_investigation(churn_db, "2024-03", output)
    assert sorted(p.name for p in written) == [
        "churned-customers.csv",
        "investigation.md",
        "losses-by-channel-and-reason.csv",
        "payment-failures.csv",
    ]
    assert read_csv(output / "churned-customers.csv") == [
        {
            "month_start": "2024-03-01",
            "customer_id": "cus_a",
            "acquisition_channel": "paid_search",
            "churn_reason": "payment_failed",
            "lost_mrr_usd": "101.25",
        },
        {
            "month_start": "2024-03-01",
            "customer_id": "cus_b",
            "acquisition_channel": "organic",
            "churn_reason": "voluntary",
            "lost_mrr_usd": "54.10",
        },
        {
            "month_start": "2024-03-01",
            "customer_id": "cus_c",
            "acquisition_channel": "partner",
            "churn_reason": "payment_failed",
            "lost_mrr_usd": "0.15",
        },
    ]
    assert [r["customer_id"] for r in read_csv(output / "payment-failures.csv")] == [
        "cus_a",
        "cus_c",
    ]
    assert read_csv(output / "losses-by-channel-and-reason.csv") == [
        {
            "month_start": "2024-03-01",
            "acquisition_channel": "organic",
            "churn_reason": "voluntary",
            "customers": "1",
            "lost_mrr_usd": "54.10",
        },
        {
            "month_start": "2024-03-01",
            "acquisition_channel": "paid_search",
            "churn_reason": "payment_failed",
            "customers": "1",
            "lost_mrr_usd": "101.25",
        },
        {
            "month_start": "2024-03-01",
            "acquisition_channel": "partner",
            "churn_reason": "payment_failed",
            "customers": "1",
            "lost_mrr_usd": "0.15",
        },
    ]
    report = (output / "investigation.md").read_text()
    assert "2024-03" in report and "$155.50" in report and "-$155.50" in report
    assert "$101.40" in report and "65.21%" in report
    assert "synthetic" in report.lower() and "subset" in report.lower()
    assert "month-end" in report.lower() and "reactivat" in report.lower()
    assert "marts.fct_mrr_movements" in report and "marts.rpt_mrr_bridge" in report
    assert str(tmp_path) not in report
    assert churn_db.read_bytes() == original


def test_valid_no_churn_month_is_not_an_absent_month(churn_db: Path, tmp_path: Path) -> None:
    output = tmp_path / "empty"
    build_investigation(churn_db, "2024-04", output)
    for name in (
        "churned-customers.csv",
        "payment-failures.csv",
        "losses-by-channel-and-reason.csv",
    ):
        assert read_csv(output / name) == []
        assert "month_start" in (output / name).read_text()
    report = (output / "investigation.md").read_text()
    assert "No customers churned" in report and "$0.00" in report
    assert "n/a" in report and "100%" not in report


def test_reports_are_byte_reproducible(churn_db: Path, tmp_path: Path) -> None:
    first = build_investigation(churn_db, "2024-03", tmp_path / "first")
    second = build_investigation(churn_db, "2024-03", tmp_path / "second")
    assert {p.name: p.read_bytes() for p in first} == {p.name: p.read_bytes() for p in second}


@pytest.mark.parametrize(
    "month",
    [
        "2024-3",
        "2024-00",
        "2024-13",
        "0000-01",
        "2024-03-01",
        " 2024-03",
        "2024-03 ",
        "2024-03' OR 1=1 --",
    ],
)
def test_malformed_month_creates_no_output(churn_db: Path, tmp_path: Path, month: str) -> None:
    output = tmp_path / "invalid"
    with pytest.raises(ValueError, match="YYYY-MM"):
        build_investigation(churn_db, month, output)
    assert not output.exists()


@pytest.mark.parametrize("month", ["2024-02", "2024-05", "9999-12"])
def test_missing_bridge_month_is_an_error(churn_db: Path, tmp_path: Path, month: str) -> None:
    output = tmp_path / "missing-month"
    with pytest.raises(ValueError, match="bridge"):
        build_investigation(churn_db, month, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "statement",
    [
        "update marts.rpt_mrr_bridge set churned_mrr_usd=-155.51 where month_start='2024-03-01'",
        "update marts.rpt_mrr_bridge set involuntary_churned_mrr_usd=-101.41 "
        "where month_start='2024-03-01'",
        "update marts.rpt_mrr_bridge set churned_customers=2 where month_start='2024-03-01'",
    ],
)
def test_cent_subset_and_count_mismatches_refuse_publication(
    churn_db: Path, tmp_path: Path, statement: str
) -> None:
    with duckdb.connect(str(churn_db)) as connection:
        connection.execute(statement)
    output = tmp_path / "mismatch"
    with pytest.raises(ValueError, match="reconcil"):
        build_investigation(churn_db, "2024-03", output)
    assert not output.exists()


@pytest.mark.parametrize(
    "statement,reason",
    [
        ("delete from marts.dim_customers where customer_id='cus_c'", "customer|channel"),
        ("insert into marts.dim_customers values ('cus_c','partner',false)", "duplicate"),
        (
            "insert into marts.fct_mrr_movements select * from marts.fct_mrr_movements "
            "where customer_id='cus_c'",
            "duplicate",
        ),
        (
            "insert into marts.rpt_mrr_bridge select * from marts.rpt_mrr_bridge "
            "where month_start='2024-03-01'",
            "bridge",
        ),
        (
            "update marts.fct_mrr_movements set churn_reason=null where customer_id='cus_c'",
            "reason",
        ),
        (
            "update marts.fct_mrr_movements set churn_reason='other' where customer_id='cus_c'",
            "reason",
        ),
        (
            "update marts.dim_customers set acquisition_channel='unknown' "
            "where customer_id='cus_c'",
            "channel",
        ),
        ("update marts.fct_mrr_movements set mrr_usd=1 where customer_id='cus_c'", "churn"),
        (
            "update marts.fct_mrr_movements set previous_mrr_usd=1 where customer_id='cus_c'",
            "churn",
        ),
        (
            "update marts.rpt_mrr_bridge set churned_mrr_usd=1 where month_start='2024-03-01'",
            "negative|non-positive|loss",
        ),
    ],
)
def test_broken_source_grains_or_churn_contract_fail_before_writes(
    churn_db: Path, tmp_path: Path, statement: str, reason: str
) -> None:
    with duckdb.connect(str(churn_db)) as connection:
        connection.execute(statement)
    output = tmp_path / "bad-source"
    with pytest.raises(ValueError, match=reason):
        build_investigation(churn_db, "2024-03", output)
    assert not output.exists()


@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "database"])
def test_existing_destinations_remain_unchanged(churn_db: Path, tmp_path: Path, kind: str) -> None:
    output = tmp_path / "existing"
    if kind == "directory":
        output.mkdir()
        (output / "keep.txt").write_text("retain this")
    elif kind == "file":
        output.write_text("retain this")
    elif kind == "symlink":
        output.symlink_to(tmp_path / "absent", target_is_directory=True)
    else:
        output = churn_db
    original_db = churn_db.read_bytes()
    with pytest.raises(FileExistsError):
        build_investigation(churn_db, "2024-03", output)
    assert churn_db.read_bytes() == original_db
    if kind == "directory":
        assert sorted(p.name for p in output.iterdir()) == ["keep.txt"]
        assert (output / "keep.txt").read_text() == "retain this"
    elif kind == "file":
        assert output.read_text() == "retain this"
    elif kind == "symlink":
        assert output.is_symlink() and not (tmp_path / "absent").exists()


def test_sub_cent_or_floating_money_is_not_silently_rounded(churn_db: Path, tmp_path: Path) -> None:
    with duckdb.connect(str(churn_db)) as connection:
        connection.execute(
            "alter table marts.fct_mrr_movements alter mrr_change_usd type decimal(18,3)"
        )
        connection.execute(
            "update marts.fct_mrr_movements set mrr_change_usd=-0.151 where customer_id='cus_c'"
        )
    with pytest.raises(ValueError, match="cent"):
        build_investigation(churn_db, "2024-03", tmp_path / "subcent")
    with duckdb.connect(str(churn_db)) as connection:
        connection.execute("alter table marts.fct_mrr_movements alter mrr_change_usd type double")
    with pytest.raises(ValueError, match=r"Decimal|decimal"):
        build_investigation(churn_db, "2024-03", tmp_path / "float")


def test_documented_module_runs_as_a_real_process(churn_db: Path, tmp_path: Path) -> None:
    output = tmp_path / "cli"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "saasreport.churn",
            "--database",
            str(churn_db),
            "--month",
            "2024-03",
            "--output-dir",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("wrote ") == 4
    assert read_csv(output / "payment-failures.csv")[0]["lost_mrr_usd"] == "101.25"
    repeated = subprocess.run(
        [
            sys.executable,
            "-m",
            "saasreport.churn",
            "--database",
            str(churn_db),
            "--month",
            "2024-03",
            "--output-dir",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert repeated.returncode == 2 and "Traceback" not in repeated.stderr


def test_missing_database_and_bad_month_are_controlled_usage_errors(
    tmp_path: Path, churn_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.duckdb"
    for database, month in [(missing, "2024-03"), (churn_db, "2024-3")]:
        with pytest.raises(SystemExit) as error:
            main(
                [
                    "--database",
                    str(database),
                    "--month",
                    month,
                    "--output-dir",
                    str(tmp_path / "out"),
                ]
            )
        assert error.value.code == 2
        assert "Traceback" not in capsys.readouterr().err
    assert not missing.exists() and not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "table,column,type_sql,conversion",
    [
        ("dim_customers", "acquisition_channel", "varchar[]", "[acquisition_channel]"),
        (
            "dim_customers",
            "acquisition_channel",
            "struct(value varchar)",
            "{'value': acquisition_channel}",
        ),
        ("fct_mrr_movements", "churn_reason", "varchar[]", "[churn_reason]"),
        ("fct_mrr_movements", "churn_reason", "struct(value varchar)", "{'value': churn_reason}"),
    ],
)
def test_collection_shaped_category_drift_is_a_controlled_data_error(
    churn_db: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    table: str,
    column: str,
    type_sql: str,
    conversion: str,
) -> None:
    # Actual LIST/STRUCT values used to escape the CLI as an unhashable TypeError.
    with duckdb.connect(str(churn_db)) as connection:
        connection.execute(
            f"alter table marts.{table} alter {column} type {type_sql} using {conversion}"
        )
    output = tmp_path / "schema-drift"
    with pytest.raises(SystemExit) as error:
        main(["--database", str(churn_db), "--month", "2024-03", "--output-dir", str(output)])
    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err
    assert not output.exists()
