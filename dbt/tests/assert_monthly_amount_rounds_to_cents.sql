-- Examples are in integer cents per billing interval. Expected MRR is in dollars.
with examples (unit_cents, seats, billing_interval, expected_mrr) as (
    values
    (1061, 1, 'year', 0.88),
    (1062, 1, 'year', 0.89),
    (-1062, 1, 'year', -0.89),
    (1063, 1, 'year', 0.89),
    (1210, 3, 'year', 3.03),
    (999999999999999990, 1, 'year', 833333333333333.33),
    (999999999999999999, 1, 'month', 9999999999999999.99),
    (1000, 1, 'unknown', null)
),

prices as (
    select *, {{ cents_to_dollars('unit_cents') }} as unit_amount_usd
    from examples
),

normalized as (
    select *, {{ monthly_amount('seats * unit_amount_usd', 'billing_interval') }} as actual_mrr
    from prices
)

select * from normalized
where actual_mrr is distinct from expected_mrr
