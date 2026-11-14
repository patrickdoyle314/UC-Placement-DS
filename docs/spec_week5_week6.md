# Spec: Week 5 share model and Week 6 scenario engine

The project owner writes these two pieces. This spec covers **what** each one must produce, so that the
app (`app/streamlit_app.py`) and the acceptance tests (`tests/test_acceptance.py`) can use it. **How** to
build them is up to the owner. Requirement IDs (FR-xx, NFR-xx) refer to the business requirements document,
which is kept local with the plan.

*Updated 2026-11-05 after an outside review of the math doc. The review's main points are now checks:
model against naive year by year, sampler diagnostics for every fit, calibration for large and small states,
the school-age assumption, and the fallback. Each new item below is marked "(review)".*

*Updated 2026-11-08: the owner confirmed four model decisions from the revised math doc (the floor for
zero shares, FY2014 as the first "last year", the winner rule, and the school-age fraction). The scenario
engine also follows the revised doc: it counts children out instead of multiplying, and it shows only
counties listed in FY2025. These items are marked "(decided)".*

*Updated 2026-11-10: the school-age point estimate now uses ORR's own split of the 0–12 group (λ = 0.863)
instead of spreading ages evenly (8/13); the low–high range is unchanged. Every assumption, with its
status and history, is listed in `docs/ASSUMPTIONS.md`.*

*Updated 2026-11-11, after a logic check of the whole project: four owner decisions. The winner rule is
now pessimistic (it must hold under three scorings). The fallback's error model is built in two versions
and compared head to head. The District of Columbia is treated as a county. An "other counties" figure
that covers a single county is marked not publishable. These items are marked "(decided 2026-11-11)".*

Check progress at any time:

```bash
python -m pytest tests/test_acceptance.py -v
```

Each test is skipped until the file it checks exists. Once the file is there, the test must pass.

## Week 5: share model (FR-11, FR-12)

**Code:** `src/share_model.py`

- Model state shares, and county shares within each state, with a Dirichlet-multinomial model in PyMC.
  Within a state, the shares are the listed counties plus that state's single "other counties" group.
  Counties under 50 releases are never modeled one by one.
