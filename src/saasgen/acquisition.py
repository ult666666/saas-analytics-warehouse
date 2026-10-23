"""Top of the funnel: daily marketing spend, signups, trials and trial conversions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from saasgen.config import (
    CHANNELS,
    COMPANY_SIZES,
    CONVERT_AT_TRIAL_END_SHARE,
    COUNTRIES,
    MESSY_UTM_RATE,
    MONTHLY_ORGANIC_GROWTH,
    MONTHLY_SPEND_GROWTH,
    SEASONALITY,
    SPEND_NOISE_SIGMA,
    TRIAL_DAYS,
    WEEKDAY_FACTORS,
    ChannelParams,
    GeneratorConfig,
)
from saasgen.dates import iter_days
from saasgen.records import Customer, MarketingSpend, Signup, Trial
from saasgen.sampling import SECONDS_PER_DAY, chance, random_time_on, weighted_choice

AVERAGE_DAYS_PER_MONTH = 365.25 / 12
COUNTRY_CODES = tuple(code for code, _ in COUNTRIES)
COUNTRY_WEIGHTS = tuple(weight for _, weight in COUNTRIES)


@dataclass(frozen=True)
class Conversion:
    """A new paying customer plus the attribute the lifecycle simulation needs."""

    customer: Customer
    company_size: str


@dataclass(frozen=True)
class AcquisitionData:
    marketing_spend: list[MarketingSpend]
    signups: list[Signup]
    trials: list[Trial]
    conversions: list[Conversion]


def simulate_acquisition(config: GeneratorConfig, rng: np.random.Generator) -> AcquisitionData:
    """Simulate the funnel day by day.

    Paid channels turn spend into signups at a channel-specific cost per signup;
    organic signups grow on their own. Each signup may start a trial, and each
    trial may convert into a customer. Conversions after the last simulated day
    are dropped, exactly as an extract taken on that day would not contain them.
    """
    spend_rows: list[MarketingSpend] = []
    signups: list[Signup] = []
    trials: list[Trial] = []
    converted: list[tuple[datetime, str, str]] = []  # (converted_at, signup_id, company_size)

    for day_index, day in enumerate(iter_days(config.start_date, config.end_date)):
        months_elapsed = day_index / AVERAGE_DAYS_PER_MONTH
        demand = SEASONALITY[day.month - 1] * WEEKDAY_FACTORS[day.weekday()]
        arrivals: list[tuple[datetime, ChannelParams]] = []

        for channel in CHANNELS:
            if channel.daily_spend_usd > 0:
                spend_usd = (
                    channel.daily_spend_usd
                    * config.scale
                    * (1 + MONTHLY_SPEND_GROWTH) ** months_elapsed
                    * demand
                    * rng.lognormal(0.0, SPEND_NOISE_SIGMA)
                )
                spend_cents = round(spend_usd * 100)
                spend_rows.append(MarketingSpend(day, channel.name, spend_cents))
                expected_signups = spend_cents / 100 / channel.cost_per_signup_usd
            else:
                expected_signups = (
                    channel.organic_daily_signups
                    * config.scale
                    * (1 + MONTHLY_ORGANIC_GROWTH) ** months_elapsed
                    * demand
                )
            for _ in range(int(rng.poisson(expected_signups))):
                arrivals.append((random_time_on(rng, day), channel))

        # Assign IDs in time order so that signup IDs increase with created_at.
        arrivals.sort(key=lambda arrival: arrival[0])
        for created_at, channel in arrivals:
            signup = _new_signup(rng, len(signups) + 1, created_at, channel)
            signups.append(signup)
            if not chance(rng, channel.signup_to_trial):
                continue
            trial_start = created_at + _trial_delay(rng)
            if trial_start.date() > config.end_date:
                continue
            trials.append(
                Trial(
                    trial_id=f"trl_{len(trials) + 1:07d}",
                    signup_id=signup.signup_id,
                    started_at=trial_start,
                    ends_at=trial_start + timedelta(days=TRIAL_DAYS),
                )
            )
            if chance(rng, channel.trial_to_paid):
                converted_at = _conversion_time(rng, trial_start)
                if converted_at.date() <= config.end_date:
                    converted.append((converted_at, signup.signup_id, signup.company_size))

    converted.sort()
    conversions = [
        Conversion(
            customer=Customer(f"cus_{index:07d}", signup_id, converted_at),
            company_size=company_size,
        )
        for index, (converted_at, signup_id, company_size) in enumerate(converted, start=1)
    ]
    return AcquisitionData(spend_rows, signups, trials, conversions)


def _new_signup(
    rng: np.random.Generator, number: int, created_at: datetime, channel: ChannelParams
) -> Signup:
    sources = tuple(source for source, _ in channel.utm_sources)
    source_weights = tuple(weight for _, weight in channel.utm_sources)
    utm_source = weighted_choice(rng, sources, source_weights)
    if utm_source is not None and chance(rng, MESSY_UTM_RATE):
        utm_source = _messy(rng, utm_source)
    return Signup(
        signup_id=f"sgn_{number:07d}",
        created_at=created_at,
        utm_source=utm_source,
        country_code=weighted_choice(rng, COUNTRY_CODES, COUNTRY_WEIGHTS),
        company_size=weighted_choice(rng, COMPANY_SIZES, channel.company_size_mix),
    )


def _messy(rng: np.random.Generator, value: str) -> str:
    """Simulate hand-typed tracking parameters: odd casing or stray whitespace."""
    variant = int(rng.integers(0, 3))
    if variant == 0:
        return value.upper()
    if variant == 1:
        return value.title()
    return f" {value} "


def _trial_delay(rng: np.random.Generator) -> timedelta:
    """Most signups start their trial right away; some come back a day or a few days later."""
    roll = rng.random()
    if roll < 0.7:
        return timedelta(minutes=int(rng.integers(1, 121)))
    if roll < 0.9:
        return timedelta(days=1, minutes=int(rng.integers(0, 24 * 60)))
    return timedelta(days=2, minutes=int(rng.integers(0, 2 * 24 * 60)))


def _conversion_time(rng: np.random.Generator, trial_start: datetime) -> datetime:
    """Most trials convert automatically at the end; the rest upgrade early."""
    if chance(rng, CONVERT_AT_TRIAL_END_SHARE):
        return trial_start + timedelta(days=TRIAL_DAYS)
    return trial_start + timedelta(seconds=int(rng.integers(3600, TRIAL_DAYS * SECONDS_PER_DAY)))
