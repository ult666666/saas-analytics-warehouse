"""Unit tests for the calendar, sampling, pricing and configuration helpers."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime

import numpy as np
import pytest

from saasgen.config import GeneratorConfig
from saasgen.dates import add_months, iter_days, month_end, month_start
from saasgen.pricing import PriceBook, build_price_book, unit_amount_cents
from saasgen.sampling import (
    compound_probability,
    random_time_between,
    random_time_on,
    weighted_choice,
)


@pytest.mark.parametrize(
    ("day", "months", "expected"),
    [
        (date(2024, 1, 15), 1, date(2024, 2, 15)),
        (date(2024, 1, 31), 1, date(2024, 2, 29)),  # leap year clamp
        (date(2023, 1, 31), 1, date(2023, 2, 28)),
        (date(2024, 1, 31), 2, date(2024, 3, 31)),  # computed from the anchor, no drift
        (date(2024, 11, 30), 3, date(2025, 2, 28)),  # year rollover
        (date(2024, 3, 31), -1, date(2024, 2, 29)),
        (date(2024, 6, 10), 12, date(2025, 6, 10)),
    ],
)
def test_add_months(day: date, months: int, expected: date) -> None:
    assert add_months(day, months) == expected


def test_month_boundaries_and_day_iteration() -> None:
    assert month_start(date(2024, 2, 17)) == date(2024, 2, 1)
    assert month_end(date(2024, 2, 17)) == date(2024, 2, 29)
    days = list(iter_days(date(2024, 2, 27), date(2024, 3, 2)))
    assert days == [
        date(2024, 2, 27),
        date(2024, 2, 28),
        date(2024, 2, 29),
        date(2024, 3, 1),
        date(2024, 3, 2),
    ]


def test_weighted_choice_follows_weights_and_skips_zero_weights() -> None:
    rng = np.random.default_rng(0)
    draws = Counter(weighted_choice(rng, ["a", "b", "c"], [0.75, 0.25, 0.0]) for _ in range(20_000))
    assert draws["c"] == 0
    assert draws["a"] / 20_000 == pytest.approx(0.75, abs=0.02)


def test_random_times_stay_inside_their_window() -> None:
    rng = np.random.default_rng(1)
    start, end = datetime(2024, 1, 1, 12), datetime(2024, 1, 3)
    for _ in range(1_000):
        assert start <= random_time_between(rng, start, end) < end
        assert random_time_on(rng, date(2024, 5, 4)).date() == date(2024, 5, 4)


def test_compound_probability() -> None:
    assert compound_probability(0.0, 12) == 0.0
    assert compound_probability(0.1, 1) == pytest.approx(0.1)
    assert compound_probability(0.1, 2) == pytest.approx(0.19)


def test_config_derived_dates_and_validation() -> None:
    config = GeneratorConfig(start_date=date(2023, 1, 1), months=36)
    assert config.end_date == date(2025, 12, 31)
    assert config.price_change_date == date(2024, 7, 1)
    with pytest.raises(ValueError, match="months"):
        GeneratorConfig(months=1)
    with pytest.raises(ValueError, match="scale"):
        GeneratorConfig(scale=0)
    with pytest.raises(ValueError, match="first day"):
        GeneratorConfig(start_date=date(2023, 1, 2))


def test_annual_price_includes_discount() -> None:
    assert unit_amount_cents(29, "month") == 2_900
    assert unit_amount_cents(29, "year") == 27_840  # 29 x 12 x 0.8


def test_price_book_has_one_list_price_change() -> None:
    config = GeneratorConfig()
    prices = build_price_book(config)
    assert len(prices) == 12  # 3 plans x 2 intervals x 2 versions
    book = PriceBook(prices)
    before = book.price_on("growth", "month", date(2024, 6, 30))
    after = book.price_on("growth", "month", config.price_change_date)
    assert before.plan_price_id == "growth_monthly_v1"
    assert after.plan_price_id == "growth_monthly_v2"
    assert after.unit_amount_cents > before.unit_amount_cents
    with pytest.raises(LookupError):
        book.price_on("growth", "month", date(2020, 1, 1))
