"""Command-line entry point: ``uv run saasgen --help``."""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from saasgen.batches import daily_batches, write_batches
from saasgen.config import (
    COMPANY_NAME,
    LATE_ARRIVAL_SHARE,
    MAX_ARRIVAL_DELAY_DAYS,
    GeneratorConfig,
)
from saasgen.generator import generate
from saasgen.writer import write_dataset

DEFAULTS = GeneratorConfig()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="saasgen",
        description=f"Generate synthetic raw data for {COMPANY_NAME}, a fictional SaaS company.",
    )
    parser.add_argument("--seed", type=int, default=DEFAULTS.seed, help="random seed (%(default)s)")
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=DEFAULTS.start_date,
        help="first simulated day, must be the 1st of a month (%(default)s)",
    )
    parser.add_argument(
        "--months", type=int, default=DEFAULTS.months, help="months to simulate (%(default)s)"
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=DEFAULTS.scale,
        help="multiplier for marketing spend and organic signups (%(default)s)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("data/raw"), help="output directory (%(default)s)"
    )
    batches = parser.add_argument_group(
        "daily batches", "write the same data as the daily batches a warehouse would load"
    )
    batches.add_argument(
        "--daily-batches",
        type=Path,
        metavar="DIR",
        help="write DIR/<YYYY-MM-DD>/<table>.csv instead of one file per table",
    )
    batches.add_argument(
        "--late-share",
        type=float,
        default=LATE_ARRIVAL_SHARE,
        help="share of rows that arrive late (%(default)s)",
    )
    batches.add_argument(
        "--max-delay-days",
        type=int,
        default=MAX_ARRIVAL_DELAY_DAYS,
        help="most days a late row can be late by (%(default)s)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = GeneratorConfig(
            seed=args.seed, start_date=args.start, months=args.months, scale=args.scale
        )
    except ValueError as error:
        parser.error(str(error))

    started = time.perf_counter()
    if args.daily_batches is not None:
        try:
            batches = daily_batches(
                generate(config), late_share=args.late_share, max_delay_days=args.max_delay_days
            )
        except ValueError as error:
            parser.error(str(error))
        rows_per_day = write_batches(batches, args.daily_batches)
        late = sum(arrival.arrives_on > arrival.known_on for arrival in batches.arrivals)
        print(
            f"Wrote {len(rows_per_day)} daily batches of synthetic {COMPANY_NAME} data to "
            f"{args.daily_batches} in {time.perf_counter() - started:.1f}s "
            f"(seed={config.seed}, scale={config.scale:g}, {config.start_date} to "
            f"{config.end_date}): {len(batches.arrivals):,} rows, {late:,} of them late"
        )
        return 0
    row_counts = write_dataset(generate(config), args.out)
    elapsed = time.perf_counter() - started

    print(
        f"Generated synthetic {COMPANY_NAME} data in {elapsed:.1f}s "
        f"(seed={config.seed}, scale={config.scale:g}, "
        f"{config.start_date} to {config.end_date})"
    )
    for table, count in row_counts.items():
        print(f"  {table:<20} {count:>9,} rows")
    print(f"Wrote {len(row_counts)} CSV files to {args.out}")
    return 0
