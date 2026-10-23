"""Number formatting shared by the charts and the markdown report."""

from __future__ import annotations

from datetime import date


def usd(value: float) -> str:
    """Whole dollars with thousands separators, e.g. ``$1,150,247``."""
    sign = "-" if round(value) < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def signed_usd(value: float) -> str:
    """Whole dollars with an explicit sign, e.g. ``+$37,006`` or ``-$12,345``."""
    return ("+" if round(value) > 0 else "") + usd(value)


def signed_usd_compact(value: float) -> str:
    """Compact form with an explicit sign for increases, e.g. ``+$37.0k`` or ``-$12.3k``."""
    return ("+" if value > 0 else "") + usd_compact(value)


def usd_compact(value: float) -> str:
    """Short form for chart labels, e.g. ``$1.15M``, ``$37.0k``, ``$950``."""
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    if magnitude >= 1_000_000:
        return f"{sign}${magnitude / 1_000_000:.2f}M"
    if magnitude >= 1_000:
        return f"{sign}${magnitude / 1_000:.1f}k"
    return f"{sign}${magnitude:.0f}"


def pct(value: float, digits: int = 1) -> str:
    """A ratio as a percentage, e.g. ``0.7046`` -> ``70.5%``."""
    return f"{value * 100:.{digits}f}%"


def optional(value: float | None, formatter: str = "{:.1f}", missing: str = "n/a") -> str:
    """Format a value that can be missing, such as CAC for a channel without spend."""
    return missing if value is None else formatter.format(value)


def month_label(day: date) -> str:
    """``2025-12-01`` -> ``Dec 2025``."""
    return day.strftime("%b %Y")
