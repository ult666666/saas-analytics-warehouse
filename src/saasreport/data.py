"""Reads the dbt marts from DuckDB into small typed records for the charts and the report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb

# Fixed channel order, so a channel keeps its position (and colour) in every chart and table.
CHANNEL_ORDER = ("paid_search", "paid_social", "content", "partner", "organic", "all_channels")
CHANNEL_LABELS = {
    "paid_search": "Paid search",
    "paid_social": "Paid social",
    "content": "Content",
    "partner": "Partner",
    "organic": "Organic",
    "all_channels": "All channels (blended)",
}


@dataclass(frozen=True)
class BridgeMonth:
    month_start: date
    starting_mrr: float
    new: float
    expansion: float
    reactivation: float
    contraction: float  # negative
    churned: float  # negative
    involuntary_churned: float  # negative, part of churned
    ending_mrr: float
    starting_customers: int
    new_customers: int
    churned_customers: int
    ending_customers: int


@dataclass(frozen=True)
class CohortCell:
    cohort_month: date
    months_since_start: int
    cohort_customers: int
    active_customers: int
    starting_mrr: float
    mrr: float


@dataclass(frozen=True)
class ChannelEconomics:
    channel: str
    marketing_spend: float
    new_customers: int
    cac: float | None
    arpa: float | None
    gross_margin: float
    monthly_churn: float | None
    ltv: float | None
    payback_months: float | None
    ltv_to_cac: float | None


@dataclass(frozen=True)
class ChannelFunnel:
    channel: str
    signups: int
    trials: int
    paid: int

    @property
    def signup_to_trial(self) -> float:
        return self.trials / self.signups if self.signups else 0.0

    @property
    def trial_to_paid(self) -> float:
        return self.paid / self.trials if self.trials else 0.0

    @property
    def signup_to_paid(self) -> float:
        return self.paid / self.signups if self.signups else 0.0


@dataclass(frozen=True)
class PlanMix:
    plan_name: str
    customers: int
    mrr: float
    grandfathered_mrr: float  # MRR still billed at the pre-change list price


@dataclass(frozen=True)
class ReportData:
    bridge: list[BridgeMonth]
    cohorts: list[CohortCell]
    economics: list[ChannelEconomics]
    funnel: list[ChannelFunnel]
    plan_mix: list[PlanMix]

    @property
    def last_month(self) -> BridgeMonth:
        return self.bridge[-1]

    def trailing_months(self, months: int = 12) -> list[BridgeMonth]:
        """The most recent ``months`` bridge rows (fewer if the data is shorter)."""
        return self.bridge[-months:]


BRIDGE_SQL = """
    select
        month_start, starting_mrr_usd, new_mrr_usd, expansion_mrr_usd, reactivation_mrr_usd,
        contraction_mrr_usd, churned_mrr_usd, involuntary_churned_mrr_usd, ending_mrr_usd,
        starting_customers, new_customers, churned_customers, ending_customers
    from marts.rpt_mrr_bridge
    order by month_start
"""

COHORTS_SQL = """
    select
        cohort_month, months_since_cohort_start, cohort_customers, active_customers,
        cohort_starting_mrr_usd, mrr_usd
    from marts.rpt_cohort_retention
    order by cohort_month, months_since_cohort_start
"""

ECONOMICS_SQL = """
    select
        channel, marketing_spend_usd, new_customers, cac_usd, arpa_usd, gross_margin_pct,
        monthly_logo_churn_rate, ltv_usd, cac_payback_months, ltv_to_cac_ratio
    from marts.rpt_unit_economics
"""

FUNNEL_SQL = """
    select channel, sum(signups), sum(trials), sum(paid_customers)
    from marts.rpt_funnel
    where is_complete_cohort
    group by channel
"""

PLAN_MIX_SQL = """
    select
        plans.plan_name,
        count(*) as customers,
        sum(mrr.mrr_usd) as mrr_usd,
        coalesce(sum(mrr.mrr_usd) filter (where not plans.is_current_price), 0) as grandfathered
    from marts.fct_mrr as mrr
    inner join marts.dim_plans as plans
        on mrr.plan_price_id = plans.plan_price_id
    where mrr.is_active
        and mrr.month_start = (select max(month_start) from marts.fct_mrr)
    group by plans.plan_name, plans.plan_tier
    order by plans.plan_tier
