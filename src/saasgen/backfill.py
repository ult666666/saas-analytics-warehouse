"""Load the synthetic data day by day, build incrementally, and prove it equals a full refresh.

Usage: ``uv run python -m saasgen.backfill --help`` (``make incremental-check``).

1. Generate the seeded dataset and split it into daily batches (``saasgen.batches``).
2. Land every batch before the daily phase at once, as an initial load, and build.
3. For each remaining day, append that day's batch to the landing files and run
   ``dbt build`` without the data tests: seeds, models (the incremental staging
   models process only their lookback window), the snapshot and the unit tests.
   Data tests wait for the end because, mid-load, a late row can refer to a row
   that has not arrived yet.
4. Run every test on the incrementally built warehouse.
5. Build a second warehouse from the same landing files with ``--full-refresh``.
6. Compare every model and seed, and the snapshot's current versions, row by row:
   an order-independent digest of row hashes per relation, and the differing
   rows when a digest does not match.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb

from saasgen.batches import daily_batches, write_batches
from saasgen.config import LATE_ARRIVAL_SHARE, MAX_ARRIVAL_DELAY_DAYS, GeneratorConfig
from saasgen.generator import generate

DBT_DIR = Path(__file__).resolve().parents[2] / "dbt"
COMPARED_SCHEMAS = ("staging", "intermediate", "marts", "seeds")
SNAPSHOT = ("snapshots", "snp_subscription_state")
MARKER = ".saasgen-backfill"


@dataclass(frozen=True)
class DbtRun:
    wall_seconds: float
    """Including starting dbt and parsing the project."""
    dbt_seconds: float
    """dbt's own ``elapsed_time`` for running the selected nodes (run_results.json)."""
    failures: tuple[str, ...] = ()
    """Nodes that failed or errored."""


RunDbt = Callable[[Sequence[str], Mapping[str, str]], DbtRun]
"""Runs one dbt command with extra environment variables."""


class BackfillError(RuntimeError):
    """A dbt command failed or the two warehouses differ."""


@dataclass(frozen=True)
class RelationComparison:
    relation: str
    rows: tuple[int, int]
    """Row counts in the incremental and the full-refresh warehouse."""
    only_incremental: int = 0
    only_full_refresh: int = 0
    samples: tuple[str, ...] = ()

    @property
    def equal(self) -> bool:
        return self.rows[0] == self.rows[1] and not (
            self.only_incremental or self.only_full_refresh
        )


@dataclass
class BackfillReport:
    daily_days: list[date]
    initial: DbtRun | None = None
    daily: list[DbtRun] = field(default_factory=list)
    tests: DbtRun | None = None
    full_refresh: DbtRun | None = None
    comparisons: list[RelationComparison] = field(default_factory=list)

    @property
    def equal(self) -> bool:
        tests_passed = self.tests is not None and not self.tests.failures
        return tests_passed and bool(self.comparisons) and all(c.equal for c in self.comparisons)

    def render(self) -> str:
        lines = ["Timings (dbt elapsed / wall clock including dbt start-up):"]
        for label, runs in (
            ("initial load, build without data tests", [self.initial]),
            ("daily incremental build, median of", self.daily),
            ("all tests on the incremental warehouse", [self.tests]),
            ("full refresh of the same data, with tests", [self.full_refresh]),
        ):
            measured = [run for run in runs if run is not None]
            if not measured:
                continue
            count = f" {len(measured)}" if len(measured) > 1 else ""
            dbt = statistics.median(run.dbt_seconds for run in measured)
            wall = statistics.median(run.wall_seconds for run in measured)
            lines.append(f"  {label + count:<48} {dbt:6.1f}s / {wall:6.1f}s")
        if self.tests is not None and self.tests.failures:
            lines.append(f"Tests FAILED on the incremental warehouse: {len(self.tests.failures)}")
            lines.extend(f"  {failure}" for failure in self.tests.failures)
        lines.append(f"Relations compared: {len(self.comparisons)}")
        for comparison in self.comparisons:
            verdict = "equal" if comparison.equal else "DIFFERENT"
            lines.append(f"  {verdict:<9} {comparison.relation:<45} {comparison.rows[0]:>8,} rows")
            if not comparison.equal:
                lines.append(
                    f"            only incremental: {comparison.only_incremental}, "
                    f"only full refresh: {comparison.only_full_refresh}, "
                    f"rows {comparison.rows[0]:,} vs {comparison.rows[1]:,}"
                )
                lines.extend(f"            {sample}" for sample in comparison.samples)
        lines.append(
            "Incremental build equals the full refresh."
            if self.equal
            else "Incremental build DIFFERS from the full refresh."
        )
        return "\n".join(lines)


