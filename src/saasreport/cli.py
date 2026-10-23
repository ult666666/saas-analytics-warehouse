"""Command-line entry point: ``uv run saasreport --help``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import duckdb

from saasreport.charts import (
    plot_cac_payback,
    plot_cohort_retention,
    plot_funnel,
    plot_mrr_bridge,
    plot_mrr_trend,
)
from saasreport.data import load_report_data
from saasreport.markdown import render_markdown


def build_report(database: Path, output_dir: Path) -> list[Path]:
    """Query the marts, draw every chart and write report.md. Returns the written files."""
    with duckdb.connect(str(database), read_only=True) as connection:
        data = load_report_data(connection)
    figures = output_dir / "figures"
    written = [
        plot_mrr_trend(data, figures / "mrr_trend.png"),
        plot_mrr_bridge(data, figures / "mrr_bridge.png"),
        plot_cohort_retention(data, figures / "cohort_retention.png"),
        plot_cac_payback(data, figures / "cac_payback.png"),
        plot_funnel(data, figures / "funnel.png"),
    ]
    report = output_dir / "report.md"
    report.write_text(render_markdown(data), encoding="utf-8")
    return [*written, report]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="saasreport",
        description="Write charts and a markdown report from the dbt marts in DuckDB.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/warehouse.duckdb"),
        help="DuckDB file built by dbt (%(default)s)",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("reports"), help="output directory (%(default)s)"
    )
    args = parser.parse_args(argv)
    if not args.database.exists():
        parser.error(f"{args.database} does not exist: run 'make build' first")
    for path in build_report(args.database, args.output_dir):
        print(f"wrote {path}")
    return 0
