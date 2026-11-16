# Model card: release share model

*Status: built and tested in a fork of the repository, with AI assistance (README, "How this was built").
The Bayesian share model did not beat last year's shares at either level, so the scenario engine uses last
year's shares with an error model. Last updated 2026-11-16.*

## Purpose

Predict each state's share of next year's releases of unaccompanied children to sponsors, so that a
national volume scenario can be turned into expected releases, and service needs, by state (Week 6).
**Service planning only.** The model works on aggregate public counts and never on individual children,
sponsors or households.

## Data

| Item | Value |
|---|---|
| Source | Migration Policy Institute tabulation of ACF/ORR releases to sponsors, FY2014–FY2025 (`data/raw/mpi/`) |
| Unit | State × federal fiscal year (October–September); 50 states and DC |
| Years used | FY2015–FY2025. FY2014 serves only as "last year" for FY2015 in the share model (`docs/ASSUMPTIONS.md`, AS-15) |
| Prepared by | `src/build_dataset.py` (reshape, reconcile), `src/measure.py` (parquet) |
| Excluded | Puerto Rico and the U.S. Virgin Islands (0–9 releases a year together; none in FY2015, FY2016 or FY2021) |

## What the data looks like

From `src/measure.py` (`results/concentration_by_year.csv`, `results/persistence_state_ranks.csv`):

- **Concentrated, slowly spreading.** State HHI is 0.058–0.074 (equivalent to 13.5–17.3 equal-sized
  states). The 10 largest states took 75% of releases in FY2016 and 64% in FY2024.
- **Very stable ranks.** Spearman rank correlation of state shares between consecutive years is
  0.985–0.996 (Kendall 0.910–0.962) in FY2015–FY2025, and 0.983 (Kendall 0.906) from FY2014 to FY2015, the
  first pair the share model uses. That stability is why "last year's shares" is hard to beat.

## Stage 1: baselines (built)

`src/share_baseline.py`. Each held-out year FY2018–FY2025 is predicted from earlier years only.

