"""Random-sampling helpers built on a seeded ``numpy.random.Generator``."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta

import numpy as np

SECONDS_PER_DAY = 86_400


def chance(rng: np.random.Generator, probability: float) -> bool:
    """Return True with the given probability."""
    return bool(rng.random() < probability)


def weighted_choice[T](
    rng: np.random.Generator, options: Sequence[T], weights: Sequence[float]
) -> T:
    """Pick one option with probability proportional to its weight."""
    target = rng.random() * sum(weights)
    cumulative = 0.0
    for option, weight in zip(options, weights, strict=True):
        cumulative += weight
        if target < cumulative:
            return option
    return options[-1]  # guards against floating-point rounding in the cumulative sum


def random_time_on(rng: np.random.Generator, day: date) -> datetime:
    """A uniformly random second within the given day."""
    return datetime.combine(day, time()) + timedelta(seconds=int(rng.integers(0, SECONDS_PER_DAY)))


def random_time_between(rng: np.random.Generator, start: datetime, end: datetime) -> datetime:
    """A uniformly random second in ``[start, end)``; ``end`` must be after ``start``."""
    seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=int(rng.integers(0, seconds)))


def midnight(day: date) -> datetime:
    return datetime.combine(day, time())


def compound_probability(monthly_probability: float, months: int) -> float:
    """Probability that an event with a constant monthly probability happens within ``months``."""
    return 1.0 - (1.0 - monthly_probability) ** months
