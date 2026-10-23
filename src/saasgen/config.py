"""Simulation parameters for Tallyloom, a fictional B2B SaaS company.

Every behavioural assumption of the synthetic data lives in this module, so the
simulation code stays free of magic numbers and the tests can compare the
generated rates with the configured ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from saasgen.dates import add_months, month_end

COMPANY_NAME = "Tallyloom"  # fictional company; any resemblance is unintended

# --- Plans and pricing ---------------------------------------------------------------------------

ANNUAL_DISCOUNT = 0.20  # annual billing costs 12 x monthly list price x (1 - discount)
CURRENCY = "USD"


@dataclass(frozen=True)
class PlanParams:
    code: str
    name: str
    tier: int
    price_before_change_usd: int  # list price per seat per month before the price change
    price_after_change_usd: int  # list price per seat per month from the price change onwards
    annual_share: float  # share of new subscriptions that choose annual billing
    monthly_churn: float  # base probability that a monthly subscription cancels at a renewal
    upgrade_rate: float  # monthly probability of moving up one tier (before tenure effect)
    downgrade_rate: float  # monthly probability of moving down one tier


PLANS: tuple[PlanParams, ...] = (
    PlanParams("starter", "Starter", 1, 12, 14, 0.15, 0.035, 0.020, 0.000),
    PlanParams("growth", "Growth", 2, 29, 34, 0.30, 0.022, 0.008, 0.006),
    PlanParams("enterprise", "Enterprise", 3, 59, 69, 0.55, 0.012, 0.000, 0.006),
)
PLANS_BY_CODE = {plan.code: plan for plan in PLANS}
PLANS_BY_TIER = {plan.tier: plan for plan in PLANS}

# --- Customers -----------------------------------------------------------------------------------

COMPANY_SIZES = ("1-10", "11-50", "51-200", "201-1000", "1000+")

# Inclusive range of seats bought at conversion, by company size.
SEATS_BY_SIZE: dict[str, tuple[int, int]] = {
    "1-10": (1, 4),
    "11-50": (3, 10),
    "51-200": (6, 25),
    "201-1000": (15, 60),
    "1000+": (40, 120),
}

# Probability of choosing (starter, growth, enterprise) at conversion, by company size.
PLAN_MIX_BY_SIZE: dict[str, tuple[float, float, float]] = {
    "1-10": (0.70, 0.28, 0.02),
    "11-50": (0.40, 0.52, 0.08),
    "51-200": (0.15, 0.60, 0.25),
    "201-1000": (0.05, 0.45, 0.50),
    "1000+": (0.02, 0.28, 0.70),
}

# Smaller companies churn more often than larger ones.
CHURN_MULTIPLIER_BY_SIZE: dict[str, float] = {
    "1-10": 1.3,
    "11-50": 1.0,
    "51-200": 0.8,
    "201-1000": 0.6,
    "1000+": 0.5,
}

COUNTRIES: tuple[tuple[str, float], ...] = (
    ("US", 0.45),
    ("GB", 0.10),
    ("DE", 0.08),
    ("CA", 0.07),
    ("IN", 0.06),
    ("FR", 0.05),
    ("AU", 0.05),
    ("NL", 0.04),
    ("BR", 0.04),
    ("SG", 0.03),
    ("JP", 0.03),
)

# --- Acquisition ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class ChannelParams:
    name: str
    daily_spend_usd: float  # base daily media spend at scale 1.0 (0 for organic)
    cost_per_signup_usd: float  # average spend per signup (paid channels only)
    organic_daily_signups: float  # base daily signups at scale 1.0 (organic only)
    signup_to_trial: float  # probability that a signup starts a trial
    trial_to_paid: float  # probability that a trial converts to a paying customer
    utm_sources: tuple[tuple[str | None, float], ...]  # raw attribution values and weights
    company_size_mix: tuple[float, float, float, float, float]  # weights for COMPANY_SIZES


CHANNELS: tuple[ChannelParams, ...] = (
    ChannelParams(
        name="paid_search",
        daily_spend_usd=3500.0,
        cost_per_signup_usd=680.0,
        organic_daily_signups=0.0,
        signup_to_trial=0.75,
        trial_to_paid=0.20,
        utm_sources=(("google_ads", 0.8), ("bing_ads", 0.2)),
        company_size_mix=(0.35, 0.33, 0.19, 0.10, 0.03),
    ),
    ChannelParams(
        name="paid_social",
        daily_spend_usd=2100.0,
        cost_per_signup_usd=420.0,
        organic_daily_signups=0.0,
        signup_to_trial=0.60,
        trial_to_paid=0.10,
        utm_sources=(("linkedin_ads", 0.6), ("meta_ads", 0.4)),
        company_size_mix=(0.50, 0.30, 0.13, 0.05, 0.02),
    ),
    ChannelParams(
        name="content",
        daily_spend_usd=560.0,
        cost_per_signup_usd=290.0,
        organic_daily_signups=0.0,
        signup_to_trial=0.70,
        trial_to_paid=0.17,
        utm_sources=(("blog", 0.60), ("newsletter", 0.25), ("webinar", 0.15)),
        company_size_mix=(0.40, 0.33, 0.17, 0.08, 0.02),
    ),
    ChannelParams(
        name="partner",
        daily_spend_usd=980.0,
        cost_per_signup_usd=1100.0,
        organic_daily_signups=0.0,
        signup_to_trial=0.85,
        trial_to_paid=0.32,
        utm_sources=(("partner_referral", 0.7), ("app_marketplace", 0.3)),
        company_size_mix=(0.20, 0.30, 0.25, 0.17, 0.08),
    ),
    ChannelParams(
        name="organic",
        daily_spend_usd=0.0,
        cost_per_signup_usd=0.0,
        organic_daily_signups=4.0,
        signup_to_trial=0.70,
        trial_to_paid=0.22,
        utm_sources=((None, 1.0),),  # no UTM parameters: direct traffic and word of mouth
        company_size_mix=(0.42, 0.32, 0.16, 0.08, 0.02),
    ),
)
CHANNELS_BY_NAME = {channel.name: channel for channel in CHANNELS}

MONTHLY_SPEND_GROWTH = 0.015  # marketing budgets grow 1.5% per month
MONTHLY_ORGANIC_GROWTH = 0.020  # word of mouth grows 2% per month
SPEND_NOISE_SIGMA = 0.15  # day-to-day noise in spend (log-normal sigma)
# B2B demand by calendar month: strong in Q1 and September/October, weak in summer and December.
SEASONALITY = (1.05, 1.00, 1.05, 1.00, 1.00, 0.95, 0.85, 0.85, 1.10, 1.10, 1.00, 0.80)
WEEKDAY_FACTORS = (1.12, 1.12, 1.12, 1.12, 1.12, 0.70, 0.70)  # Monday..Sunday, averages 1.0
MESSY_UTM_RATE = 0.03  # share of raw utm_source values with inconsistent case or whitespace

TRIAL_DAYS = 14
CONVERT_AT_TRIAL_END_SHARE = 0.60  # the rest convert early, during the trial

# --- Subscription lifecycle ----------------------------------------------------------------------

EARLY_TENURE_RENEWALS = 3  # the first renewals of a monthly subscription are riskier
EARLY_TENURE_CHURN_MULTIPLIER = 1.5
ANNUAL_CHURN_FACTOR = 0.6  # annual contracts are stickier than 12 monthly renewals
SEAT_INCREASE_RATE = 0.05  # monthly probability of adding seats (before tenure effect)
SEAT_INCREASE_FRACTION = (0.10, 0.40)  # seats added, as a fraction of current seats
SEAT_DECREASE_RATE = 0.02  # monthly probability of removing seats
SEAT_DECREASE_FRACTION = (0.10, 0.30)  # seats removed, as a fraction of current seats
EXPANSION_RAMP_MONTHS = 24  # expansion propensity ramps from 0.6x to 1.4x over two years
REACTIVATION_PROBABILITY: dict[str, float] = {"voluntary": 0.10, "payment_failed": 0.25}
REACTIVATION_DELAY_DAYS = (45, 300)  # inclusive range of days between churn and reactivation
REACTIVATE_SAME_PLAN_SHARE = 0.70  # returning customers usually pick their previous plan
REACTIVATION_SEAT_FACTOR = (0.60, 1.00)  # and come back with the same or fewer seats

# --- Billing -------------------------------------------------------------------------------------

PAYMENT_FAILURE_RATE = 0.06  # first charge attempt of a renewal invoice fails
RETRY_DAYS = (3, 7, 14)  # retry schedule, in days after the invoice date
RETRY_SUCCESS_RATE = 0.45  # probability that each retry succeeds
FAILURE_CODES: tuple[tuple[str, float], ...] = (
    ("card_declined", 0.5),
    ("insufficient_funds", 0.3),
    ("expired_card", 0.2),
)
DUPLICATE_PAYMENT_RATE = 0.005  # payment webhooks are delivered at least once


# --- Run configuration ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeneratorConfig:
    """Size and randomness of one generated dataset.

    The same configuration always produces byte-identical output.
    """

    seed: int = 42
    start_date: date = date(2023, 1, 1)
    months: int = 36
    scale: float = 1.0  # multiplies marketing spend and organic signups

    def __post_init__(self) -> None:
        if self.months < 2:
            raise ValueError("months must be at least 2")
        if self.scale <= 0:
            raise ValueError("scale must be positive")
        if self.start_date.day != 1:
            raise ValueError("start_date must be the first day of a month")

    @property
    def end_date(self) -> date:
        """Last simulated day (inclusive): the last day of the final month."""
        return month_end(add_months(self.start_date, self.months - 1))

    @property
    def price_change_date(self) -> date:
        """Day the second price book takes effect: the first day of the middle month."""
        return add_months(self.start_date, self.months // 2)