def init_landing(landing_dir: Path, columns: Mapping[str, Sequence[str]]) -> None:
    """Create a header-only CSV per raw table, so every dbt source exists from day one."""
    landing_dir.mkdir(parents=True, exist_ok=True)
    for table, names in columns.items():
        with (landing_dir / f"{table}.csv").open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle, lineterminator="\n").writerow(names)


def land(batch_dir: Path, landing_dir: Path) -> int:
    """Append one day's batch to the landing files; returns the rows appended."""
    appended = 0
    for batch_file in sorted(batch_dir.glob("*.csv")):
        with batch_file.open(newline="", encoding="utf-8") as source:
            reader = csv.reader(source)
            next(reader)  # the header is already in the landing file
            rows = list(reader)
        with (landing_dir / batch_file.name).open("a", newline="", encoding="utf-8") as target:
            csv.writer(target, lineterminator="\n").writerows(rows)
        appended += len(rows)
    return appended


def compare_warehouses(incremental: Path, full_refresh: Path) -> list[RelationComparison]:
    """Compare every model, seed and the snapshot's current versions in two warehouses."""
    with duckdb.connect() as connection:
        for path, alias in ((incremental, "incremental"), (full_refresh, "refreshed")):
            # dbt names a DuckDB catalog after its file, and views refer to it by that
            # name, so each file is attached under its own name.
            escaped = str(path).replace("'", "''")
            connection.execute(f"attach '{escaped}' as {alias} (read_only)")
        relations = {
            catalog: _relations(connection, catalog) for catalog in ("incremental", "refreshed")
        }
        missing = relations["incremental"] ^ relations["refreshed"]
        if missing:
            raise BackfillError(f"relations in only one warehouse: {sorted(missing)}")
        return [
            _compare(connection, schema, name) for schema, name in sorted(relations["refreshed"])
        ]


def backfill(
    config: GeneratorConfig,
    work_dir: Path,
    *,
    daily_days: int,
    lookback_days: int | None = None,
    late_share: float = LATE_ARRIVAL_SHARE,
    max_delay_days: int = MAX_ARRIVAL_DELAY_DAYS,
    run_dbt: RunDbt | None = None,
    log: Callable[[str], None] = print,
) -> BackfillReport:
    """Run the whole simulation in ``work_dir`` and return what it measured and found."""
    runner = run_dbt or dbt_runner(work_dir)
    _prepare(work_dir)
    batches = daily_batches(generate(config), late_share=late_share, max_delay_days=max_delay_days)
    batch_root = work_dir / "batches"
    days = sorted(write_batches(batches, batch_root))
    if not 0 < daily_days < len(days):
        raise ValueError(f"daily_days must be between 1 and {len(days) - 1}")
    landing = work_dir / "raw"
    init_landing(landing, batches.columns)
    incremental_db = work_dir / "incremental.duckdb"
    full_refresh_db = work_dir / "refreshed.duckdb"
    extra = (
        []
        if lookback_days is None
        else ["--vars", json.dumps({"incremental_lookback_days": lookback_days})]
    )
    incremental_env = {"SAAS_RAW_DIR": str(landing), "SAAS_WAREHOUSE": str(incremental_db)}
    build_without_data_tests = ["build", "--exclude", "resource_type:test", *extra]

    initial, daily = days[: len(days) - daily_days], days[len(days) - daily_days :]
    report = BackfillReport(daily_days=daily)
    rows = sum(land(batch_root / day.isoformat(), landing) for day in initial)
    log(f"initial load: {len(initial)} days ({initial[0]} to {initial[-1]}), {rows:,} rows")
    report.initial = _succeeded(runner(build_without_data_tests, incremental_env), "initial build")
    for day in daily:
        rows = land(batch_root / day.isoformat(), landing)
        run = _succeeded(runner(build_without_data_tests, incremental_env), f"build for {day}")
        report.daily.append(run)
        log(f"{day}: {rows:,} rows landed, incremental build {run.dbt_seconds:.1f}s")
    # A failing test is a finding, not a crash: record it and still compare the warehouses.
    report.tests = runner(["test", *extra], incremental_env)
    full_refresh_env = {**incremental_env, "SAAS_WAREHOUSE": str(full_refresh_db)}
    report.full_refresh = _succeeded(
        runner(["build", "--full-refresh", *extra], full_refresh_env), "full refresh"
    )
    report.comparisons = compare_warehouses(incremental_db, full_refresh_db)
    return report