- Backtest each held-out year from FY2018 to FY2025, fitting only on earlier years. Score it the way
  `src/share_baseline.py` does: mean absolute error in share points, and log score. Compare against the
  "naive" baseline (last year's shares).
- At county level, the set of listed counties changes every year. Say in the model card how you scored
  that, for example only counties listed in both years plus "other counties". Knowing which counties are
  listed in the held-out year is a small peek at that year; say so in the model card, and say how much of
  each year's releases went to counties listed for the first time (review).
- **Years used (decided):** the model learns from year-over-year changes, and FY2014 serves only as "last
  year" for FY2015 (the processed table has FY2014). So the first backtest fit (trained through FY2017) sees
  three changes, FY2014→15, 15→16 and 16→17; the last backtest fit sees ten, and the fit through FY2025 sees
  eleven. Record the count as `transitions` in each `diagnostics` entry.
- **Zero shares (decided):** a share of zero has no logarithm. Four state-years among the 51 places had no
  releases (Vermont FY2017, Alaska FY2018 and FY2020, Montana FY2019), and an "other counties" group can be
  zero too (Delaware FY2024). Before taking logs, add the same floor naive uses, `EPS` in
  `src/share_baseline.py` (0.0001 of a release), to every count at both levels, so ρ = 1, α = 0 gives
  exactly the naive forecast. Then refit the state model trained through FY2025 once with a floor of 0.5
  releases, record the posterior mean of ρ at both floors in `floor_check`, and say in the model card how
  much ρ moved.
- **Winner rule (decided), fixed before the backtest and applied to each level separately:** your model is
  used at a level only if all three hold:
  1. its release-weighted mean log score is higher than naive's;
  2. its equal-weighted mean log score is also higher than naive's;
  3. its log score is higher than naive's in at least 6 of the 8 held-out years.

  A difference smaller than 0.0005 (log score per child) counts as a tie, in the averages and in single
  years, and ties go to naive. MAE is reported but does not decide. With 8 years no rule can prove the model
  better (6 wins out of 8 happen by luck about 15% of the time); the rule only keeps a winner from being
  picked on noise. Copy this rule into `winner_rule`.
- **Pessimistic scoring (decided 2026-11-11).** The winner rule is applied three times, and your model is
  used at a level only if it passes all three:
  1. **Main** (`floor_0.0001`): scored as `src/share_baseline.py` scores, with the 0.0001 floor.
  2. **`floor_0.5`:** naive's forecast gets a floor of 0.5 of a release instead. Your model's forecast is
     not changed.
  3. **`zeros_left_out`:** places with no releases the year before are left out of that year's score for
     both methods, and each forecast is rescaled to add to 1 over the places that remain.

  Why: in FY2018–FY2021 one state a year had no releases the year before and 2 to 4 in the scored year.
  Under the main scoring those 12 children cost naive 0.0007 to 0.0024 of log score per child, more than the
  0.0005 tie, so a model could win those years on them alone. Write log scores with six decimals; the tests
  round each gap to six decimals before comparing it with 0.0005. List the three scorings in `scorings`.

**Writes:**

| File | Columns |
|---|---|
| `results/share_model_backtest.csv` | `fiscal_year, level, method, releases, mae_share_points, log_score`. Here `level` is `state` or `county`, and `releases` is the number of releases scored that year at that level. Include a `naive` row and your model's row for every held-out year and level. |
| `results/share_model_summary.csv` | `level, method, weighting, mae_share_points, log_score, years_beating_naive_mae, years_beating_naive_log`. One row per level × method × `weighting`, where `weighting` is `release` (weighted by `releases`, as `src/share_baseline.py` does) or `equal` (plain mean of the 8 years). The last two columns count the held-out years in which the method beat naive: lower MAE, or a log score higher by at least 0.0005 (review, decided). |
| `results/share_model_backtest_checks.csv` | `fiscal_year, level, method, scoring, releases, log_score` (decided 2026-11-11). The same years, levels and methods as the backtest file, scored under `floor_0.5` and under `zeros_left_out`. Under `zeros_left_out`, `releases` counts only the children in the places that are scored. |
| `results/share_model.json` | The model's record (review): see below. |

`share_model.json` makes the fit reproducible and shows that the sampler worked:

```json
{
  "model_method": "your method's name, as in the backtest",
  "winner_rule": "the winner rule above",
  "winner": {"state": "naive or your method's name", "county": "naive or your method's name"},
  "scorings": ["floor_0.0001", "floor_0.5", "zeros_left_out"],
  "first_lag_year": 2014,
  "floor": 0.0001,
  "floor_check": [
    {"level": "state", "trained_through": 2025, "floor": 0.0001, "rho_mean": 0.0},
    {"level": "state", "trained_through": 2025, "floor": 0.5, "rho_mean": 0.0}
  ],
  "priors": {"alpha": "...", "sigma": "...", "rho": "...", "kappa": "..."},
  "sampler": {"chains": 4, "draws": 1000, "tune": 1000, "target_accept": 0.9, "seed": 20261101},
  "diagnostics": [
    {"level": "state", "trained_through": 2017, "transitions": 3, "max_rhat": 1.0, "min_ess_bulk": 1000,
     "divergences": 0}
  ]
}
```

- `priors`: one entry per parameter, written out with its numbers (for example `"rho": "Normal(1, 0.25)"`).
  Use the math doc's names where they fit, and include the concentration `kappa`.
- `diagnostics`: one entry per fit. That is every backtest fit (`trained_through` 2017 to 2024) at both
  levels, plus the fits through 2025 that the scenario engine uses. Every fit must have R-hat at most 1.01,
  bulk effective sample size at least 400, and no divergences (Vehtari et al. 2021).
- `winner`: the method that won at each level under `winner_rule`: `model_method` if it passed under all
  three scorings, else `naive`. The tests recompute this from the backtest and the checks file.

Then update `docs/MODEL_CARD_share_model.md` with which method won and why. If the baseline wins, say so
plainly and make naive the shares the scenario engine uses. That is FR-12's acceptance condition.

## Week 6: scenario engine (FR-13, FR-14, FR-15)

**Code:** `src/scenarios.py`

- **Scenarios (FR-13):** `low`, `median` and `high` are the lowest, median and highest national release
  totals in FY2015–FY2025, from `data/processed/releases_by_fy_geo.parquet`. Record which fiscal year each
  one comes from.
- **Simulation (FR-14, decided):** in each draw, take next year's state shares θ from the share model,
  starting from FY2025's actual shares. Then count the scenario's N children out across the 51 places,
  x ~ Multinomial(N, θ), and count each state's x_s out across its county categories,
  Multinomial(x_s, φ), with φ from the county model. Do not multiply N by θ: that leaves out counting
  noise. In theory county ranges would then hold only about 70% of outcomes; measured on the fallback the
  difference is small (84% against 86%), and why is still being looked into (AS-24). N is the full national total,
  including the few releases to Puerto Rico and the Virgin Islands, which the counting spreads over the 51
  places. Report the mean of the draws as the expected value, and the 10th and 90th percentiles as the 80%
  range.
- **County categories (decided):** the counties listed in FY2025 (110 counties, in 34 states and the
  District of Columbia) plus one "other counties" group per state. A county listed only in earlier years
  has no FY2025 count to start from, so it stays inside "other counties". The District of Columbia is
  treated as a county (decided 2026-11-11): in the Week 1 table its one category is its county row, and
  its "other counties" is zero.
- **Fallback:** until Week 5 is validated, "last year's shares" with an error model is the BRD's allowed
  fallback (risk R-03). Say which one you used in `share_model`. If it is the fallback, describe the error
  model in `fallback_error_model`: how the ranges around last year's shares are made (review).
- **Two versions of the fallback, compared head to head (decided 2026-11-11).** With one κ for all 51
  places, the ranges held for about 83% of state-years but only about 60% for the 10 largest states, which
  receive about two thirds of children. Build both versions:
  - **(a)** one κ for all places;
  - **(b)** one κ for the large states and one for the other 41, each fitted on its own group's past misses.
    "Large" means the 10 states with the most releases in the training years, as in the calibration by
    state size below.

  Run both through the same calibration: the same held-out years, the same seed and the same number of
  draws. Write the comparison to `results/scenario_variant_comparison.csv` (below). Record the version the
  scenario tables use in `error_model_version` (`"a"` or `"b"`) and the reason in `version_choice`. The
  two calibration files describe that version.
- **Calibration (FR-14, NFR-10):** for each held-out year FY2018–FY2025, simulate from earlier years
  only, using that year's actual national total. Count how many states, and how many listed counties,
  landed inside their 80% range. A county is scored only if it would get a row: listed in both that year
  and the year before, and expecting 50 or more releases (fork, 2026-11-14). Pooled over the years, this should be about 80%; the test accepts
  70%–90%. That band is an operational tolerance, not a statistical test: states in the same year move
  together, so the 408 state-years are not independent checks.
- **Calibration by state size (review):** one κ for all states may fit the big states and the small ones
  differently. For each held-out year, report the state results separately for `large` states (the 10
  states with the most releases in the years that fit was trained on) and `small` states (the other 41),
  with the average width of the 80% range. If coverage differs a lot between the two, say in the model
  card what you changed, or why you kept one κ. The app shows these two figures next to the pooled one
  (decided 2026-11-11).
- **Service needs (FR-15):** at least `school_age`, from ORR's published age mix. The source is
  [ORR's UAC Age Data](https://acf.gov/orr/data/uac/age), an XLSX file of children in ORR care by age
  (published Oct 7, 2026). The copy is `data/raw/orr/UAC-Age-Data_Sep_2026_0.xlsx`, downloaded
  2026-11-04; record it in the README's data table.
  - ORR's ages describe children **in care**, not children released. Using them for released children is
    assumption A-03, so say so in the measure's definition.
  - **School-age fraction (decided).** The file's yearly table gives the share of children in care in each
    age group for FY2019–FY2025: 0–12, 13–14, 15–16 and 17+ (17+ includes the 0.13% found to be 18 after
    ORR's first evaluation). School age here means 5 to 17, and part of the 0–12 group is under 5, so

    f = share(13–14) + share(15–16) + share(17+) + λ × share(0–12), with 8/13 ≤ λ ≤ 1.

    ORR rounds the shares to two decimals (FY2021's add up to 1.01), so rescale each year's shares to add
    to 1 first.

    **λ for the point estimate (decided 2026-11-10)** comes from the file's FY2026 monthly table, which
    splits the group into 0–5 and 6–12 (children in care at each month's end). Sum the twelve months, and
    count age 5 as one sixth of 0–5, since ORR does not split that group:
    λ = (6–12 + 0–5 ÷ 6) ÷ (0–5 + 6–12) = (3,449 + 678 ÷ 6) ÷ 4,127 = 0.863.

    Record in `age_mix`: `lambda`, that value; `point_fiscal_years`, the year or years the point estimate
    uses; `school_age_fraction`, the point estimate (FY2025 alone gives 0.967); `low`, f with λ = 8/13 (ages
    spread evenly) in the year where that is lowest; and `high`, f with λ = 1 in the year where that is
    highest (every child counted, so 1.0) (review).
  - Optional extra measures, each needing a label and a definition:
    - post-release services referrals: [ORR post-release services](https://acf.gov/orr/data/uac-post-release-services)
    - primary language: [ORR primary language](https://acf.gov/orr/data/UAC-Primary-Language)
- **Guardrail (FR-19, NFR-03):**
  - A county gets its own row only if it is listed in FY2025 (decided) and its expected releases in that
    scenario are 50 or more. The test uses the national total × the county's starting share, which the
    average of the draws lands on, so the same counties are shown whatever the random seed (fork,
    2026-11-14).
  - Everything else in the state goes into one "other counties" row. Fold a listed county under 50 into
    it by adding its draws to the other-counties draws before taking the mean and percentiles.
  - Round every figure to whole children.
  - **One-county remainders (decided 2026-11-11).** If a state's "other counties" row covers exactly one
    county (the state's counties minus the county rows shown), the figure is that county's own. Write the
    row as usual so the totals add up; the app leaves it blank by itself (`one_county_remainders` in
    `src/scenario_contract.py`). With FY2025 as the base year this happens only for the District of
    Columbia in the low scenario.

**Writes three files to `results/`:**

`scenarios.json`:

```json
{
  "base_fiscal_year": 2025,
  "share_model": "Dirichlet-multinomial (Week 5)",
  "draws": 10000,
  "seed": 20261101,
  "range": [0.1, 0.9],
  "scenarios": [
    {"id": "low", "label": "Low", "national_releases": 0, "source_fiscal_year": 0},
    {"id": "median", "label": "Median", "national_releases": 0, "source_fiscal_year": 0},
    {"id": "high", "label": "High", "national_releases": 0, "source_fiscal_year": 0}
  ],
  "measures": [
    {"id": "releases", "label": "Children released to sponsors", "definition": "..."},
    {"id": "school_age", "label": "School-age children", "definition": "...which ages, and assumption A-03"}
  ],
  "age_mix_source": "ORR UAC Age Data, yearly table FY2019-FY2025 (published 2026-10-07), downloaded 2026-11-04",
  "age_mix": {"ages": "13-14, 15-16 and 17+, plus lambda x 0-12", "lambda": 0.8631, "point_fiscal_years": [2025],
              "school_age_fraction": 0.0, "low": 0.0, "high": 1.0},
  "fallback_error_model": "only if share_model is the fallback: how its ranges are made",
  "error_model_version": "a or b: the version the tables use",
  "version_choice": "why that version, from the comparison file"
}
```

`scenario_releases.csv` has one row per scenario × place × measure:

| Column | Meaning |
|---|---|
| `scenario` | `low`, `median` or `high` |
| `geo_level` | `state`, `county` or `other_counties` |
| `state`, `state_name` | two-letter code and full name |
| `county_key`, `county_fips`, `county_name` | as in the Week 1 table, on county rows (`county_fips` is blank for the four Connecticut counties). On other-counties rows, `county_key` and `county_fips` are blank and `county_name` is `Other counties, ST`. State rows leave all three blank. |
| `measure` | an `id` from `scenarios.json` |
| `expected`, `lower_80`, `upper_80` | mean, 10th and 90th percentile of the draws, whole children |

The state rows must add up to the scenario's national total. In each state, the county rows plus the
other-counties row must add up to the state row. Rounding can be off by up to 1%.

`scenario_calibration.csv` has the columns `fiscal_year, geo_level, places, inside_80, coverage`, with one
row per held-out year for `state` and for `county`.

`scenario_calibration_by_size.csv` (review) has the columns `fiscal_year, size_group, places, inside_80,
coverage, mean_width_share_points`, with one `large` and one `small` row per held-out year. The two rows
add up to that year's `state` row in `scenario_calibration.csv`. `mean_width_share_points` is the average
of (upper − lower) over the group's states, as shares × 100.

`scenario_variant_comparison.csv` (decided 2026-11-11) has the columns `version, size_group, places,
inside_80, coverage, mean_width_share_points, mean_interval_score`. It has one row per version (`a`, `b`)
and size group (`all`, `large`, `small`), pooled over the eight held-out years: 408, 80 and 328
state-years. The interval score of one state-year is the width of its 80% range plus 10 times any distance
by which the actual figure falls outside the range, in share points (10 is 2 ÷ 0.2). Lower is better: it
rewards ranges that are narrow and still hold (Gneiting and Raftery 2007).

## What the acceptance tests check

| Test | Requirement |
|---|---|
| Backtest has every held-out year, both levels, and the naive baseline | FR-12 |
| Scores are valid (MAE ≥ 0, log score ≤ 0, nothing missing) | FR-12 |
| Summary compares your model with the naive baseline at both levels | FR-12 |
| Summary matches the backtest: both averages and the years each method beat naive, with the 0.0005 tie (review, decided) | FR-12 |
| `share_model.json` records the winner rule, the winner, priors and sampler settings (review) | FR-12, NFR-07 |
| The winner is the one the fixed winner rule picks from the backtest, under all three scorings (decided, 2026-11-11) | FR-12 |
| The checks file covers every year, level and method, and naive's state scores in it match the data (decided 2026-11-11) | FR-12 |
| The floor matches naive's, and the 0.5-release refit is recorded (decided) | FR-11 |
| FY2014 is the first "last year": each fit's `transitions` = `trained_through` − 2014 (decided) | FR-11, FR-12 |
| Every fit has R-hat ≤ 1.01, bulk ESS ≥ 400 and no divergences (review) | FR-11 |
| Calibration is reported for large and small states, adding up to the state totals (review) | FR-14, NFR-10 |
| The school-age fraction uses λ from ORR's 0–5 / 6–12 split, and its low and high match ORR's file (review, decided) | FR-15, A-03 |
| A fallback share model says what error model it uses (review) | R-03 |
| Both fallback versions are in the comparison file for all, large and small states; the version used and the reason are recorded (decided 2026-11-11) | FR-14, NFR-10 |
| Scenario volumes are the lowest, median and highest years, with the right source years | FR-13 |
| The files pass every check in `src/scenario_contract.py` (format, ranges, sums, the 50-release rule) | FR-18, FR-19, NFR-03 |
| Every county shown is listed in FY2025 (decided) | FR-19, NFR-03 |
| Every place has a school-age figure, never more than its releases | FR-15 |
| Pooled 80% coverage is 70%–90% for states and for counties | FR-14, NFR-10 |

The app runs the same contract checks. If your files fail any of them, it shows the problem instead of the
numbers.
