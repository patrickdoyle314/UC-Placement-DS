# Assumptions register

Every assumption the project rests on, in one place. It is updated whenever an assumption is added,
changed or settled: the row changes in place, and the **History** at the bottom keeps what it used to say.

- **ID:** this register's own number (AS-xx). Where the business requirements document (BRD, kept local)
  has a matching item, its ID is given too (A-xx assumption, R-xx risk).
- **Status:**
  - **Decided**: the project owner confirmed it (date given).
  - **Design**: part of the method in the math doc or the spec, not separately confirmed.
  - **Data**: how a source is read.
  - **Open**: not settled yet.
- **Where:** the math doc's section ("§"), the spec (`docs/spec_week5_week6.md`) or the code.

The guardrails (public aggregate data only, service planning only, ORR's 50-release threshold, neutral
language) are rules rather than assumptions; they are in the README.

## Data

| ID | Assumption | Evidence, or what happens if it is wrong | Where | Status |
|---|---|---|---|---|
| AS-01 | MPI's file is a faithful tabulation of ORR's published release counts, and it stays available (A-01). | State and county totals reconcile to the file every year (data build checks). If it disappears, rebuild from ORR's web tables. | §2, `src/build_dataset.py` | Data |
| AS-02 | A release is counted where the child was first released to a sponsor; later moves are not tracked. | A property of the source. Counts describe first placements, not where children live now. | §13, README Limitations | Data |
| AS-03 | Every source is aligned to the federal fiscal year (October to September). | MPI and ORR report by fiscal year; Census is a fixed reference. | README Data | Data |
| AS-04 | A county missing from a year's list had 0 to 49 releases. It sits inside "other counties" (state total minus listed counties) and is never estimated (R-05). | ORR's publication threshold. County results therefore cover listed counties only, which leans toward large counties. | §2, §9 | Data |
| AS-05 | One reference population for every year: Census Vintage 2024 county estimates (July 1, 2024), ages 5–17. | The BRD (A-04) named ACS 5-year estimates; the project uses Vintage 2024 instead. Puerto Rico and the Virgin Islands have no figures in it. | Week 4 school-age ratio, README | Data |
| AS-06 | Connecticut's four listed counties stay in the tables without population figures or map shapes. | The Census now reports Connecticut by planning region, so those counties have no current FIPS code. | README Limitations | Data |
| AS-07 | "States" means the 50 states and DC (51 places). Puerto Rico and the Virgin Islands are left out of the share model but stay in the national total. | Together they had 0 to 9 releases a year, and 11 of their 22 state-years had none. | §2, §10 | Design |

## Share model

