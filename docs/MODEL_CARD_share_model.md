# Model card: release share model

*Status: baseline stage built. The scenario engine is being built first on the fallback (last year's shares
with an error model), in two versions compared head to head; the Bayesian model follows. Nothing below has
results from the model or the engine yet. Last updated 2026-11-11.*

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

## Stage 2: Bayesian share model (planned, Week 5)

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

## Until then: the fallback (being built)

The scenario engine is built first on last year's shares with a Dirichlet error model (AS-39), in two
versions compared head to head (AS-40): one κ for all 51 places, and one κ each for the 10 largest states
and for the other 41. In a check before coding, one κ gave 80% ranges that held for about 83% of
state-years but only about 60% for the 10 largest states, which receive about two thirds of children; two
gave about 78% and 85%. The results, and which version the tables use, go here once the engine has run.

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
python -m pytest
```
