"""Chart styling: one light theme, a validated palette and recessive axes.

Colours follow a colour-blind-checked reference palette: categorical slots in a fixed
order, a blue/red diverging pair for increases and decreases, and a single-hue blue ramp
for magnitude (the retention heatmap).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from matplotlib.axes import Axes
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

SERIES_1 = "#2a78d6"  # blue: first categorical slot, and the "increase" pole
SERIES_2 = "#eb6834"  # orange: second categorical slot
DECREASE = "#e34948"  # red: the "decrease" pole of the diverging pair
TOTAL = INK_SECONDARY  # neutral bars for totals in the waterfall

BLUE_RAMP = (
    "#cde2fb",
    "#b7d3f6",
    "#9ec5f4",
    "#86b6ef",
    "#6da7ec",
    "#5598e7",
    "#3987e5",
    "#2a78d6",
    "#256abf",
    "#1c5cab",
    "#184f95",
    "#104281",
    "#0d366b",
)
SEQUENTIAL_BLUE = LinearSegmentedColormap.from_list("sequential_blue", BLUE_RAMP)

FIGURE_DPI = 130
SYNTHETIC_NOTE = "Synthetic data for Tallyloom, a fictional company"


def new_figure(width: float = 9.0, height: float = 5.0) -> Figure:
    figure = Figure(figsize=(width, height), dpi=FIGURE_DPI, facecolor=SURFACE)
    return figure


def style_axes(axes: Axes, *, grid_axis: Literal["x", "y"] | None = "y") -> None:
    """Recessive chrome: no box, hairline grid on the value axis, muted tick labels."""
    axes.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        axes.spines[side].set_visible(False)
    axes.spines["bottom"].set_color(BASELINE)
    axes.tick_params(colors=INK_MUTED, labelsize=9, length=0, pad=6)
    if grid_axis is not None:
        axes.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    axes.set_axisbelow(True)


def add_titles(figure: Figure, title: str, subtitle: str) -> None:
    figure.text(0.02, 0.965, title, ha="left", va="top", fontsize=13, weight="bold", color=INK)
    figure.text(0.02, 0.905, subtitle, ha="left", va="top", fontsize=9.5, color=INK_SECONDARY)
    figure.text(0.98, 0.015, SYNTHETIC_NOTE, ha="right", va="bottom", fontsize=8, color=INK_MUTED)


def save(figure: Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # No "Software" metadata, so identical data always produces identical files.
    figure.savefig(path, facecolor=SURFACE, metadata={"Software": None})
    return path
