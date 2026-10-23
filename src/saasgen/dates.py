"""Small calendar helpers (the standard library has no month arithmetic)."""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from datetime import date, timedelta


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def add_months(day: date, months: int) -> date:
    """Shift a date by whole months, clamping to the last day of shorter months.

    Billing anniversaries are always computed from the original anchor date
    (``add_months(anchor, k)``) so that a subscription started on 31 January
    renews on 28/29 February and then on 31 March again.
    """
    month_index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(month_index, 12)
    month += 1
    return date(year, month, min(day.day, days_in_month(year, month)))


def month_start(day: date) -> date:
    return day.replace(day=1)


def month_end(day: date) -> date:
    return day.replace(day=days_in_month(day.year, day.month))


def iter_days(start: date, end: date) -> Iterator[date]:
    """Yield every date from ``start`` to ``end``, both inclusive."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
