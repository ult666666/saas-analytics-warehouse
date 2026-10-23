"""Command-line entry point: ``uv run saasgen --help``."""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from saasgen.config import COMPANY_NAME, GeneratorConfig
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
