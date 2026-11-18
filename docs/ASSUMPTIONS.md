# Assumptions register

This copy belongs to the fork made on 2026-11-14, where the scenario engine and the share model were built with AI assistance.
Rows changed in the fork say so, and the History has an entry for it.

Every assumption the project rests on, in one place. It is updated whenever an assumption is added,
changed or settled: the row changes in place, and the **History** at the bottom keeps what it used to say.

- **ID:** this register's own number (AS-xx). Where the business requirements document (BRD, kept local)
  has a matching item, its ID is given too (A-xx assumption, R-xx risk).
- **Status:**
  - **Decided**: the project owner confirmed it (date given).
  - **Design**: part of the method in the math doc or the spec, not separately confirmed.
  - **Data**: how a source is read.
  - **Open**: not settled yet.
- **Where:** the math doc's section ("§"), the spec (`docs/spec_week5_week6.md`) or the code. The math doc
  is [`math_methods_and_principles_2026-11-06.pdf`](math_methods_and_principles_2026-11-06.pdf), the
  November 6 revision. Where a later entry in the History below differs from it, the History is right.

The guardrails (public aggregate data only, service planning only, ORR's 50-release threshold, neutral
language) are rules rather than assumptions; they are in the README.

## Data

| ID | Assumption | Evidence, or what happens if it is wrong | Where | Status |
|---|---|---|---|---|
| AS-01 | MPI's file is a faithful tabulation of ORR's published release counts, and it stays available (A-01). | State and county totals reconcile to the file every year (data build checks). If it disappears, rebuild from ORR's web tables. | §2, `src/build_dataset.py` | Data |
| AS-02 | A release is counted where the child was first released to a sponsor; later moves are not tracked. | A property of the source. Counts describe first placements, not where children live now. | §13, README Limitations | Data |
| AS-03 | Every source is aligned to the federal fiscal year (October to September). | MPI and ORR report by fiscal year; Census is a fixed reference. | README Data | Data |
| AS-04 | A county missing from a year's list had 0 to 49 releases. It sits inside "other counties" (state total minus listed counties) and is never estimated (R-05). | ORR's publication threshold. County results therefore cover listed counties only, which leans toward large counties. Checked 2026-11-11: no state's remainder is larger than 49 times its unlisted counties, once the District of Columbia is counted as a county (AS-42). | §2, §9 | Data |
| AS-05 | One reference population for every year: Census Vintage 2024 county estimates (July 1, 2024), ages 5–17. | The BRD (A-04) named ACS 5-year estimates; the project uses Vintage 2024 instead. Puerto Rico and the Virgin Islands have no figures in it. | Week 4 school-age ratio, README | Data |
| AS-06 | Connecticut's four listed counties stay in the tables without population figures or map shapes. | The Census now reports Connecticut by planning region, so those counties have no current FIPS code. | README Limitations | Data |
| AS-07 | "States" means the 50 states and DC (51 places). Puerto Rico and the Virgin Islands are left out of the share model but stay in the national total. | Together they had 0 to 9 releases a year, and 11 of their 22 state-years had none. | §2, §10 | Design |
| AS-41 | An "other counties" figure that covers exactly one county is marked not publishable, automatically. It stays in the tables so that totals add up; the exchange file flags it and the app leaves it blank. | It is that one county's own count, which ORR withheld: Delaware in FY2019, FY2021, FY2022 and FY2023 (two of its three counties were listed) and the District of Columbia in FY2020. Anyone can do the same subtraction from the public file, so the rule keeps the project from repeating it; it cannot make it impossible. | `src/build_dataset.py`, `exchange/`, `src/scenario_contract.py`, app | Decided 2026-11-11 |
| AS-42 | The District of Columbia is treated as a county. It gets a county row from its state total in the years with 50 or more releases: 10 of the 11 analysis years (48 in FY2020). | MPI's county sheet has no row for it, because it is reported as a state, yet it is one county-equivalent. Without the row it counted as a county that never reached the threshold. Effect on Week 4: High-High counties 151 to 152, county Moran's I 0.40 to 0.41, and cluster 1 gains DC. | `src/build_dataset.py`, README, Week 4 memo | Decided 2026-11-11 |

## Share model

