"""The report's charts. Each function draws one PNG from ``ReportData`` and returns its path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
from matplotlib.ticker import FuncFormatter, PercentFormatter

from saasreport.data import CHANNEL_LABELS, ReportData, pooled_retention
from saasreport.formatting import month_label, pct, signed_usd_compact, usd_compact
from saasreport.style import (
    DECREASE,
    INK,
    INK_MUTED,
    INK_SECONDARY,
    SEQUENTIAL_BLUE,
    SERIES_1,
    SERIES_2,
    SURFACE,
    TOTAL,
    add_titles,
    new_figure,
    save,
    style_axes,
)

PAID_CHANNELS = ("paid_search", "paid_social", "content", "partner")
MIN_COHORTS_PER_POINT = 3  # pooled retention points backed by fewer cohorts are too noisy
COMPACT_USD = FuncFormatter(lambda value, _position: usd_compact(value))


def plot_mrr_trend(data: ReportData, path: Path) -> Path:
    """Ending MRR per month: the growth story in one line."""
    figure = new_figure(9.0, 4.6)
    axes = figure.add_axes((0.08, 0.13, 0.84, 0.66))
    months = [row.month_start for row in data.bridge]
    positions = list(range(len(months)))
    mrr = [row.ending_mrr for row in data.bridge]

    axes.fill_between(positions, mrr, color=SERIES_1, alpha=0.08, linewidth=0)
    axes.plot(positions, mrr, color=SERIES_1, linewidth=2)
    axes.scatter(positions[-1:], mrr[-1:], s=36, color=SERIES_1, edgecolors=SURFACE, zorder=3)
    axes.annotate(
        usd_compact(mrr[-1]),
        xy=(positions[-1], mrr[-1]),
        xytext=(-8, 10),
        textcoords="offset points",
        ha="right",
        fontsize=10,
        weight="bold",
        color=INK,
    )
    ticks = [index for index, month in enumerate(months) if month.month in (1, 7)] or positions
    axes.set_xticks(ticks, [month_label(months[index]) for index in ticks])
    axes.set_xlim(-0.7, len(months) - 0.3)
    axes.set_ylim(0, max(mrr) * 1.15)
    axes.yaxis.set_major_formatter(COMPACT_USD)
    style_axes(axes)
    add_titles(
        figure,
        "Ending MRR by month",
        f"{month_label(months[0])} to {month_label(months[-1])}, "
        "measured on the last day of each month",
    )
    return save(figure, path)


@dataclass(frozen=True)
class _Bar:
    label: str
    bottom: float
    height: float
    colour: str
    text: str


def plot_mrr_bridge(data: ReportData, path: Path) -> Path:
    """Waterfall from starting to ending MRR over the trailing twelve months."""
    window = data.trailing_months(12)
    start, end = window[0].starting_mrr, window[-1].ending_mrr
    movements = [
        ("New", sum(month.new for month in window)),
        ("Expansion", sum(month.expansion for month in window)),
        ("Reactivation", sum(month.reactivation for month in window)),
        ("Contraction", sum(month.contraction for month in window)),
        ("Churn", sum(month.churned for month in window)),
    ]
    before = month_label(window[0].month_start - timedelta(days=1))
    bars = [_Bar(f"MRR\n{before}", 0.0, start, TOTAL, usd_compact(start))]
    running = start
    for name, amount in movements:
        bottom = running if amount >= 0 else running + amount
        colour = SERIES_1 if amount >= 0 else DECREASE
        bars.append(_Bar(name, bottom, abs(amount), colour, signed_usd_compact(amount)))
        running += amount
    if abs(running - end) > 0.01:
        raise ValueError(f"MRR bridge does not reconcile: {running:.2f} != {end:.2f}")
    bars.append(
        _Bar(f"MRR\n{month_label(window[-1].month_start)}", 0.0, end, TOTAL, usd_compact(end))
    )

    figure = new_figure(9.0, 4.8)
    axes = figure.add_axes((0.08, 0.15, 0.89, 0.63))
    positions = list(range(len(bars)))
    axes.bar(
        positions,
        [bar.height for bar in bars],
        bottom=[bar.bottom for bar in bars],
        color=[bar.colour for bar in bars],
        width=0.62,
    )
    top = max(bar.bottom + bar.height for bar in bars)
    for position, bar in zip(positions, bars, strict=True):
        label_y = bar.bottom + bar.height + top * 0.015
        axes.text(position, label_y, bar.text, ha="center", fontsize=9, color=INK)
    # Thin connectors show the running total each step starts from.
    level = start
    for position, (_, amount) in enumerate(movements):
        axes.plot([position + 0.31, position + 0.69], [level, level], color=INK_MUTED, lw=0.8)
        level += amount
    axes.plot([len(movements) + 0.31, len(movements) + 0.69], [end, end], color=INK_MUTED, lw=0.8)

    axes.set_xticks(positions, [bar.label for bar in bars])
    axes.set_ylim(0, top * 1.12)
    axes.yaxis.set_major_formatter(COMPACT_USD)
    style_axes(axes)
    axes.tick_params(axis="x", colors=INK_SECONDARY, labelsize=9.5)
    add_titles(
        figure,
        f"MRR bridge, last {len(window)} months",
        f"{month_label(window[0].month_start)} to {month_label(window[-1].month_start)}: "
        "blue movements add MRR, red movements remove it",
    )
    return save(figure, path)


def plot_cohort_retention(data: ReportData, path: Path) -> Path:
    """Heatmap of logo retention per cohort, next to pooled retention curves."""
    cohort_months = sorted({cell.cohort_month for cell in data.cohorts})
    row_of = {month: row for row, month in enumerate(cohort_months)}
    width = max(cell.months_since_start for cell in data.cohorts) + 1
    matrix = np.full((len(cohort_months), width), np.nan)
    for cell in data.cohorts:
        matrix[row_of[cell.cohort_month], cell.months_since_start] = (
            cell.active_customers / cell.cohort_customers
        )

    figure = new_figure(11.0, 5.8)
    grid = figure.add_gridspec(
        1, 2, width_ratios=(1.5, 1), left=0.1, right=0.97, bottom=0.11, top=0.8, wspace=0.3
    )
    heatmap = figure.add_subplot(grid[0, 0])
    image = heatmap.imshow(
        np.ma.masked_invalid(matrix),
        cmap=SEQUENTIAL_BLUE.with_extremes(bad=SURFACE),
        vmin=0,
        vmax=1,
        aspect="auto",
        interpolation="nearest",
    )
    step = 3 if len(cohort_months) > 12 else 1
    heatmap.set_yticks(
        range(0, len(cohort_months), step),
        [f"{month:%Y-%m}" for month in cohort_months[::step]],
    )
    heatmap.set_xticks(range(0, width, 6))
    heatmap.set_xlabel("Months since first paid month", color=INK_SECONDARY, fontsize=9.5)
    heatmap.set_ylabel("Cohort (first month with MRR)", color=INK_SECONDARY, fontsize=9.5)
    style_axes(heatmap, grid_axis=None)
    heatmap.spines["bottom"].set_visible(False)
    colorbar = figure.colorbar(image, ax=heatmap, fraction=0.04, pad=0.02)
    colorbar.ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    colorbar.ax.tick_params(colors=INK_MUTED, labelsize=8, length=0)
    colorbar.outline.set_visible(False)
    heatmap.set_title("Logo retention by cohort", loc="left", fontsize=10.5, color=INK)

    min_cohorts = min(MIN_COHORTS_PER_POINT, len(cohort_months))  # short histories still plot
    points = [p for p in pooled_retention(data.cohorts) if p.cohorts >= min_cohorts]
    curves = figure.add_subplot(grid[0, 1])
    months = [point.months_since_start for point in points]
    for values, colour, label in (
        ([p.net_revenue_retention for p in points], SERIES_2, "Net revenue retention"),
        ([p.logo_retention for p in points], SERIES_1, "Logo retention"),
    ):
        curves.plot(months, values, color=colour, linewidth=2, label=label)
        curves.annotate(
            pct(values[-1], 0),
            xy=(months[-1], values[-1]),
            xytext=(4, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=INK,
        )
    curves.set_ylim(0, max(1.05, max(p.net_revenue_retention for p in points) + 0.05))
    curves.yaxis.set_major_formatter(PercentFormatter(1.0))
    curves.set_xlabel("Months since first paid month", color=INK_SECONDARY, fontsize=9.5)
    curves.legend(loc="lower left", frameon=False, fontsize=9, labelcolor=INK_SECONDARY)
    style_axes(curves)
    curves.set_title("All cohorts pooled", loc="left", fontsize=10.5, color=INK)

    add_titles(
        figure,
        "Cohort retention",
        "Share of each monthly cohort still paying, and pooled retention across cohorts "
        f"(points backed by at least {min_cohorts} cohorts)",
    )
    return save(figure, path)


def plot_cac_payback(data: ReportData, path: Path) -> Path:
    """Months of gross profit needed to recover CAC, per paid channel."""
    paid = sorted(
        (
            row
            for row in data.economics
            if row.channel in PAID_CHANNELS
            and row.payback_months is not None
            and row.cac is not None
        ),
        key=lambda row: row.payback_months or 0.0,
    )
    blended = next((row for row in data.economics if row.channel == "all_channels"), None)

    figure = new_figure(9.0, 4.4)
    axes = figure.add_axes((0.15, 0.14, 0.8, 0.62))
    positions = list(range(len(paid)))
    paybacks = [row.payback_months or 0.0 for row in paid]
    axes.barh(positions, paybacks, height=0.56, color=SERIES_1)
    for position, row, payback in zip(positions, paid, paybacks, strict=True):
        axes.text(
            payback + 0.3,
            position,
            f"{payback:.1f} months  (CAC {usd_compact(row.cac or 0.0)})",
            va="center",
            fontsize=9,
            color=INK,
        )
    if blended is not None and blended.payback_months is not None:
        axes.axvline(blended.payback_months, color=INK_SECONDARY, linestyle=(0, (4, 3)), lw=1.2)
        axes.text(
            blended.payback_months,
            -0.62,
            f"Blended: {blended.payback_months:.1f} months",
            ha="center",
            fontsize=9,
            color=INK_SECONDARY,
        )
    axes.set_yticks(positions, [CHANNEL_LABELS[row.channel] for row in paid])
    axes.invert_yaxis()
    axes.set_xlim(0, max(paybacks, default=1.0) * 1.45)
    axes.set_xlabel("Months of gross profit to recover CAC", color=INK_SECONDARY, fontsize=9.5)
    style_axes(axes, grid_axis="x")
    axes.tick_params(axis="y", colors=INK_SECONDARY, labelsize=10)
    margin = paid[0].gross_margin if paid else 0.0
    add_titles(
        figure,
        "CAC payback by acquisition channel",
        f"Trailing 12 months. CAC / (ARPA x {margin:.0%} gross margin). "
        "Organic signups have no spend, so no CAC.",
    )
    return save(figure, path)


def plot_funnel(data: ReportData, path: Path) -> Path:
    """Signup-to-trial and trial-to-paid conversion per channel."""
    rows = sorted(data.funnel, key=lambda row: row.signup_to_paid, reverse=True)
    figure = new_figure(9.0, 4.9)
    axes = figure.add_axes((0.2, 0.12, 0.76, 0.68))
    positions = np.arange(len(rows))
    bar_height = 0.36
    for offset, values, colour, label in (
        (-bar_height / 2, [row.signup_to_trial for row in rows], SERIES_1, "Signup to trial"),
        (bar_height / 2, [row.trial_to_paid for row in rows], SERIES_2, "Trial to paid"),
    ):
        axes.barh(
            positions + offset,
            values,
            height=bar_height,
            color=colour,
            edgecolor=SURFACE,
            linewidth=1.5,
            label=label,
        )
        for position, value in zip(positions, values, strict=True):
            axes.text(
                value + 0.01, position + offset, pct(value, 0), va="center", fontsize=8.5, color=INK
            )
    axes.set_yticks(
        positions,
        [
            f"{CHANNEL_LABELS[row.channel]}\n{pct(row.signup_to_paid)} signup to paid"
            for row in rows
        ],
    )
    axes.invert_yaxis()
    axes.set_xlim(0, 1)
    axes.xaxis.set_major_formatter(PercentFormatter(1.0))
    axes.legend(loc="lower right", frameon=False, fontsize=9, labelcolor=INK_SECONDARY)
    style_axes(axes, grid_axis="x")
    axes.tick_params(axis="y", colors=INK_SECONDARY, labelsize=9)
    add_titles(
        figure,
        "Funnel conversion by acquisition channel",
        "Signup cohorts that ended at least 30 days before the data ends",
    )
    return save(figure, path)
