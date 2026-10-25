"""Read-only, exact-cent customer investigation of one synthetic month-end churn bridge."""

from __future__ import annotations

import argparse
import csv
import io
import re
from collections import defaultdict
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

import duckdb

CHANNELS = frozenset({"paid_search", "paid_social", "content", "partner", "organic"})
REASONS = frozenset({"voluntary", "payment_failed"})


@dataclass(frozen=True)
class _Customer:
    customer_id: str
    channel: str
    reason: str
    loss_cents: int


@dataclass(frozen=True)
class _Investigation:
    month: date
    customers: tuple[_Customer, ...]
    loss_cents: int
    payment_loss_cents: int


def _month(value: str) -> date:
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value):
        raise ValueError("month must be a valid YYYY-MM")
    try:
        return date.fromisoformat(value + "-01")
    except ValueError as error:
        raise ValueError("month must be a valid YYYY-MM") from error


def _cents(value: object, label: str) -> int:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{label} must be finite native Decimal money")
    # DuckDB decimals have at most 38 digits. Convert without binary floats or
    # ambient Decimal precision rounding; Python integer sums then stay exact.
    with localcontext() as context:
        context.prec = 50
        cents = value * 100
        if cents != cents.to_integral_value():
            raise ValueError(f"{label} must be exact cents, not sub-cent money")
        return int(cents)


def _bridge_loss(value: object, label: str) -> int:
    cents = _cents(value, label)
    if cents > 0:
        raise ValueError(f"{label} must be a non-positive signed loss")
    return -cents


def _load(connection: duckdb.DuckDBPyConnection, month: date) -> _Investigation:
    bridge = connection.execute(
        """select churned_mrr_usd, involuntary_churned_mrr_usd, churned_customers
           from marts.rpt_mrr_bridge where month_start = ?""",
        [month],
    ).fetchall()
    if len(bridge) != 1:
        raise ValueError("selected month must have exactly one bridge row; run 'make build'")
    loss = _bridge_loss(bridge[0][0], "bridge churn")
    payment_loss = _bridge_loss(bridge[0][1], "bridge payment-failure churn")
    count = bridge[0][2]
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("bridge churned customer count must be a non-negative integer")
    rows = connection.execute(
        """select movements.customer_id, movements.previous_mrr_usd, movements.mrr_usd,
                  movements.mrr_change_usd, movements.churn_reason, customers.acquisition_channel
           from marts.fct_mrr_movements as movements
           left join marts.dim_customers as customers
             on movements.customer_id = customers.customer_id
           where movements.month_start = ? and movements.movement_type = 'churn'
           order by movements.customer_id, customers.acquisition_channel""",
        [month],
    ).fetchall()
    customers: list[_Customer] = []
    seen: set[str] = set()
    for customer_id, previous, current, change, reason, channel in rows:
        if (
            not isinstance(customer_id, str)
            or not customer_id.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in customer_id)
        ):
            raise ValueError("churn customer ID must be non-empty text without control characters")
        if customer_id in seen:
            raise ValueError("duplicate churn customer or customer-dimension join")
        seen.add(customer_id)
        if channel not in CHANNELS:
            raise ValueError("churn customer must have one supported acquisition channel")
        if reason not in REASONS:
            raise ValueError("churn reason must be voluntary or payment_failed")
        prior_cents = _cents(previous, "previous churn MRR")
        current_cents = _cents(current, "current churn MRR")
        change_cents = _cents(change, "churn change")
        if prior_cents <= 0 or current_cents != 0 or change_cents != -prior_cents:
            raise ValueError("churn must move positive previous MRR to zero with its exact loss")
        customers.append(_Customer(customer_id, channel, reason, -change_cents))
    actual_loss = sum(customer.loss_cents for customer in customers)
    actual_payment = sum(
        customer.loss_cents for customer in customers if customer.reason == "payment_failed"
    )
    if (len(customers), actual_loss, actual_payment) != (count, loss, payment_loss):
        raise ValueError(
            "customer count, total loss and payment-failure subset must reconcile to bridge"
        )
    return _Investigation(month, tuple(customers), loss, payment_loss)


def _amount(cents: int) -> str:
    whole, fraction = divmod(cents, 100)
    return f"{whole}.{fraction:02d}"


def _usd(cents: int) -> str:
    whole, fraction = divmod(abs(cents), 100)
    return f"{'-' if cents < 0 else ''}${whole:,}.{fraction:02d}"