| ID | Assumption | Evidence, or what happens if it is wrong | Where | Status |
|---|---|---|---|---|
| AS-08 | Expected releases = national volume × a place's share. Volume is a scenario, not a forecast; only shares are modeled. | Volume swung 7.6-fold (16,864 in FY2020 to 127,512 in FY2022) with policy and events. | §1 | Design |
| AS-09 | Past shares inform future ones (A-02). | State rank correlation is 0.985 or higher every year from FY2016 on (0.983 from FY2014 to FY2015), and "same as last year" misses by 0.212 share points. A policy change could still move shares more than any past year did. | §3, §4, §13 | Design |
| AS-10 | Shares themselves vary from year to year, more than counting noise, so the model is Dirichlet-multinomial. | For the largest states, shares move about 4 to 7 times more than counting noise alone (in standard deviation). This is math doc §4's measure: the spread of the year-to-year change in share divided by √2, against counting noise at the typical national total. The κ fit in AS-39 uses a different yardstick (each miss against that year's counting noise alone), which gives larger ratios for the same states. | §4, §5 | Design |
| AS-11 | One concentration κ for all states. | Large and small states may vary differently; calibration is reported separately for the 10 largest states and the other 41 to check it. | §5, spec | Design |
| AS-12 | Expected shares = softmax(α + ρ × log last year's shares). ρ = 1 and α = 0 give naive. | Lets the fit fall back on naive; the backtest decides. In the fork's fits (2026-11-16) ρ was 0.92 to 0.94 for states, and the backtest chose naive. | §6, `src/share_model.py` | Design |
| AS-13 | Priors: α a zero-sum normal with its own spread σ; ρ centered at 1; κ on the log scale, from the tens to the tens of thousands. | Exact numbers are recorded in `results/share_model.json`. Set in the fork by Claude (2026-11-16) and confirmed by the owner on 2026-11-17: σ ~ HalfNormal(0.5), ρ ~ Normal(1, 0.25), κ ~ LogNormal(log 1000, 2), and for counties an "other" offset δ ~ Normal(0, 1). The data, not the priors, set the values: in the state fit through FY2025 the 90% range for ρ narrowed from 0.59–1.41 to 0.88–0.94, and for κ from about 37–26,800 to 2,249–2,781. County scoring: one log score a year, pooled over the scored states and weighted by releases, as at state level. | §7, spec, `src/share_model.py` | Decided 2026-11-17 (set by Claude in the fork; confirmed by the owner) |
| AS-14 | A share of zero gets a floor of 0.0001 releases before taking logs, the same as naive. A refit with a floor of 0.5 releases checks that ρ barely moves. | Four state-years had no releases (VT FY2017, AK FY2018 and FY2020, MT FY2019), and one "other counties" group (DE FY2024). The floor also moves naive's own log score: by 0.0004 to 0.0010 per child in FY2018–FY2021, all from the 12 children released in those states the following year. That is why the winner rule is scored three ways (AS-20). The refit with a floor of 0.5 moved ρ from 0.915 to 0.931 (fork, 2026-11-16). | §6, spec, tests | Decided 2026-11-08 |
| AS-15 | FY2014 serves only as "last year" for FY2015. | The first backtest fit sees three year-over-year changes instead of two. | §7, §8, spec, tests | Decided 2026-11-08 |
| AS-16 | In the backtest, a year's county categories are the counties listed in both that year and the year before, plus "other". | Knowing year t's list is a small peek at year t: counties new to the list took 0% to 26.7% of releases (5.5% on average). In the engine's calibration a county is scored only if it would get a row: listed in both years and expecting 50 or more releases (fork, 2026-11-14). | §9, spec | Design |
| AS-17 | The county model shares one ρ, one κ and one "other" offset across all states. | More than half of the 394 counties are listed in 5 or fewer of the 11 years, too few to estimate each one's own tilt. | §9 | Design |
| AS-18 | The county model's mean has no term for each county's long-run share. | If the county ρ comes out below 1, counties within a state are pulled toward equal shares. Raised in Claude's theory review on 2026-11-06; not in the math doc. In the fork's fits (2026-11-16) the county ρ was 0.94 to 0.95, so the pull exists but is small, and naive won at county level, so the model's county forecast is not used. | §9 | Open |
| AS-43 | A more complicated model is not necessarily better. Last year's shares seems to be the strongest simple baseline at both the state and the county level, and a simpler distribution than the Dirichlet-multinomial share model could serve better, especially because many counties do not appear on the list year after year. | On AS-16's matched categories, last year's shares beats the three-year mean and the pooled rule for counties as well as for states (10 largest states, FY2017–FY2025: 1.01 share points against 1.22 and 1.51). The earlier probe in `docs/modeling_candidates.md` pointed the other way only because it scored last year's shares on counties new to the list. The backtest (AS-20) and the comparison in AS-40 decide. The fork's backtest (2026-11-16) agrees: the Dirichlet-multinomial share model did not beat last year's shares at either level. The owner decided on that evidence on 2026-11-17: last year's shares are the method. A later model can still be tested against them under the same rule (AS-20). | `docs/modeling_candidates.md`, spec, `results/share_model_summary.csv` | Decided 2026-11-17: last year's shares are the method |

## Backtest and the winner

| ID | Assumption | Evidence, or what happens if it is wrong | Where | Status |
|---|---|---|---|---|
| AS-19 | Each held-out year, FY2018 to FY2025, is predicted from earlier years only. | Prevents leakage. The BRD's "leave-one-year-out" (R-04) would also train on later years, so FR-12's forward-only rule is followed. | §8, §11 | Design |
| AS-20 | Winner rule: the model is used at a level only if its release-weighted and equal-weighted mean log scores both beat naive's and it wins at least 6 of the 8 years. A gap under 0.0005 per child is a tie, and ties go to naive. MAE does not decide. The rule is pessimistic: it must hold under three scorings, namely the main one (floor 0.0001), naive with a floor of 0.5 of a release, and places with no releases the year before left out. | With 8 years nothing can prove the model better: 6 wins of 8 happen by luck about 15% of the time. The rule only guards against picking a winner on noise. Without the pessimistic part, 12 children in three small states could decide up to four of the eight years (AS-14). Applied in the fork on 2026-11-16: naive won at both levels. The model beat naive in 4 of 8 years for states and 4 of 8 for counties, short of the 6 needed; with naive floored at half a release its FY2020 state win disappears. | §8, spec, tests, `results/share_model.json` | Decided 2026-11-08; made pessimistic 2026-11-11 |
| AS-21 | The log score is the judge. | It is a proper scoring rule, so hedging or false confidence cannot game it. It judges expected shares only; ranges are checked by calibration. | §3 | Design |

## Scenario engine

| ID | Assumption | Evidence, or what happens if it is wrong | Where | Status |
|---|---|---|---|---|
| AS-22 | The scenarios are the lowest, median and highest national totals of FY2015–FY2025: 16,864 (FY2020), 52,267 (FY2016) and 127,512 (FY2022). | They are planning volumes, not forecasts, and Low is not a floor: October 2025 had 106 releases, a pace of about 1,300 a year (R-06). Shares were learned at 17,000 to 128,000 a year and are untested far below that. | §10, §13 | Design |
| AS-23 | Next year starts from FY2025's actual shares. | The most recent published year. | §10, spec | Design |
| AS-24 | Children are counted out of each draw's shares (multinomial), not N × shares. | Multiplying leaves out counting noise. In theory, if counting noise were about 35% of a county's spread, county ranges would hold only about 70% of outcomes without it (65% near 50 releases, where it is about 47%). Measured in the fork on 2026-11-17 (check script kept in the fork's local `writeups/as24_check/`): counting noise is a median 20% of a shown county's spread in the Low scenario (14% to 36% for the middle 80% of rows), 8% in Median and 4% in High, because most of the spread comes from the shares moving. In the FY2018–FY2025 replay (version (b)), county ranges held 86.3% of the time counted out and 84.7% multiplied. By year the gap was 0 to 1.9 points, except in the two lowest-volume years: 5.7 points in FY2020 (70 counties) and 7.8 in FY2025 (103 counties). So counting out matters most in low-volume years, which is the Low scenario's case. With 70 to 124 counties a year each county is about 1 point, so the per-year gaps are rough. | §10, spec | Decided 2026-11-08 (count out); evidence Open: measured 2026-11-17, kept Open by the owner |
| AS-25 | Only the 110 counties listed in FY2025 (in 34 states and the District of Columbia) can get their own row. A county listed only in earlier years stays in "other counties". | Such a county has no FY2025 count to start from. In the high scenario, "other counties" holds about 35% of releases, against 10% in FY2022. | §9, §12, §13, spec, tests | Decided 2026-11-08 |
| AS-26 | A listed county under 50 expected releases is folded into "other counties" by adding its draws there before the mean and percentiles are taken. | Keeps ORR's threshold in every scenario (FR-19, NFR-03). Whether a county expects 50 is worked out before any random draw, as national total × state share × the county's share of its state, which the average of the draws lands on. Tested on the draws' average instead, two counties with the same FY2025 count (72 each) fell on opposite sides of 50 in the low scenario by chance (fork, 2026-11-14). Confirmed by the owner on 2026-11-17: the same county always gets the same answer. | §10, §12, spec, `src/scenarios.py` | Decided 2026-11-17 |
| AS-27 | The 80% range runs from the 10th to the 90th percentile of 10,000 draws, with a fixed seed (20261101). | Reproducible (NFR-07). | §10, spec | Design |
| AS-28 | Calibration passes if pooled coverage is 70% to 90%. | An operational tolerance, not a statistical test: states in the same year move together, so the 408 state-years are not independent checks (independent checks would give 76% to 84%). A pooled figure can hide a gap between large and small states, so both are reported beside it (AS-40). | §11, spec, tests | Design |
| AS-29 | "Large" states are the 10 with the most releases in each fit's training years; the other 41 are "small". | Used only to report calibration by size. | spec | Design |
| AS-30 | Figures are rounded to whole children; a sum of rounded parts may be off by up to 1% or 2 children. | Largest-remainder rounding would keep sums exact. | §12, `src/scenario_contract.py` | Design |
| AS-39 | Until the share model is validated, the engine runs on the fallback (R-03): last year's shares, with a Dirichlet error whose κ is fitted to the year-over-year changes, every place weighted equally. The Dirichlet share model replaces it later; nothing else in the engine changes. | Lets the app and scenario tables exist before the share model (the BRD's D-05 puts the model first, so outputs are labeled as the fallback). In a check before coding, this calibrated at about 83% for states and 86% for counties, but only about 60% for the 10 largest states. Weighting places by size instead gave 91% pooled (78% for the large states, 94% for the others), too wide. The equal-weight fit was chosen after seeing these figures, so its pooled coverage is not an independent check; AS-40 follows from that. The exact error model is recorded in `fallback_error_model`. Built in the fork on 2026-11-14: fitted on all eleven changes, κ is 2,387 for all states (988 and 3,659 in version (b)) and 404 for counties; the version the tables use held 84% of state-years and 86% of county-years. The share model was run in the fork on 2026-11-16 and did not beat last year's shares, so the fallback stays. Coverage swings from year to year (AS-44). | spec, `src/scenarios.py`, `results/scenarios.json` | Decided 2026-11-11; built in the fork 2026-11-14 |
| AS-40 | The fallback's error model is built in two versions and compared head to head: (a) one κ for all 51 places; (b) one κ for the 10 largest states and one for the other 41. Same held-out years, same seed, same number of draws. | With one κ the ranges held in about 60% of the largest states' years, and those states receive about 68% of children: weighted by children, 65% were in a state whose range held. In a check before coding, version (b) gave 78% for the large states and 85% for the others, with a lower interval score (1.04 against 1.13 share points). Which version the tables use is the owner's call after seeing both; it is recorded in `error_model_version` with the reason. Run in the fork on 2026-11-14: (a) held for 60.0% of the largest states' years and 89.0% of the others' (interval score 1.13); (b) for 77.5% and 85.1% (1.04). The fork's tables use (b), picked by a rule: the lower mean interval score among versions whose pooled coverage is 70% to 90%, a tie going to (a). The same replay picks the version, so its coverage is not an independent check, and California's range held in only 3 of 8 years. The owner confirmed (b) on 2026-11-17. | spec, tests, `src/scenarios.py`, `results/scenario_variant_comparison.csv` | Decided 2026-11-11 (build both and compare); version (b) confirmed by the owner 2026-11-17 |
| AS-44 | The ranges are about equally honest every year, so one pooled coverage figure describes them. | It hides a swing from year to year. Version (b)'s county ranges held 69% to 78% of the time in FY2018–FY2021 (too narrow) and 91% to 96% in FY2022–FY2023 (too wide); state ranges went from 69% (FY2018) to 96% (FY2022). The pooled 86% for counties and 84% for states average the two. Chance alone does not explain it: with 293 counties, an honest 80% range would land between about 75% and 85% in 19 years of 20 (counties in one year move together, so the real band is somewhat wider), and FY2022 reached 96%. One κ fitted on all years is a single setting for calm and turbulent stretches alike. Raised by the owner on 2026-11-17. | `results/scenario_calibration.csv`, AS-16, AS-39 | Open |

## Service needs (school-age children)

| ID | Assumption | Evidence, or what happens if it is wrong | Where | Status |
|---|---|---|---|---|
| AS-31 | ORR's national age mix applies to every place (A-03). | Local age mixes may differ; school-age figures carry error the ranges do not include. | §12, §13 | Design |
| AS-32 | The ages of children in ORR's care stand in for the ages of children released. | Teens who turn 18 in care are not released, so the mix slightly overstates 17-year-olds; ORR's 17+ group also includes the 0.13% found to be 18 after its first evaluation. | §12, spec | Design |
| AS-33 | School age means 5 to 17. | Matches the Census ages 5–17 used for the Week 4 school-age ratio. | §12 | Design |
| AS-34 | School-age fraction f = share(13–14) + share(15–16) + share(17+) + λ × share(0–12), from ORR's yearly table (FY2019–FY2025), each year rescaled to add to 1. | ORR rounds to two decimals; FY2021's shares add up to 1.01. | §12, spec, tests | Decided 2026-11-08 |
| AS-35 | λ, the part of the 0–12 group aged 5 to 12, is 0.863 for the point estimate: (6–12 + one sixth of 0–5) ÷ (0–5 + 6–12), from ORR's FY2026 month-end counts summed over the year (3,449 and 678). Age 5 is taken as one sixth of 0–5, since ORR does not split that group. | ORR's own split, instead of assuming ages are spread evenly (8/13 = 0.615). The monthly values run from 0.844 to 0.896. Assumes FY2026's split within 0–12 also holds for the years the point estimate uses. The month-end counts are children in care at one moment (ages 0–12 are 15.6% of them), while the yearly table has 24% for FY2025, so the two tables do not measure quite the same thing. The effect on f is small: 0.967 to 0.980 across FY2019–FY2025. | §12, spec, tests | Decided 2026-11-10 |
| AS-36 | The range for f runs from λ = 8/13 in the year where f is lowest (0.908) to λ = 1 (1.0, every child counted). | The high end counts children under 5 as school age, so it is an upper bound, not a likely value. | §12, spec, tests | Decided 2026-11-08 |
| AS-37 | Which year or years the point estimate of f uses. | FY2025 alone gives 0.967; the seven published years run from 0.967 to 0.980. Recorded as `point_fiscal_years` in `results/scenarios.json`. The fork's engine uses FY2025 alone, the same year the shares start from (AS-23). The owner chose FY2025 on 2026-11-17: it is the current age mix (the 0–12 group rose from about 16% to 24% of children in care in FY2024–FY2025), and the shares start from the same year. Averaging FY2019–FY2025 would give about 0.975. | spec, `src/scenarios.py` | Decided 2026-11-17: FY2025 alone |

## Project

| ID | Assumption | Evidence, or what happens if it is wrong | Where | Status |
|---|---|---|---|---|
| AS-38 | Approvers are available, and FSO and contract-lead sign-off is recorded before anything is published (A-05, NFR-06). | Not yet recorded. | BRD, README | Open |

## History

Newest first. Each line says what changed and which files were updated with it.

- **2026-11-17, in the fork** (the owner went through, with Claude, the rows Claude had left to the owner):
  - Confirmed as built: AS-37 (FY2025's age mix), AS-40 (version (b)), AS-13 (the priors and the county scoring) and AS-26 (the 50-release test uses the exact expected value). Each was marked "not confirmed by the owner" before.
  - AS-43 Decided: last year's shares are the method. It was Open, the owner's working view.
  - AS-24: counting noise was measured directly instead of explained. Claude recommended closing the investigation; the owner kept it Open because the effect varies too much: 0 to 1.9 points of county coverage in most years, 5.7 and 7.8 in FY2020 and FY2025. The 70% stays a theoretical case.
  - AS-44 added (Open): coverage swings from year to year, which the pooled figure hides. Raised by the owner.
  - AS-16 and AS-18 were discussed and left for another day. AS-38 unchanged.
  - Updated in the fork: the README's "How this was built", the spec's sentence on AS-24 and the changelog. Not updated: the math doc, the review copies and the Word copies.
- **2026-11-16, in the fork** (the owner had Claude build the share model there too):
  - `src/share_model.py` and `tests/test_share_model.py` were written with AI assistance. All 19 fits passed the sampler checks.
  - AS-20 applied: naive won at both levels (4 of 8 years for states, 4 of 8 for counties; 6 needed). The scenario engine keeps last year's shares (AS-39), and AS-43's view is supported.
  - AS-13: the priors are written out; Claude set them and the owner has not confirmed them. AS-14: the floor check moved ρ from 0.915 to 0.931. AS-12 and AS-18: the fitted ρ values are in the rows.
  - Updated in the fork: the model card, the README, the app's "About" text, the scenario engine (it now reads the backtest's result), `requirements.txt` and the changelog. Not updated: the math doc, the review copies and the Word copies.
  - AS-38 (no change to the row): the owner had the fork's repository made public on this date. Sign-off was not yet recorded, so the row stays Open.
- **2026-11-14, in the fork** (the owner had Claude build the scenario engine in a fork of the repository):
  - `src/scenarios.py` and `tests/test_scenarios.py` were written with AI assistance. The README's "How this was built" says so.
  - AS-39: the fallback engine is built; its κ values and coverage are in the row.
  - AS-40: both versions were run. The fork's tables use (b), picked by a rule in the code; the owner has not confirmed the choice.
  - AS-37: the fork uses FY2025's age mix for the point estimate; the owner has not confirmed it.
  - AS-26: the 50-release test is now worked out before any random draw. AS-16: the calibration scores only counties that would get a row.
  - Updated in the fork: the README, the spec, the model card, the app's "About" text and the changelog. Not updated: the math doc, the review copies and the Word copies, which describe the original's register.
- **2026-11-12:**
  - New copies of the review doc and of both Word copies were made from this register (43 rows). The November 11 copies are kept unchanged, so the two sets can be compared.
  - The owner confirmed that sign-off is still pending (AS-38, no change). The README no longer says this repository has been public since October 25: current work is kept in a private repository, and the public copy holds the project through v0.6.2.
- **2026-11-11, after a logic check of the whole project** (the owner's decisions on its findings):
  - AS-20 changed: the winner rule is now pessimistic. It must hold under three scorings: the main one, naive with a floor of 0.5, and zero-last-year places left out. AS-14's evidence says why. Updated: the spec, the acceptance tests and the model card. Math doc §8 is not updated yet.
  - AS-40 added: the fallback's error model is built in two versions, one κ and two, and compared head to head. The app now shows coverage for the 10 largest states and the other 41 next to the pooled figure. AS-39's evidence now says the equal-weight fit was chosen after seeing coverage. Updated: the spec, the acceptance tests, the app and its tests.
  - AS-42 added: the District of Columbia is treated as a county. With it, AS-04 (the under-50 check now holds for every state), AS-16 (26.5% became 26.7%), AS-17 (393 counties became 394) and AS-25 (109 counties in 34 states became 110 in 34 states and DC) changed. Updated: `src/build_dataset.py`, every results table and chart that uses counties, the Week 4 memo, the README and the spec.
  - AS-41 added: an "other counties" figure that covers one county is marked not publishable. Updated: `src/build_dataset.py` (two new columns), the exchange export and contract, `src/scenario_contract.py`, the app and the tests.
  - AS-24: the evidence is now given as a theoretical case, with the measured figures beside it; it is under investigation. Updated: the spec.
  - AS-43 added: the owner's working view that a simpler model may serve better. `docs/modeling_candidates.md` now says its county result is superseded.
  - AS-10, AS-28 and AS-35: evidence lines extended; no decision changed.
  - The math doc was added to `docs/` as a PDF (the November 6 revision).
  - Not updated yet: the math doc itself (§2, §8, §9, §10, §12, §13), the review copy of this register and both Word copies.
- **2026-11-11:**
  - AS-09 corrected: the 0.985 rank correlation holds from FY2016 on. Now that FY2014 serves as "last year" for FY2015 (AS-15), that pair counts too, at 0.983. Found when the numbers were re-run before the Word copies. Updated: this register, the review doc, both Word copies, the README, the share-model card and the week 4 memo (its builder, `src/build_week4_memo.py`, now computes the FY2014 pair from the data).
  - AS-39 added: the owner chose to build the scenario engine on the fallback first, to have the app and scenario tables for the deliverable. Updated: this register and the review doc.
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