def dbt_runner(work_dir: Path) -> RunDbt:
    """Run each dbt command in its own process, with artifacts and logs inside ``work_dir``.

    A separate process per command releases the DuckDB files when it exits, so the
    comparison can open both warehouses afterwards.
    """
    dbt = Path(sys.executable).with_name("dbt")
    target = work_dir / "target"

    def run(args: Sequence[str], env: Mapping[str, str]) -> DbtRun:
        command = [
            str(dbt),
            *args,
            "--project-dir",
            str(DBT_DIR),
            "--profiles-dir",
            str(DBT_DIR),
            "--target-path",
            str(target),
            "--log-path",
            str(work_dir / "logs"),
        ]
        results_file = target / "run_results.json"
        results_file.unlink(missing_ok=True)
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=DBT_DIR,  # dbt resolves relative paths against the working directory
            env={**os.environ, **env, "DBT_SEND_ANONYMOUS_USAGE_STATS": "False"},
            capture_output=True,
            text=True,
            check=False,
        )
        wall = time.perf_counter() - started
        if not results_file.exists():
            raise BackfillError(f"dbt {' '.join(args)} did not run:\n{completed.stdout[-3000:]}")
        results = json.loads(results_file.read_text())
        failures = tuple(
            result["unique_id"]
            for result in results["results"]
            if result["status"] in {"error", "fail"}
        )
        return DbtRun(wall, float(results["elapsed_time"]), failures)

    return run


def _succeeded(run: DbtRun, step: str) -> DbtRun:
    if run.failures:
        raise BackfillError(f"{step} failed: {', '.join(run.failures)}")
    return run


def _prepare(work_dir: Path) -> None:
    """Start from an empty work directory; only ever delete one this tool created."""
    if work_dir.exists():
        if not (work_dir / MARKER).exists():
            if any(work_dir.iterdir()):
                raise BackfillError(f"{work_dir} is not empty and was not made by this tool")
        else:
            shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / MARKER).touch()


def _relations(connection: duckdb.DuckDBPyConnection, catalog: str) -> set[tuple[str, str]]:
    rows = connection.execute(
        "select table_schema, table_name from information_schema.tables "
        "where table_catalog = ? and table_schema in (?, ?, ?, ?, ?)",
        [catalog, *COMPARED_SCHEMAS, SNAPSHOT[0]],
    ).fetchall()
    return {(schema, name) for schema, name in rows}


def _compare(connection: duckdb.DuckDBPyConnection, schema: str, name: str) -> RelationComparison:
    columns = connection.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_catalog = 'refreshed' and table_schema = ? and table_name = ? "
        "order by ordinal_position",
        [schema, name],
    ).fetchall()
    # Floating-point aggregates can differ in their last bits between runs, so compare
    # them rounded. Every other value is compared exactly.
    values = ", ".join(
        f'round("{column}", 10)' if data_type in {"DOUBLE", "FLOAT", "REAL"} else f'"{column}"'
        for column, data_type in columns
    )
    # The snapshot keeps history incrementally; only its current versions have a
    # full-refresh counterpart.
    where = " where dbt_valid_to is null" if (schema, name) == SNAPSHOT else ""

    def select(catalog: str) -> str:
        return f'select {values} from {catalog}."{schema}"."{name}"{where}'

    counts = [_count(connection, select(catalog)) for catalog in ("incremental", "refreshed")]
    only = [
        connection.execute(
            f"select * from ({select(first)} except all {select(second)})"
        ).fetchall()
        for first, second in (("incremental", "refreshed"), ("refreshed", "incremental"))
    ]
    samples = tuple(
        f"{side}: {row}"
        for side, rows in zip(("incremental", "full refresh"), only, strict=True)
        for row in rows[:3]
    )
    return RelationComparison(
        relation=f"{schema}.{name}",
        rows=(counts[0], counts[1]),
        only_incremental=len(only[0]),
        only_full_refresh=len(only[1]),
        samples=samples,
    )


def _count(connection: duckdb.DuckDBPyConnection, query: str) -> int:
    row = connection.execute(f"select count(*) from ({query})").fetchone()
    assert row is not None
    return int(row[0])


def build_parser() -> argparse.ArgumentParser:
    defaults = GeneratorConfig()
    parser = argparse.ArgumentParser(
        prog="python -m saasgen.backfill",
        description="Load synthetic data day by day, build incrementally and compare with a "
        "full refresh.",
    )
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--months", type=int, default=defaults.months)
    parser.add_argument("--scale", type=float, default=defaults.scale)
    parser.add_argument(
        "--daily-days",
        type=int,
        default=31,
        help="days loaded one at a time at the end; earlier days form the initial load "
        "(%(default)s)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        help="override the incremental_lookback_days dbt variable (default: dbt_project.yml)",
    )
    parser.add_argument("--late-share", type=float, default=LATE_ARRIVAL_SHARE)
    parser.add_argument("--max-delay-days", type=int, default=MAX_ARRIVAL_DELAY_DAYS)
    parser.add_argument("--work-dir", type=Path, default=Path("build/backfill"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = GeneratorConfig(seed=args.seed, months=args.months, scale=args.scale)
    report = backfill(
        config,
        args.work_dir.resolve(),
        daily_days=args.daily_days,
        lookback_days=args.lookback_days,
        late_share=args.late_share,
        max_delay_days=args.max_delay_days,
    )
    print(report.render())
    return 0 if report.equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