def _csv(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue()


def _render(data: _Investigation) -> dict[str, str]:
    month = data.month.isoformat()
    customers = [
        [month, c.customer_id, c.channel, c.reason, _amount(c.loss_cents)] for c in data.customers
    ]
    payment_customers = [row for row in customers if row[3] == "payment_failed"]
    groups: dict[tuple[str, str], list[_Customer]] = defaultdict(list)
    for customer in data.customers:
        groups[(customer.channel, customer.reason)].append(customer)
    grouped = [
        [month, channel, reason, len(members), _amount(sum(c.loss_cents for c in members))]
        for (channel, reason), members in sorted(groups.items())
    ]
    with localcontext() as context:
        context.prec = 50
        share = (
            f"{Decimal(data.payment_loss_cents) * 100 / Decimal(data.loss_cents):.2f}%"
            if data.loss_cents
            else "n/a (no churned MRR)"
        )
    markdown = [
        f"# Churn investigation — {data.month:%Y-%m}",
        "",
        "**All data is synthetic.** Tallyloom is a fictional SaaS company.",
        "",
        "## Reconciliation",
        "",
        "| Measure | Value |",
        "| --- | ---: |",
        f"| Churned customers (movement rows = bridge count) | {len(customers)} |",
        f"| Lost MRR (customer sum = inverse of signed bridge churn) | {_usd(data.loss_cents)} |",
        f"| Signed bridge churned_mrr_usd | {_usd(-data.loss_cents)} |",
        f"| Payment-failure customers | {len(payment_customers)} |",
        f"| Payment-failure loss (subset = inverse of bridge) | {_usd(data.payment_loss_cents)} |",
        f"| Payment-failure share of churned MRR | {share} |",
        "",
        "Payment-failure churn is a **subset** of total churn, not an additional loss.",
        "All three checks (customer count, total cents, payment-failure cents) reconcile exactly.",
        "",
        "## Channel and reason",
        "",
        "| Acquisition channel | Churn reason | Customers | Lost MRR (USD) |",
        "| --- | --- | ---: | ---: |",
    ]
    markdown.extend(
        f"| {channel} | {reason} | {len(members)} | {_usd(sum(c.loss_cents for c in members))} |"
        for (channel, reason), members in sorted(groups.items())
    )
    if not customers:
        markdown.extend(["", "No customers churned in this month."])
    markdown.extend(
        [
            "",
            "## Inspect the records",
            "",
            "- [All churned customers](churned-customers.csv): historical customer-month records.",
            "- [Payment failures](payment-failures.csv): the payment_failed subset.",
            "- [Channel/reason totals](losses-by-channel-and-reason.csv): exclusive groups.",
            "",
            "Sources: `marts.rpt_mrr_bridge`, `marts.fct_mrr_movements`, `marts.dim_customers`.",
            "One read-only transaction; native Decimal money converted to integer cents.",
            "",
            "## Interpretation",
            "",
            "Month-end MRR transitions do not measure charge failures or recoverable cash.",
            "A within-month cancellation and reactivation that leaves MRR unchanged is absent.",
            "Customers reactivated later remain in their historical churn month.",
            "Current active status is not used. Channels represent first-touch acquisition.",
            "Reasons come from the classified cancellation event.",
            "IDs are fictional; this workflow does not contact customers or estimate recovery.",
            "",
        ]
    )
    headers = ["month_start", "customer_id", "acquisition_channel", "churn_reason", "lost_mrr_usd"]
    return {
        "churned-customers.csv": _csv(headers, customers),
        "payment-failures.csv": _csv(headers, payment_customers),
        "losses-by-channel-and-reason.csv": _csv(
            ["month_start", "acquisition_channel", "churn_reason", "customers", "lost_mrr_usd"],
            grouped,
        ),
        "investigation.md": "\n".join(markdown),
    }


def build_investigation(database: Path, month: str, output_dir: Path) -> list[Path]:
    """Validate one monthly bridge, then write four files to an exclusively new directory."""
    selected = _month(month)
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"output destination already exists: {output_dir}")
    if not database.is_file():
        raise ValueError("warehouse does not exist: run 'make build' first")
    with duckdb.connect(str(database), read_only=True) as connection:
        connection.execute("begin transaction")
        data = _load(connection, selected)
        connection.execute("commit")
    contents = _render(data)
    output_dir.mkdir(parents=True, exist_ok=False)
    written: list[Path] = []
    try:
        for name, content in contents.items():
            path = output_dir / name
            with path.open("x", encoding="utf-8", newline="") as target:
                written.append(path)
                target.write(content)
    except OSError:
        for path in written:
            with suppress(OSError):
                path.unlink()
        with suppress(OSError):
            output_dir.rmdir()
        raise
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/warehouse.duckdb"))
    parser.add_argument("--month", required=True, help="historical bridge month, YYYY-MM")
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="new directory; never replaced"
    )
    args = parser.parse_args(argv)
    try:
        written = build_investigation(args.database, args.month, args.output_dir)
    except (ValueError, OSError, duckdb.Error) as error:
        parser.exit(2, f"error: {error}\n")
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