"""


def _optional_float(value: object) -> float | None:
    return None if value is None else float(str(value))


def _channel_position(channel: str) -> int:
    return CHANNEL_ORDER.index(channel) if channel in CHANNEL_ORDER else len(CHANNEL_ORDER)


def load_report_data(connection: duckdb.DuckDBPyConnection) -> ReportData:
    bridge = [
        BridgeMonth(
            month_start=row[0],
            starting_mrr=float(row[1]),
            new=float(row[2]),
            expansion=float(row[3]),
            reactivation=float(row[4]),
            contraction=float(row[5]),
            churned=float(row[6]),
            involuntary_churned=float(row[7]),
            ending_mrr=float(row[8]),
            starting_customers=int(row[9]),
            new_customers=int(row[10]),
            churned_customers=int(row[11]),
            ending_customers=int(row[12]),
        )
        for row in connection.execute(BRIDGE_SQL).fetchall()
    ]
    if not bridge:
        raise ValueError("marts.rpt_mrr_bridge is empty: run 'make build' first")

    cohorts = [
        CohortCell(
            cohort_month=row[0],
            months_since_start=int(row[1]),
            cohort_customers=int(row[2]),
            active_customers=int(row[3]),
            starting_mrr=float(row[4]),
            mrr=float(row[5]),
        )
        for row in connection.execute(COHORTS_SQL).fetchall()
    ]

    economics = sorted(
        (
            ChannelEconomics(
                channel=str(row[0]),
                marketing_spend=float(row[1]),
                new_customers=int(row[2]),
                cac=_optional_float(row[3]),
                arpa=_optional_float(row[4]),
                gross_margin=float(row[5]),
                monthly_churn=_optional_float(row[6]),
                ltv=_optional_float(row[7]),
                payback_months=_optional_float(row[8]),
                ltv_to_cac=_optional_float(row[9]),
            )
            for row in connection.execute(ECONOMICS_SQL).fetchall()
        ),
        key=lambda economics: _channel_position(economics.channel),
    )

    funnel = sorted(
        (
            ChannelFunnel(
                channel=str(row[0]), signups=int(row[1]), trials=int(row[2]), paid=int(row[3])
            )
            for row in connection.execute(FUNNEL_SQL).fetchall()
        ),
        key=lambda funnel: _channel_position(funnel.channel),
    )

    plan_mix = [
        PlanMix(
            plan_name=str(row[0]),
            customers=int(row[1]),
            mrr=float(row[2]),
            grandfathered_mrr=float(row[3]),
        )
        for row in connection.execute(PLAN_MIX_SQL).fetchall()
    ]
    return ReportData(bridge, cohorts, economics, funnel, plan_mix)


@dataclass(frozen=True)
class RetentionPoint:
    months_since_start: int
    cohorts: int  # cohorts old enough to have reached this month
    logo_retention: float
    net_revenue_retention: float


@dataclass
class _RetentionTotals:
    cohorts: int = 0
    customers: int = 0
    active_customers: int = 0
    starting_mrr: float = 0.0
    mrr: float = 0.0


def pooled_retention(cohorts: list[CohortCell]) -> list[RetentionPoint]:
    """Retention curves pooled over every cohort that has reached each month.

    The rates are ratios of sums, so large cohorts weigh more than small ones; an average
    of per-cohort percentages would let a tiny cohort swing the curve.
    """
    totals: dict[int, _RetentionTotals] = {}
    for cell in cohorts:
        bucket = totals.setdefault(cell.months_since_start, _RetentionTotals())
        bucket.cohorts += 1
        bucket.customers += cell.cohort_customers
        bucket.active_customers += cell.active_customers
        bucket.starting_mrr += cell.starting_mrr
        bucket.mrr += cell.mrr
    return [
        RetentionPoint(
            months_since_start=months,
            cohorts=bucket.cohorts,
            logo_retention=bucket.active_customers / bucket.customers,
            net_revenue_retention=bucket.mrr / bucket.starting_mrr,
        )
        for months, bucket in sorted(totals.items())
    ]