| ID | Assumption | Evidence, or what happens if it is wrong | Where | Status |
|---|---|---|---|---|
| AS-08 | Expected releases = national volume × a place's share. Volume is a scenario, not a forecast; only shares are modeled. | Volume swung 7.6-fold (16,864 in FY2020 to 127,512 in FY2022) with policy and events. | §1 | Design |
| AS-09 | Past shares inform future ones (A-02). | State rank correlation is 0.985 or higher every year, and "same as last year" misses by 0.212 share points. A policy change could still move shares more than any past year did. | §3, §4, §13 | Design |
| AS-10 | Shares themselves vary from year to year, more than counting noise, so the model is Dirichlet-multinomial. | For the largest states, shares move about 4 to 7 times more than counting noise alone (in standard deviation). | §4, §5 | Design |
| AS-11 | One concentration κ for all states. | Large and small states may vary differently; calibration is reported separately for the 10 largest states and the other 41 to check it. | §5, spec | Design |
| AS-12 | Expected shares = softmax(α + ρ × log last year's shares). ρ = 1 and α = 0 give naive. | Lets the fit fall back on naive; the backtest decides. | §6 | Design |
| AS-13 | Priors: α a zero-sum normal with its own spread σ; ρ centered at 1; κ on the log scale, from the tens to the tens of thousands. | Exact numbers are recorded in `results/share_model.json`. | §7, spec | Design |
| AS-14 | A share of zero gets a floor of 0.0001 releases before taking logs, the same as naive. A refit with a floor of 0.5 releases checks that ρ barely moves. | Four state-years had no releases (VT FY2017, AK FY2018 and FY2020, MT FY2019), and one "other counties" group (DE FY2024). | §6, spec, tests | Decided 2026-11-08 |
| AS-15 | FY2014 serves only as "last year" for FY2015. | The first backtest fit sees three year-over-year changes instead of two. | §7, §8, spec, tests | Decided 2026-11-08 |
| AS-16 | In the backtest, a year's county categories are the counties listed in both that year and the year before, plus "other". | Knowing year t's list is a small peek at year t: counties new to the list took 0% to 26.5% of releases (5.5% on average). | §9, spec | Design |
| AS-17 | The county model shares one ρ, one κ and one "other" offset across all states. | More than half of the 393 counties are listed in 5 or fewer of the 11 years, too few to estimate each one's own tilt. | §9 | Design |
| AS-18 | The county model's mean has no term for each county's long-run share. | If the county ρ comes out below 1, counties within a state are pulled toward equal shares. Raised in Claude's theory review on 2026-11-06; not in the math doc. | §9 | Open |

## Backtest and the winner

| ID | Assumption | Evidence, or what happens if it is wrong | Where | Status |
|---|---|---|---|---|
| AS-19 | Each held-out year, FY2018 to FY2025, is predicted from earlier years only. | Prevents leakage. The BRD's "leave-one-year-out" (R-04) would also train on later years, so FR-12's forward-only rule is followed. | §8, §11 | Design |
| AS-20 | Winner rule: the model is used at a level only if its release-weighted and equal-weighted mean log scores both beat naive's and it wins at least 6 of the 8 years. A gap under 0.0005 per child is a tie, and ties go to naive. MAE does not decide. | With 8 years nothing can prove the model better: 6 wins of 8 happen by luck about 15% of the time. The rule only guards against picking a winner on noise. | §8, spec, tests | Decided 2026-11-08 |
| AS-21 | The log score is the judge. | It is a proper scoring rule, so hedging or false confidence cannot game it. It judges expected shares only; ranges are checked by calibration. | §3 | Design |

## Scenario engine

| ID | Assumption | Evidence, or what happens if it is wrong | Where | Status |
|---|---|---|---|---|
| AS-22 | The scenarios are the lowest, median and highest national totals of FY2015–FY2025: 16,864 (FY2020), 52,267 (FY2016) and 127,512 (FY2022). | They are planning volumes, not forecasts, and Low is not a floor: October 2025 had 106 releases, a pace of about 1,300 a year (R-06). Shares were learned at 17,000 to 128,000 a year and are untested far below that. | §10, §13 | Design |
| AS-23 | Next year starts from FY2025's actual shares. | The most recent published year. | §10, spec | Design |
| AS-24 | Children are counted out of each draw's shares (multinomial), not N × shares. | Multiplying leaves out counting noise; county ranges would then hold only about 70% of outcomes (65% near 50 releases). | §10, spec | Decided 2026-11-08 |
| AS-25 | Only the 109 counties listed in FY2025 (34 states) can get their own row. A county listed only in earlier years stays in "other counties". | Such a county has no FY2025 count to start from. In the high scenario, "other counties" holds about 35% of releases, against 11% in FY2022. | §9, §12, §13, spec, tests | Decided 2026-11-08 |
| AS-26 | A listed county under 50 expected releases is folded into "other counties" by adding its draws there before the mean and percentiles are taken. | Keeps ORR's threshold in every scenario (FR-19, NFR-03). | §10, §12, spec | Design |
| AS-27 | The 80% range runs from the 10th to the 90th percentile of 10,000 draws, with a fixed seed (20261101). | Reproducible (NFR-07). | §10, spec | Design |
| AS-28 | Calibration passes if pooled coverage is 70% to 90%. | An operational tolerance, not a statistical test: states in the same year move together, so the 408 state-years are not independent checks (independent checks would give 76% to 84%). | §11, spec, tests | Design |
| AS-29 | "Large" states are the 10 with the most releases in each fit's training years; the other 41 are "small". | Used only to report calibration by size. | spec | Design |
| AS-30 | Figures are rounded to whole children; a sum of rounded parts may be off by up to 1% or 2 children. | Largest-remainder rounding would keep sums exact. | §12, `src/scenario_contract.py` | Design |

## Service needs (school-age children)

| ID | Assumption | Evidence, or what happens if it is wrong | Where | Status |
|---|---|---|---|---|
| AS-31 | ORR's national age mix applies to every place (A-03). | Local age mixes may differ; school-age figures carry error the ranges do not include. | §12, §13 | Design |
| AS-32 | The ages of children in ORR's care stand in for the ages of children released. | Teens who turn 18 in care are not released, so the mix slightly overstates 17-year-olds; ORR's 17+ group also includes the 0.13% found to be 18 after its first evaluation. | §12, spec | Design |
| AS-33 | School age means 5 to 17. | Matches the Census ages 5–17 used for the Week 4 school-age ratio. | §12 | Design |
| AS-34 | School-age fraction f = share(13–14) + share(15–16) + share(17+) + λ × share(0–12), from ORR's yearly table (FY2019–FY2025), each year rescaled to add to 1. | ORR rounds to two decimals; FY2021's shares add up to 1.01. | §12, spec, tests | Decided 2026-11-08 |
| AS-35 | λ, the part of the 0–12 group aged 5 to 12, is 0.863 for the point estimate: (6–12 + one sixth of 0–5) ÷ (0–5 + 6–12), from ORR's FY2026 month-end counts summed over the year (3,449 and 678). Age 5 is taken as one sixth of 0–5, since ORR does not split that group. | ORR's own split, instead of assuming ages are spread evenly (8/13 = 0.615). The monthly values run from 0.844 to 0.896. Assumes FY2026's split within 0–12 also holds for the years the point estimate uses. | §12, spec, tests | Decided 2026-11-10 |
| AS-36 | The range for f runs from λ = 8/13 in the year where f is lowest (0.908) to λ = 1 (1.0, every child counted). | The high end counts children under 5 as school age, so it is an upper bound, not a likely value. | §12, spec, tests | Decided 2026-11-08 |
| AS-37 | Which year or years the point estimate of f uses. | FY2025 alone gives 0.967. Recorded as `point_fiscal_years` in `results/scenarios.json`. | spec | Open: chosen when `src/scenarios.py` is written |

## Project

| ID | Assumption | Evidence, or what happens if it is wrong | Where | Status |
|---|---|---|---|---|
| AS-38 | Approvers are available, and FSO and contract-lead sign-off is recorded before anything is published (A-05, NFR-06). | Not yet recorded. | BRD, README | Open |

## History

Newest first. Each line says what changed and which files were updated with it.

- **2026-11-10:**
  - AS-35 changed: λ for the point estimate went from 8/13 (ages spread evenly) to 0.863 (ORR's FY2026 split of 0–5 and 6–12). Updated in the spec, the acceptance tests and math doc §12.
  - The ORR age file was recorded as downloaded (2026-11-04, now in `data/raw/orr/`).
  - This register was started.
- **2026-11-08:**
  - The owner confirmed AS-14 (floor), AS-15 (FY2014 as the first "last year"), AS-20 (winner rule), and AS-34 and AS-36 (school-age fraction; λ was then 8/13 for the point estimate).
  - AS-24 (counting out) and AS-25 (FY2025-listed counties) were adopted from the revised math doc.
  - All of these are written into the spec and the acceptance tests.
- **2026-11-06:**
  - The math doc was revised for the outside reviewer's comments. That revision added AS-07 (Puerto Rico and the Virgin Islands), proposed AS-14, AS-15, AS-20, AS-24, AS-25 and AS-34, and stated the low scenario's limits (AS-22).
  - AS-18 was raised in Claude's own review and left out of the doc.
- **2026-11-05:** after an outside review, the spec added calibration by state size (AS-11, AS-29), the school-age range, and the fallback's error model.
- **2026-10-31:** BRD v0.2 listed A-01 to A-05 (AS-01, AS-09, AS-31, AS-05, AS-38). The project replaced ACS 5-year estimates with Census Vintage 2024 for population (AS-05).
