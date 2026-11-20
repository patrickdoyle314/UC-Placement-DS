# Where Unaccompanied Children Are Placed

Where unaccompanied children were released to sponsors across U.S. states and counties,
FY2015–FY2025, and what a future rise in national volume would mean for local services
(schools, legal aid, case management). Service planning only.

**This repository is a fork.** It was made on November 14, 2026 from the project owner's working copy of
UC-Placement, at the owner's direction, so the scenario engine could be finished on schedule. The scenario
engine (`src/scenarios.py`), the share model (`src/share_model.py`) and their unit tests were built in this
fork. [How this was built](#how-this-was-built) gives the dates and the decisions behind them.

- Plan of record: [`docs/portfolio_plan_2026-10-20.docx`](docs/portfolio_plan_2026-10-20.docx)
- Problem statement (draft for approval): [`docs/problem_statement.md`](docs/problem_statement.md)
- Findings memo (concentration, stability, geography): [`docs/findings_memo.md`](docs/findings_memo.md)
- Spec for the share model and the scenario engine: [`docs/spec_share_model_scenarios.md`](docs/spec_share_model_scenarios.md)
- Assumptions register (every assumption, its status and a dated history): [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md)
- Math document (methods and mathematical principles, November 6 revision):
  [`docs/math_methods_and_principles_2026-11-06.pdf`](docs/math_methods_and_principles_2026-11-06.pdf)
- Changes: [`CHANGELOG.md`](CHANGELOG.md)

**Status:** data assembly, exploratory analysis, concentration and persistence, and geography are done.
The exploratory analysis was reviewed against the dataset and the BRD on its own: it now runs on the release
table alone and includes the per-year maps. The concentration measures were reviewed the same way: county concentration now counts counties one by one
(it had counted all unlisted counties as one place), and Lorenz curves and per-year transition matrices are
added. The app is built: the Streamlit app, its tests and a reshaping unit test. The scenario engine
is built in this fork (November 14, 2026) on the fallback the BRD allows: last year's shares with an error
model, in two versions compared head to head (AS-39 and AS-40 in
[`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md)). The app's Scenario tab now shows its tables; the results are
under [Scenario engine](#scenario-engine-results-on-the-fallback). The Bayesian share model was built in this fork on November 16
and tested against last year's shares. It did not beat them at either level, so the scenario tables keep last
year's shares ([Share model](#share-model-results)). All 20 acceptance tests now run and pass. FSO and contract-lead sign-off
is still pending.
This fork's repository was made public on November 16, 2026, at the project owner's direction, before that
sign-off was recorded (AS-38). The original's current work is kept in a separate private repository. A copy through v0.6.2 (the analysis and the app) is public at
[UC-Public](https://github.com/patrickdoyle314/UC-Public), released by the project owner on November 4, 2026.
The alignment notes with the MP project stay local and unpublished.


## Guardrails

These apply to every file, chart and write-up in this project:

1. **Public, aggregate data only.** No program data, internal knowledge, screenshots, or anything learned on the job.
2. **Service planning only.** Never framed as, or usable as, a tool for locating children, sponsors or households.
3. **Respect ORR's threshold.** Counties with fewer than 50 releases are not published, and their counts are never backed out.
4. **Neutral language.** "Unaccompanied children", "released to sponsors"; describe patterns, not blame.
5. **Counts are service needs,** not characteristics of the communities.

## Layout

```
UC-Placement/
  README.md, CHANGELOG.md
  docs/                 plan of record (.docx, kept local), problem statement, findings memo, model spec,
                        assumptions register, math document (PDF)
  src/build_dataset.py  dataset: reshape MPI data, add other-counties rows, join Census
  src/measure.py, src/share_baseline.py, src/run_sql.py   concentration measures, tiers, share baselines, SQL runner
  src/geography.py, src/build_findings_memo.py           geography: Moran's I, LISA, school-age comparison; memo
  src/scenario_contract.py  format and guardrail checks for the scenario engine's files
  src/scenarios.py      scenario engine (fallback): scenarios, error model, simulation, calibration
  src/share_model.py    Bayesian share model (PyMC): fits, backtest against naive, winner rule
  app/                  Streamlit app (streamlit_app.py) and its glossary (terms.py)
  notebooks/            exploratory notebook and its builder (needs only the release table)
  sql/                  SQL statements (DuckDB over parquet)
  results/              aggregate outputs
  tests/                pytest checks; tests/fixtures/ holds synthetic scenario files for the app tests
  data/raw/             downloaded sources (not committed; see Data)
  data/processed/       generated tables (not committed)
  exchange/             contract and export for adjacent projects (see Exchange)
  alignment/            local-only coincidence notes with the MP project (not committed)
```

## Reading the code

Every Python and SQL file from the data, exploration, concentration and geography steps opens with a **HOW TO READ THIS FILE** block: what the file does for the project
(business purpose), how it is laid out, and the Python ideas it uses. Comments through the code explain *why*
each step exists (for example, why "other counties" are never split) and point out Python, pandas and SQL
techniques where they first appear. A suggested reading order for learning Python: `src/build_dataset.py` →
`src/measure.py` (NumPy, pandas) → `sql/state_ranks.sql` (window functions) → `src/share_baseline.py` →
`tests/test_measure.py` (pytest) → `notebooks/build_eda.py`, whose comments also appear inside the
notebook's code cells → `src/geography.py` (GeoPandas, spatial statistics).

## Data

| Source | File | Notes |
|---|---|---|
| [Migration Policy Institute: Released to Sponsors by State and County, FY 2014–2025](https://www.migrationpolicy.org/data-tool/unaccompanied-children-state-county) | `data/raw/mpi/mpi-data-hub_uacsbystate-county-fy2014-fy2025.xlsx` (133,945 bytes, downloaded 2026-10-22) | Tabulation of ACF/ORR data. Counties listed only for years with ≥ 50 releases. First release location only. Includes FY2014, Puerto Rico and the U.S. Virgin Islands. Its county sheet has no row for the District of Columbia (see Results: the dataset). |
| [Census Bureau Vintage 2024 county estimates by age and sex](https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/counties/asrh/) | `data/raw/census/cc-est2024-agesex-all.csv` (8,723,627 bytes, downloaded 2026-10-22) | County FIPS codes; July 1, 2024 total and ages 5–17 population. Covers the 50 states and DC only. |
| Census ACS 5-year (language spoken at home) | — | Pending: needs a free Census API key, which you request yourself at api.census.gov. |
| [Census 2023 cartographic boundary files](https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html) (1:20,000,000) | `data/raw/geo/cb_2023_us_state_20m.zip`, `cb_2023_us_county_20m.zip` | State and county shapes for the maps and the app. |
| [ORR: Unaccompanied Alien Children age data](https://acf.gov/orr/data/uac/age) | `data/raw/orr/UAC-Age-Data_Sep_2026_0.xlsx` (16,414 bytes, published 2026-10-07, downloaded 2026-11-04) | Children in ORR care by age group: yearly shares for FY2019–FY2025 and FY2026 month-end counts. For the school-age fraction in the scenario engine (spec; AS-34 to AS-37). |

### Fiscal-year alignment

Every figure is placed on the federal fiscal year (October 1 – September 30):

| Source | Its own period | How it is aligned |
|---|---|---|
| MPI release counts | Federal fiscal year | Used as published. FY2015–FY2025 are analyzed. FY2014 is used only as the starting "last year" for FY2015 in the share model (AS-15). |
| Census Vintage 2024 estimates | July 1, 2024 (inside FY2024) | One fixed reference population for every fiscal year, not re-estimated year by year. |
| Census ACS 5-year (pending) | A five-calendar-year period | To be used the same way: a fixed reference, labeled with its period. |
| ORR age data (scenario engine) | Federal fiscal year | The engine uses the fiscal year it names in `results/scenarios.json`. |
| CBP encounters (optional, not used) | Monthly | Would be summed October through September. |

## Run

```bash
pip install -r requirements.txt   # SciPy, libpysal + esda (spatial statistics), matplotlib and python-docx (reporting)
python src/build_dataset.py          # the release table + reconciliation
python notebooks/build_eda.py        # exploratory notebook and its charts, including maps for every year
python src/measure.py                # concentration, Lorenz curves, persistence, tiers
python src/share_baseline.py         # share baselines and their backtest
python src/run_sql.py                # state ranks in SQL (DuckDB)
python src/geography.py              # Moran's I, LISA, school-age comparison (after src/measure.py)
python src/build_findings_memo.py    # findings memo, from the results tables
python src/share_model.py            # share model: 19 fits and the backtest against naive (about half an hour)
python src/scenarios.py              # scenario engine: scenario tables, calibration, version comparison
streamlit run app/streamlit_app.py   # the scenario app, in your browser
python exchange/export_exchange.py   # aggregates for adjacent projects
python alignment/align_mp.py         # optional, local only: coincidence checks with MP
```

## Measures, model and SQL

| Path | What it is |
|---|---|
| `src/measure.py` | pandas + NumPy: concentration (HHI, effective number, Gini, top-10 share, Lorenz) and persistence (Spearman, Kendall) by fiscal year; county size tiers and their Markov transition matrix; writes the parquet table |
| `src/geography.py` | GeoPandas + libpysal + esda + NumPy: global Moran's I (esda) and LISA clusters (states: releases per school-age child; counties: years listed), Moran's I by year, release share vs school-age share. LISA's permutation test is written in NumPy so that ties count on purpose and results don't change when numba is installed |
| `src/build_findings_memo.py` | Writes `docs/findings_memo.md` from the results tables, with the tier transition chart |
| `src/share_baseline.py` | Share model, baseline stage: next year's state shares from last year, a 3-year mean, or all years pooled, backtested |
| `docs/MODEL_CARD_share_model.md` | Model card: data, baselines and scores, the planned Bayesian model, limitations |
| `sql/state_ranks.sql` | SQL with CTEs and window functions (`RANK`, `LAG`, running `SUM`) over the parquet table |
| `src/run_sql.py` | Runs a SQL file with DuckDB, saves the result in `results/` |
| `src/scenario_contract.py` | What the scenario engine's files must contain, and the checks the app runs before showing them |
| `app/streamlit_app.py` | Streamlit + Plotly app: scenario selector, state and county maps, tables with 80% ranges, history, definitions |
| `tests/` | pytest: metric checks, the reshaping step on made-up counties, reconciliation, SQL matches pandas, tiers, Moran's I, clusters, school-age ratio, the exploratory notebook's BRD checks, county concentration bounds and the concentration measures' BRD checks, the app (Streamlit's AppTest), and acceptance tests for the share model and scenario engine that skip until those outputs exist |
| `results/` | Outputs (aggregate, from public MPI data) |

```bash
python src/measure.py
python src/share_baseline.py
python src/run_sql.py
python src/geography.py
python src/build_findings_memo.py
python -m pytest
```

## Share model: results

`python src/share_model.py` fits a Bayesian Dirichlet-multinomial model with PyMC and tests it against
"same shares as last year" (naive). Each held-out year FY2018–FY2025 is predicted by a model fitted on
earlier years only: 19 fits, about half an hour.

**Result: last year's shares win at both levels, so the scenario tables keep them (FR-12).**

| Level | Method | Log score, release-weighted | Log score, equal-weighted | Mean absolute error (share points) | Years it beat naive |
|---|---|---|---|---|---|
| State | Last year's shares (naive) | -3.1678 | -3.1624 | 0.212 |  |
| State | Share model | -3.1679 | -3.1626 | 0.216 | 4 of 8 |
| County | Last year's shares (naive) | -1.8632 | -1.7631 | 1.824 |  |
| County | Share model | -1.8624 | -1.7623 | 1.825 | 4 of 8 |

Log-score gap by held-out year, model minus naive (a gap under 0.0005 is a tie):

| Year | States | Counties |
|---|---|---|
| FY2018 | +0.0026 | +0.0022 |
| FY2019 | -0.0063 | -0.0014 |
| FY2020 | +0.0006 | +0.0013 |
| FY2021 | -0.0012 | +0.0004 |
| FY2022 | -0.0003 | -0.0006 |
| FY2023 | +0.0018 | +0.0020 |
| FY2024 | +0.0027 | +0.0028 |
| FY2025 | -0.0014 | -0.0004 |

- **The rule, fixed before the backtest (AS-20).** The model is used only if both of its average log scores
  beat naive's and it wins at least 6 of the 8 years, with gaps under 0.0005 counted as ties. It won
  4 years for states and 4 for counties.
- **States.** The model is slightly worse on average (-0.0001 per child, release-weighted). Its worst
  year is FY2019 (-0.0063).
- **Counties.** The model is slightly better on average (+0.0008), but in only 4 of
  the 8 years, which the rule treats as noise.
- **Pessimistic scorings.** The outcome is the same under all three. With naive floored at half a release, the
  model's FY2020 state win disappears (3 wins instead of 4). With places that had no
  releases the year before left out instead, it stays a win by a hair (+0.0005).
- **What the model learned.** ρ came out at 0.92 to 0.94 for states and
  0.94 to 0.95 for counties: a mild pull back toward each place's usual
  share. The pull is real in the training years but did not make the next year's forecast reliably better.
- **Sampler checks.** Every fit passed: largest R-hat 1.0062 (limit 1.01), smallest bulk
  effective sample size 1,076 (limit 400), no divergences. Settings: 4
  chains, 2,000 tuning and 2,000 kept draws each, target acceptance 0.95.
- **Floor check (AS-14).** Refitting with a floor of half a release moved ρ from 0.915 to 0.931.
- **County scoring.** In each state the categories are the counties listed in both years plus "other
  counties"; states with only "other counties" are skipped. Scores are pooled over the scored states
  (15,044 to 126,929 releases a year). Knowing the held-out
  year's list is a small peek at that year (AS-16).
- **Checks.** `tests/test_share_model.py` works the scoring and the winner rule by hand, and fits the model
  to made-up data to confirm it recovers a known ρ and κ.

## Scenario engine: results on the fallback

`python src/scenarios.py` writes the scenario tables the app shows (about 30 seconds). It runs on the
fallback the BRD allows (risk R-03): next year's expected shares are FY2025's actual shares, and an error
model sets the ranges around them (AS-39). The share model did not beat last year's shares, so this is also
what the winner rule picks.

| Scenario | National releases | Year it comes from | Texas: expected (80% range) | County rows | In "other counties" |
|---|---|---|---|---|---|
| Low | 24,259 | FY2025 | 3,429 (3,121 to 3,745) | 110 | 34.9% |
| Median | 52,267 | FY2016 | 7,398 (6,754 to 8,061) | 110 | 34.9% |
| High | 127,512 | FY2022 | 18,012 (16,431 to 19,641) | 110 | 34.9% |

FY2020 (16,864 releases) is set aside as far outside the usual range (AS-45, the owner's decision of
2026-11-18): it is not a scenario, and the changes into and out of it do not set κ. Low is therefore FY2025's
own total, and its expected figures are FY2025's actual counts.

- **Simulation.** Each of 10,000 simulated years draws the states' shares around FY2025's, counts the
  scenario's children out across the 51 places, and does the same inside each state for its FY2025-listed
  counties and one "other counties" group. Expected is the average of the draws; the 80% range runs from
  their 10th to their 90th percentile.
- **Error model.** One number, κ, says how far shares really moved from one year to the next in
  FY2014–FY2025, leaving out the two changes that touch FY2020. A smaller κ means wider ranges. It is fitted
  with every place weighted equally.
- **Two versions, compared head to head (AS-40).** Each held-out year FY2018–FY2025 was replayed from
  earlier years only, with the same seed for both versions:

  | Version | State-years | 80% range held | Mean width (share points) | Mean interval score (lower is better) |
  |---|---|---|---|---|
  | (a) one κ for all states | all 408 | 82.4% | 0.610 | 1.131 |
  |  | 10 largest states, 80 | 58.8% | 1.406 | 3.688 |
  |  | other 41 states, 328 | 88.1% | 0.416 | 0.508 |
  | (b) one κ for the 10 largest states, one for the rest | all 408 | 83.1% | 0.685 | 1.029 |
  |  | 10 largest states, 80 | 76.2% | 2.021 | 3.210 |
  |  | other 41 states, 328 | 84.8% | 0.359 | 0.497 |

  The tables use **version (b)**. The engine takes the version with the lower mean interval score among those
  whose pooled coverage is 70% to 90%; a tie goes to (a). Fitted on the nine changes that do not touch FY2020,
  κ is 1,228 for the 10 largest states and 3,698 for the other 41 (one κ for all
  would be 2,650), and 459 for counties.
- **What the comparison does not settle.** Under (b), 76.3% of children were in a state whose range
  held (63.5% under (a)), but California's range held in only 3 of the 8 years.
  Coverage also changes from year to year: from 69% of states in FY2018 to
  96% in FY2022. The same replay picks the version, so its coverage is not
  an independent check.
- **Counties.** The ranges held for 85.7% of the 1,345 county-years scored: counties
  listed in both years and expecting 50 or more releases.
- **School-age children.** Releases × 0.967, from ORR's FY2025 age mix of children in
  its care. The fraction could be as low as 0.908 or as high as 1.0 (AS-34 to AS-37).
- **50-release rule.** A county gets a row only if it was listed in FY2025 and expects 50 or more releases in
  the scenario; otherwise it is inside its state's "other counties" figure. At the three scenario volumes
  all 110 listed counties expect 50 or more, so none is folded. Whether a county expects 50 is
  worked out before any random draw, so the same counties are shown whatever the seed (AS-26). An "other
  counties" figure that covers one county would be left blank by the app (AS-41); no scenario has one now.
- **Checks.** `tests/test_acceptance.py` checks the files. `tests/test_scenarios.py` checks the steps on
  made-up data, including that the κ fit finds a known κ again (within 15%).

## The scenario app

`streamlit run app/streamlit_app.py` opens the app in a browser. A planner picks a national volume scenario (Low,
Median or High, each one a real year's national total from FY2015–FY2025) and a state. The app then shows:

- **Scenario:** state and county maps of expected releases or school-age children, and sortable tables with the
  expected value and the 80% range for every state, listed county and state "other counties" figure. It also
  shows how often the ranges held the actual figure in backtests: for all states, and separately for the 10
  largest states and the other 41, since one pooled figure can hide a gap between them.
- **History:** published counts for any fiscal year on state and county maps, the national or state trend, and
  how many of the 11 years each county was listed (steady or changing need).
- **Definitions:** a plain-language glossary. Every table column also has its own help text.
- **About and guardrails:** purpose, guardrails, limits, and how the app was built.

Guardrails are enforced in code, not only stated:

- The app runs `src/scenario_contract.py` on the scenario files before drawing anything. If a check fails, for
  example a county with fewer than 50 expected releases shown by itself, the app shows the problem instead of
  the numbers.
- The History tab shades a county only in years it was published (50+ releases).
- An "other counties" figure that would cover a single county is left blank, because it would be that
  county's own number (AS-41).

The tests run the app on synthetic scenario files in `tests/fixtures/scenarios/`, which are made up and describe
nothing real. They check that:

- choosing a scenario refreshes every table;
- no county under 50 is shown by itself;
- every column is defined;
- files that fail the checks are not shown.

The same per-year maps are saved as images by the exploratory notebook (see Results: exploratory analysis).

## Results: geography

Full memo with charts and methods: [`docs/findings_memo.md`](docs/findings_memo.md). Check-in question:
*is the pattern stable enough that last year predicts next year?*

1. **States, yes.** Year-to-year state rank correlations are 0.985 or higher in FY2015–FY2025 (0.983 from FY2014
   to FY2015, a pair the share model also uses), and "last year's shares" misses each
   state's share by 0.21 percentage points on average, the best of three simple rules.
2. **Counties: steady places, moving counts.** How many counties clear the 50-release threshold follows national
   volume (73 listed in FY2020, 339 in FY2022, 110 in FY2025); a 1,000+ county stays 1,000+ the next year 58% of the time.
3. **Releases cluster.** Moran's I is 0.48 for state release rates per school-age child and 0.41 for how often
   counties are listed (both p = 0.0001), and every single year is significant. Eight county clusters (the largest
   runs from Prince George's County, MD to Suffolk County, NY) received 51% of all FY2015–FY2025 releases. Of the
   152 High-High counties, 59 pass a false-discovery-rate correction. That figure was 105 before the
   November 10, 2026 fix to how ties are counted, and 58 before the District of Columbia was counted as a county
   on November 11 (see the CHANGELOG).
4. **Compared with school-age population,** listed counties took 1.4–2.0 times their share each year. 71 counties
   were listed every year; the 70 with a Census population figure received 59% of releases and have 31% of the
   nation's school-age children.

## Results: concentration and persistence

`src/measure.py` (pandas, NumPy) reads only the release table and writes its tables to `results/` for every fiscal
year (BRD FR-07, FR-08). The **effective number** (1 / HHI) reads "as concentrated as if releases were spread
evenly over this many places": higher means more spread out.

| Fiscal year | States: effective number | States: top-10 share | Listed counties | Counties: effective number (at least) | Counties: top-10 share | Unlisted counties' share |
|---|---|---|---|---|---|---|
| FY2015 | 14.7 | 72% | 109 | 71 | 29% | 26% |
| FY2016 | 13.5 | 75% | 157 | 60 | 33% | 17% |
| FY2017 | 13.6 | 74% | 139 | 63 | 31% | 20% |
| FY2018 | 14.9 | 70% | 125 | 82 | 26% | 26% |
| FY2019 | 14.8 | 72% | 227 | 75 | 27% | 14% |
| FY2020 | 14.5 | 71% | 73 | 76 | 26% | 36% |
| FY2021 | 15.6 | 70% | 299 | 88 | 24% | 12% |
| FY2022 | 15.3 | 69% | 339 | 88 | 24% | 10% |
| FY2023 | 16.4 | 67% | 335 | 107 | 22% | 12% |
| FY2024 | 17.3 | 64% | 323 | 132 | 19% | 15% |
| FY2025 | 16.5 | 65% | 110 | 112 | 21% | 35% |

1. **Concentration** (`concentration_by_year.csv`, Lorenz curves in `lorenz_by_year.csv` and
   [`results/figures/lorenz.png`](results/figures/lorenz.png)). Releases are concentrated, and the
   concentration has eased slowly for both states and counties. The Gini coefficient is 0.61–0.69 for states
   and 0.39–0.61 among listed counties.
   - **States:** the largest fifth of states received 64%–76% of children each year, and the smaller half 7%–10%.
   - **Counties:** the county curves and Gini cover listed counties only, and the number listed swings with
     volume. They look flattest in FY2020 and FY2025, when only 73 and 110 counties reached 50 releases and
     the listed set held only larger counties. So compare county curves across years with care, and use the
     effective numbers above for trends.
2. **How counties are counted.** Counties under 50 releases are not published, and they are never split or
   estimated. Each of them had at most 49 releases, which limits how much they can add, so county HHI is a
   narrow range (`hhi_low` to `hhi`). The effective numbers above are the low end of that range. The ten largest
   counties are always listed, so their share is exact.
3. **Persistence** (`persistence_state_ranks.csv`, `persistence_county_ranks.csv`). Year-to-year rank
   correlations of state shares are Spearman 0.985–0.996 and Kendall 0.910–0.962 (FY2015–FY2025; from FY2014 to
   FY2015, a pair the share model also uses, they are 0.983 and 0.906). Among the 73–311 counties
   published in both years of a pair, they are Spearman 0.877–0.968 and Kendall 0.699–0.857.
4. **Tiers** (`tier_transitions.csv` pooled; `tier_transitions_by_year.csv` for each pair of years). A county
   with 1,000+ releases stays 1,000+ the next year 58% of the time; one with 50–199 falls below the threshold 34%
   of the time.

## Results: exploratory analysis

[`notebooks/eda.ipynb`](notebooks/eda.ipynb), built and run by `notebooks/build_eda.py` (pandas,
matplotlib, GeoPandas with Census 2023 cartographic boundaries). Charts are also in `results/figures/`.
It reads only the release table and the raw boundary files, so it runs right after `src/build_dataset.py`.

**Review question:** do county rows plus "other counties" match each state total? Yes. The notebook checks
this again before any finding: all 583 state-years in FY2015–FY2025 match (50 states, DC, Puerto Rico, the
Virgin Islands), and states add up to the national total in all 11 years.

Five findings, FY2015–FY2025 (BRD FR-05):

1. National releases ranged from 16,864 (FY2020) to 127,512 (FY2022); FY2021–FY2024 hold 62% of all releases, and
   FY2025 fell to 24,259, 76% below FY2024.
2. The six largest receiving states (TX, CA, FL, NY, MD, NJ) took 53% of releases; Texas's share stayed between
   11.7% and 14.9%, and year-to-year state rank correlations never fell below 0.985 (FY2017 to FY2018). FY2014 to
   FY2015, which the share model also uses, is 0.983.
3. The 20 largest receiving counties took 34% of releases; Harris County, TX received the most children in 9 of
   11 years, and all 20 were listed (50+ releases) every year.
4. Listed counties ranged from 73 (FY2020) to 339 (FY2022) and held 63%–90% of releases; the rest are the
   unlisted "other counties" group, never split further.
5. Per school-age child (ages 5–17, 2024), the highest totals were in Maryland (36 per 1,000), DC (31) and
   Virginia (26), and the lowest in Hawaii, Vermont and Alaska. 390 of the 394 listed counties are on the county map (4 Connecticut
   counties have no FIPS match; Alaska, Hawaii and Puerto Rico are left off the maps).

State and county maps for every fiscal year, on one shared color scale (BRD FR-06):
[`results/figures/state_maps_by_year.png`](results/figures/state_maps_by_year.png) and
[`results/figures/county_maps_by_year.png`](results/figures/county_maps_by_year.png). County panels
shade only published counts (50+ releases).

## Results: the dataset

`src/build_dataset.py` writes:

- **`data/processed/releases_by_fy_geo.csv`**: 3,684 rows, one per fiscal year × geography:
  12 national, 636 state (50 states, DC, PR, VI), 2,400 county, 636 "other counties".
  Columns: `fiscal_year, geo_level, state, state_name, county_fips, county_name, county_key, releases,
  listed_counties, pop_total_2024, pop_5_17_2024, unlisted_counties, publishable`.
- **`data/processed/reconciliation.csv`**: 648 checks, **all pass**. For every state and year, listed
  counties plus "other counties" equal the state total. For every year, states sum to the national total.
- **`data/processed/county_fips_unmatched.csv`**: 390 of 394 counties matched to a FIPS code (MPI's 393 and the
  District of Columbia). The 4
  unmatched are Connecticut counties (Fairfield, Hartford, New Haven, New London): since 2022 the Census
  reports Connecticut by planning region, not county.

Findings for the plan:

- The MPI file **includes FY2014** (53,515 releases); the plan's data table lists it as unavailable.
- MPI's national totals include Puerto Rico and the U.S. Virgin Islands (together 0–9 releases a year, none
  in FY2014–FY2016 or FY2021); both are kept as state-level rows so the totals reconcile.
- 15 state-year cells are blank in MPI's States sheet (Alaska FY2018 and FY2020, Montana FY2019, Vermont
  FY2017, Puerto Rico in 4 years, the Virgin Islands in 7). They count as 0 releases, as in MPI's own
  FY 2014–2025 total column; read that way, the states add up to the national total in every year.
- Census population is one reference year (July 1, 2024) on every row. Puerto Rico and the Virgin Islands
  have no population in this file.
- MPI's county sheet has no row for the **District of Columbia**, which it reports as a state. DC is one
  county-equivalent, and it had 50 or more releases in every year but FY2020 (48). It therefore gets a county
  row from its state total in those years (AS-42). Without the row it counted as a county that never reached
  the threshold.
- A state's "other counties" figure sometimes covers a **single county**: Delaware in FY2019, FY2021, FY2022
  and FY2023 (two of its three counties were listed) and DC in FY2020. That figure is the one county's own
  count, which ORR withheld. Those five rows stay in the table so totals add up, marked
  `publishable = False`; the exchange file flags them and the app leaves them blank (AS-41).
- The plan says to join ACS county data. Total and school-age population come from the Vintage 2024
  estimates above, which need no API key; the ACS join (language spoken at home) is pending (see Data).

## Limitations

Every assumption behind the analysis and the model, with its status and a dated history of changes, is in
[docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md).

- **First release location only.** A child is counted in the county where they were first released to a
  sponsor; later moves are not tracked.
- **Small counties are not published.** Counties with fewer than 50 releases in a year appear only inside their
  state's "other counties" figure, and nothing is estimated for them. Every county-level result therefore covers
  listed counties only, which leans toward large counties. A methods note on this is an optional item, not yet
  written.
- **One reference population.** Every year uses the July 1, 2024 Census estimates. Puerto Rico and the Virgin
  Islands have none in that file.
- **Connecticut.** Its four listed counties have no current Census FIPS code (the Census now reports Connecticut
  by planning region), so they have no population and are not drawn on maps. They do appear in tables.
- **Scenarios are not forecasts.** Low, Median and High are past national totals. The scenario engine assumes
  the historical pattern of where children are released holds at those volumes; if it shifts, the ranges will be
  too narrow.
- **Service needs are approximate.** School-age figures will use ORR's national age mix for children in its care,
  which may differ from the children released to a given place.
- **Language spoken at home** (ACS) is not yet included.
- **Source revisions.** MPI and ORR can revise published figures. Each downloaded file is listed above with its
  date.
other's; no raw records cross. From MP, only **child** measures are used. Adult measures
(ages 18–25) are kept apart and never enter child comparisons.

## Alignment notes (local only)

`alignment/` holds the coincidence log between the two projects
([`alignment/README.md`](alignment/README.md)) and the script that produces it. It is excluded through
`.git/info/exclude` and is not part of this project's deliverables until sign-off covers it.
