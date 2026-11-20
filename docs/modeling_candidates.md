# Predictive modeling: status and candidates

*Assessed 2026-10-22, after the dataset was built.* Service planning only: every candidate predicts aggregate releases
for states and counties, never anything about an individual child, sponsor or household.

> **Note, 2026-11-11.** This is a dated note; `docs/spec_share_model_scenarios.md` and `docs/ASSUMPTIONS.md` now govern.
> Two things below no longer hold.
> 1. *"Must beat 0.206 share points."* The winner is picked on the log score under a fixed, pessimistic rule
>    (AS-20), not on mean absolute error.
> 2. *The county result.* The probe scored "last year" on counties it had never seen: a county new to the list
>    got only the floor, and new counties took up to 27% of a year's releases. On the matched categories now
>    used (counties listed in both years, plus other; AS-16), last year's shares is the best simple rule for
>    counties too: 1.01 share points against 1.22 for the three-year mean and 1.51 pooled (10 largest states,
>    FY2017–FY2025). So the case for partial pooling at county level is not supported by this probe. The
>    owner's working view is that a more complicated model is not necessarily better and a simpler
>    distribution may serve, especially since many counties do not appear every year (AS-43).

## What exists today

No model yet. The plan schedules the share model and then the scenario engine. A
feasibility probe (`src/probes/share_backtest.py`) measured how predictable shares already are.

## Probe: how predictable are next year's shares?

Held-out years FY2017–FY2025, each predicted from earlier years only; weighted by releases.

| Level | Method | MAE (share points) | Log score per release |
|---|---|---|---|
| State share of national (50 states + DC) | **last year (plan's baseline)** | **0.206** | **−3.158** |
| | mean of last 3 years | 0.221 | −3.160 |
| | all earlier years pooled | 0.291 | −3.168 |
| County share within state (10 largest states; other counties as one category) | last year | 1.331 | −2.479 |
| | mean of last 3 years | 1.294 | −2.352 |
| | all earlier years pooled | 1.343 | **−2.341** |

**Reading:** state shares are very stable, and last year is the best simple predictor. A share model
must beat 0.206 share points to be worth it. County shares are noisier, and averaging over years beats last
year on log score, so a model that borrows strength across years and counties (partial pooling) has real
room to help at county level.

## Candidates, ranked

| # | Candidate | Predicts | Data | Ready? |
|---|---|---|---|---|
| 1 | **County shares within state, partial pooling** (Dirichlet-multinomial) | Each listed county's and "other counties'" share of a state's releases | release table | **Now.** Must handle counties entering and leaving the list at the 50-release threshold without estimating suppressed values |
| 2 | **State shares** (Dirichlet-multinomial, recency-weighted) | Each state's share of national releases | release table | **Now**, against the strong naive baseline above |
| 3 | **Scenario engine** (Monte Carlo over the share models) | Releases and school-age needs by state and county under low / median / high national volume, with 80% ranges | Share models + FY2015–FY2025 volumes | After 1–2 |
| 4 | **National volume from CBP encounters** (lagged regression) | Releases a few months ahead | CBP Southwest Border monthly encounters of unaccompanied children (public portal) | Stretch goal. FY2025 (24,259) and October 2025 (106) suggest a regime change, so scenarios stay safer than forecasts |
| 5 | **Linear compartment model** (from the predator-prey literature) | Children in ORR care as inflow (referrals) minus outflow (releases) | ORR Facts and Data: referrals, children in care, average length of care | Possible later. National only, which fits the plan's guardrails |

**Off-limits:** anything predicting which children, sponsors or households are where; estimating
counties below the 50-release threshold.