| Method | Prediction for year *t* |
|---|---|
| naive | $\hat p_{s,t} = p_{s,t-1}$ (the plan's baseline) |
| mean3 | $\hat p_{s,t} = \tfrac13 \sum_{k=1}^{3} p_{s,t-k}$ |
| pooled | $\hat p_{s,t} = \sum_{u<t} y_{s,u} \big/ \sum_{s'} \sum_{u<t} y_{s',u}$ |

where $y_{s,t}$ is releases and $p_{s,t} = y_{s,t} / \sum_{s'} y_{s',t}$. Before rescaling, a small floor is
added so no state gets zero probability: 0.0001 of a release for naive and pooled, and 0.0001 of a share for
mean3, which works in shares. With all three on the release scale, mean3 scores 0.229 and −3.170 and the
order stays the same.

**Scores** (release-weighted means over held-out years, `results/share_baseline_summary.csv`):

| Method | Mean absolute error (share points) | Log score per release |
|---|---|---|
| **naive** | **0.212** | **−3.168** |
| mean3 | 0.227 | −3.169 |
| pooled | 0.294 | −3.177 |

Mean absolute error is the average over states of $|\hat p_{s,t} - p_{s,t}|$; the log score is
$\frac{1}{Y_t}\sum_s y_{s,t} \log \hat p_{s,t}$, the average log-probability the forecast gave each actual
release (higher is better; a uniform forecast over 51 states scores $\log(1/51) = -3.93$).
An earlier probe (`src/probes/share_backtest.py`, held-out FY2017–FY2025) gave 0.206 for naive; the
difference is only the held-out window.

## Stage 2: Bayesian share model (built in the fork, 2026-11-16)

A Dirichlet-multinomial model in PyMC, scored against the naive baseline with the same backtest:

$$
\mathbf{y}_t \sim \text{DirichletMultinomial}\big(Y_t,\ \kappa\,\boldsymbol{\mu}_t\big), \qquad
\boldsymbol{\mu}_t = \operatorname{softmax}\big(\alpha_s + \rho\,\log p_{s,t-1}\big)
$$

- $\boldsymbol{\mu}_t$: expected shares, built from last year's shares ($\rho$ near 1 means "like last
  year") and a state effect $\alpha_s$ that pools toward each state's long-run share.
- $\kappa$: concentration; small $\kappa$ means year-to-year shares vary more than counts alone imply.
- County shares within a state follow the same form, with "other counties" as one category.
- Output: posterior predictive shares with 80% intervals, checked for calibration (about 80% of held-out
  actuals inside the 80% interval) and diagnosed with ArviZ ($\hat R$, effective sample size).

**How the winner is picked** (`docs/ASSUMPTIONS.md`, AS-20). The log score decides, not MAE. The model is
used at a level only if its release-weighted and equal-weighted mean log scores both beat naive's and it
wins at least 6 of the 8 held-out years; a gap under 0.0005 per child is a tie, and ties go to naive. The
rule is pessimistic: it must hold under three scorings (the main one with the 0.0001 floor; naive with a
floor of 0.5 of a release; and places with no releases the year before left out). If the model fails any of
them, the scenario engine keeps last year's shares.

### Result: last year's shares win at both levels

`src/share_model.py`, `results/share_model_backtest.csv`, `share_model_summary.csv`, `share_model.json`.

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

- **States:** the model won 4 of 8 years and is slightly worse on average (-0.0001 per
  child). **Counties:** it won 4 of 8 and is slightly better on average (+0.0008). The
  rule needs 6 of 8, so naive is used at both levels. The outcome is the same under the two extra scorings;
  with naive floored at half a release, the model's FY2020 state win disappears.
- **Why naive wins.** Last year's shares already close about 99% of the gap between a uniform forecast and
  perfect hindsight, so there is little left to gain. The model finds a mild pull toward each place's usual
  share (ρ 0.92 to 0.94 for states, 0.94 to
  0.95 for counties), but that pull helps in some years and hurts in others, most of all in
  FY2019.
- **Priors:** α = σ × a zero-sum normal(1), σ ~ HalfNormal(0.5), ρ ~ Normal(1, 0.25), κ ~ LogNormal(log 1000, 2).
  The county model has one ρ, one κ and one offset for "other counties", δ ~ Normal(0, 1), shared by all states.
- **Fitted values:** κ 1,849 to 2,507 for states and 203 to
  338 for counties, close to the simple fit the scenario engine uses.
- **Sampler:** 4 chains, 2,000 tuning and 2,000 kept draws each, target
  acceptance 0.95, seed 20261101. All 18 fits and the floor-check refit passed:
  largest R-hat 1.0062, smallest bulk effective sample size 1,076,
  no divergences.
- **Floor check:** with a floor of half a release instead of 0.0001, ρ moved from 0.915 to 0.931.
- **County scoring:** in each state, the counties listed in both the held-out year and the year before, plus
  "other counties"; states with only "other counties" are skipped; scores are pooled over the scored states.
  Knowing the held-out year's list is a small peek at that year: counties new to the list took 0% to 26.7% of
  releases (5.5% on average). Naive is scored on the same categories.
- **Checked on made-up data:** fitted to data built with ρ = 0.8 and κ = 1,500, the model recovers both
  (`tests/test_share_model.py`).

## The shares the scenario engine uses: the fallback (built in the fork, 2026-11-14)

The scenario engine runs on last year's shares with a Dirichlet error model (AS-39), in two versions
compared head to head (AS-40): one κ for all 51 places, and one κ each for the 10 largest states and for the
other 41. It was written with AI assistance in a fork of the repository (README, "How this was built").

Replaying FY2018–FY2025 from earlier years only (`results/scenario_variant_comparison.csv`):

| Version | 80% range held, all 408 state-years | 10 largest states | Other 41 | Mean interval score |
|---|---|---|---|---|
| (a) one κ | 83.3% | 60.0% | 89.0% | 1.13 |
| (b) two κ | 83.6% | 77.5% | 85.1% | 1.04 |

- The tables use version (b), which has the lower interval score. Fitted on all eleven changes, κ is
  988 for the 10 largest states, 3,659 for the other 41 and 404 for
  counties.
- County ranges held for 86.3% of the county-years scored.
- Limits: California's range held in only 3 of 8 years under (b); coverage runs from
  69% of states in FY2018 to 96% in
  FY2022; and the replay that picks the version is the same one that scores it.
- The fallback only puts ranges around last year's shares. It does not try to predict which way a share
  will move. That was the share model's job, and it did not do it better than last year's shares.

## Limitations

- **First release location only.** Later moves are not in the data.
- **Suppressed counties.** Counties with fewer than 50 releases are never estimated; they stay one
  "other counties" category (plan guardrail).
- **Regime changes.** FY2020 (16,864) and FY2025 (24,259) were low-volume years; shares held steady
  through them, but a policy change could shift where children are released.
- **Not a forecast of volume.** National volume comes from scenarios (lowest, median, highest year),
  not from this model.

## Reproduce

```bash
pip install -r requirements.txt
python src/build_dataset.py
python src/measure.py
python src/share_baseline.py
python src/run_sql.py          # sql/state_ranks.sql
python src/share_model.py      # the Bayesian model and its backtest (about half an hour)
python src/scenarios.py        # the scenario tables
python -m pytest
```
