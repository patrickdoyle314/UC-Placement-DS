"""Share model: does a Bayesian model predict next year's shares better than "same as last year"?

A Dirichlet-multinomial model in PyMC, for state shares and for county shares inside each state. Each
held-out year FY2018-FY2025 is predicted by a model fitted on earlier years only, and scored against the
naive baseline (last year's shares) under three scorings. A rule fixed before the backtest picks the winner
at each level; ties go to naive (docs/spec_share_model_scenarios.md, docs/ASSUMPTIONS.md AS-08 to AS-21).

Reads : data/processed/releases_by_fy_geo.parquet
Writes: results/share_model_backtest.csv, share_model_backtest_checks.csv, share_model_summary.csv,
        share_model.json. Fitted draws are kept in data/processed/share_model_fits/ (not committed), so the
        scoring can be rerun without refitting; delete that folder to fit everything again.
Usage : python src/share_model.py   (after src/build_dataset.py and src/measure.py; about half an hour)
"""
# ===================================================================================================
# HOW TO READ THIS FILE
# Business purpose: the scenario tables need each place's share of next year's releases. The simplest
# answer is "the same share as last year". This file asks whether a model can do better, and it is built
# so that the answer can be "no": with rho = 1 and every alpha = 0 the model IS last year's shares.
#
# The model, state level:  expected shares = softmax(alpha + rho x log of last year's shares)
#   rho    how much of last year carries over. 1 = all of it; below 1 = shares drift back to a usual level.
#   alpha  one tilt per state, summing to zero, shrunk toward 0 by its own spread sigma.
#   kappa  how far a year's real shares stray from the expected ones (the same kappa as the scenario engine's).
# County level: the same inside each state, on the counties listed in both years plus "other counties",
# with one rho, one kappa and one offset for "other" shared by all states (AS-17).
#
# The steps: blocks() lays out the data; fit() runs the sampler for one training window and checks it;
# forecast() turns a fit into next year's expected shares; score_year() scores model and naive three ways;
# winner() applies the fixed rule; main() runs every fit and writes the files.
#
# Guardrails: counties under 50 releases are never modeled one by one; they stay inside "other counties".
#
# Python ideas: PyMC models (priors, a likelihood, pm.sample), ArviZ diagnostics, padding ragged data
# into a rectangle with a mask, a process pool to run several fits at once, caching results in .npz files.
# ===================================================================================================
import hashlib
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # lets "python src/share_model.py" import the project's other files
from src import scenarios as sc  # noqa: E402  the data layout (History) is shared with the scenario engine
from src.share_baseline import EPS, score  # noqa: E402  the floor and the two scores, as the baseline uses them

RESULTS = ROOT / "results"
FITS = ROOT / "data/processed/share_model_fits"  # cached draws, one file per fit (not committed)

METHOD = "dirichlet_multinomial"  # the model's name in the output files
LEVELS = ("state", "county")
HELD_OUT = sc.HELD_OUT            # FY2018-FY2025, each predicted from earlier years only (AS-19)
FIRST_LAG_YEAR = sc.FIRST_LAG_YEAR  # FY2014 is only "last year" for FY2015 (AS-15)
LAST_YEAR = sc.BASE_YEAR          # the fit through FY2025 is the one a scenario for next year would use
CHECK_FLOOR = 0.5                 # the second floor: half a release (AS-14)
TIE = 0.0005                      # a log-score gap smaller than this is a tie, and ties go to naive (AS-20)
MIN_WINS = 6                      # the model must beat naive in at least 6 of the 8 held-out years
SCORINGS = ("floor_0.0001", "floor_0.5", "zeros_left_out")  # the winner rule must hold under all three

# Sampler settings (recorded in share_model.json). More draws and a higher target_accept than PyMC's
# defaults: rho and the alphas pull against each other, so the sampler needs small, careful steps.
SAMPLER = {"chains": 4, "draws": 2000, "tune": 2000, "target_accept": 0.95, "seed": 20261101}
MAX_RHAT, MIN_ESS = 1.01, 400     # every fit must pass these (Vehtari et al. 2021)
WORKERS = 3                       # fits run side by side; each fit runs its chains one after another
PRIORS = {
    "alpha": "sigma x ZeroSumNormal(1), one per state, summing to 0 (state model only)",
    "sigma": "HalfNormal(0.5): the spread of the state tilts",
    "rho": "Normal(1, 0.25), at both levels",
    "kappa": "LogNormal(log 1000, 2): from the tens to the tens of thousands, at both levels",
    "delta": "Normal(0, 1): the offset for 'other counties' (county model only)",
}
WINNER_RULE = (
    "Fixed before the backtest and applied to each level separately. The model is used only if (1) its "
    "release-weighted mean log score is higher than naive's, (2) its equal-weighted mean log score is also "
    "higher, and (3) its log score is higher than naive's in at least 6 of the 8 held-out years. A difference "
    "smaller than 0.0005 per child is a tie, and ties go to naive. MAE is reported but does not decide. The rule "
    "is pessimistic: it must hold under three scorings (floor_0.0001, the main one; floor_0.5, naive floored at "
    "half a release; zeros_left_out, places with no releases the year before left out).")


# --------------------------------------------------------------------------- the data, as blocks

def blocks(h: sc.History, level: str, year: int) -> list:
    """The change from year-1 to year, as a list of (label, last year's counts, this year's counts).

    State level: one block, the 51 places. County level: one block per state that has a county listed in
    both years; its categories are those counties and then "other counties" as the last entry (AS-16).
    A state with only "other counties" has nothing to predict and gets no block.
    """
    if level == "state":
        return [("US", h.states.loc[year - 1].to_numpy(), h.states.loc[year].to_numpy())]
    out = []
    for st in h.states.columns:
        keys = [k for k in sc.listed(h, st, year - 1) if k in set(sc.listed(h, st, year))]
        if keys:
            out.append((st, sc.category_counts(h, st, year - 1, keys), sc.category_counts(h, st, year, keys)))
    return out


def log_shares(last: np.ndarray, floor: float = EPS) -> np.ndarray:
    """Log of last year's shares, with the floor added to every count first so a zero has a logarithm."""
    return np.log((last + floor) / (last + floor).sum())


def softmax(x: np.ndarray) -> np.ndarray:
    """Turn any numbers into positive shares that add to 1 along the last axis."""
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


# --------------------------------------------------------------------------- fitting

def fit_key(level: str, trained_through: int, floor: float) -> str:
    """The cache file's name: it changes whenever the data, the sampler settings or the model would."""
    stamp = hashlib.md5(sc.DATA.read_bytes() + json.dumps([SAMPLER, PRIORS], sort_keys=True).encode()).hexdigest()[:10]
    return f"{level}_through{trained_through}_floor{floor}_{stamp}.npz"


def sample(model) -> tuple:
    """Run NUTS on a PyMC model; return (the draws as plain arrays, the sampler's health checks)."""
    import arviz as az  # imported here so the scoring code can be used without loading the samplers
    import pymc as pm

    with model:
        idata = pm.sample(draws=SAMPLER["draws"], tune=SAMPLER["tune"], chains=SAMPLER["chains"], cores=1,
                          target_accept=SAMPLER["target_accept"], random_seed=SAMPLER["seed"], progressbar=False,
                          compile_kwargs={"mode": "NUMBA"})  # this machine has no C compiler; Numba is the fast path
    checks = az.summary(idata, kind="diagnostics", round_to="none")
    health = {"max_rhat": round(float(checks["r_hat"].max()), 4), "min_ess_bulk": int(checks["ess_bulk"].min()),
              "divergences": int(idata["sample_stats"]["diverging"].sum())}
    posterior = idata["posterior"]
    draws = {name: posterior[name].to_numpy().reshape(SAMPLER["chains"] * SAMPLER["draws"], -1).squeeze()
             for name in posterior.data_vars}
    return draws, health


def state_model(log_last: np.ndarray, counts: np.ndarray):
    """The state model: counts ~ DirichletMultinomial(total, kappa x softmax(alpha + rho x log last shares)).

    log_last and counts have one row per training change and one column per state. alpha is written as
    sigma x z ("non-centered"): the sampler moves more easily when the tilts are small, which they are.
    """
    import pymc as pm

    with pm.Model() as model:
        sigma = pm.HalfNormal("sigma", 0.5)
        z = pm.ZeroSumNormal("z", sigma=1.0, shape=counts.shape[1])
        alpha = pm.Deterministic("alpha", sigma * z)
        rho = pm.Normal("rho", 1.0, 0.25)
        kappa = pm.LogNormal("kappa", mu=np.log(1000.0), sigma=2.0)
        expected = pm.math.softmax(alpha[None, :] + rho * log_last, axis=1)
        pm.DirichletMultinomial("releases", n=counts.sum(axis=1), a=kappa * expected, observed=counts)
    return model


def county_model(log_last: np.ndarray, counts: np.ndarray, mask: np.ndarray, other: np.ndarray):
    """The county model: the same idea inside each state, with one rho, kappa and "other" offset for all.

    States have different numbers of categories, so each block is one row of a rectangle, padded on the
    right; mask is 1 for real categories and 0 for padding. The Dirichlet-multinomial log-probability is
    written out by hand so the padding can be left out of it.
    """
    import pymc as pm
    import pytensor.tensor as pt

    with pm.Model() as model:
        rho = pm.Normal("rho", 1.0, 0.25)
        delta = pm.Normal("delta", 0.0, 1.0)
        kappa = pm.LogNormal("kappa", mu=np.log(1000.0), sigma=2.0)
        eta = rho * log_last + delta * other - 1e30 * (1 - mask)  # padding gets a share of zero
        expected = pt.exp(eta - pt.logsumexp(eta, axis=1, keepdims=True))
        a = mask * kappa * expected + (1 - mask)  # 1 under the padding keeps gammaln finite there
        n = counts.sum(axis=1)
        log_prob = (pt.gammaln(kappa) - pt.gammaln(n + kappa)).sum() + (mask * (pt.gammaln(counts + a) - pt.gammaln(a))).sum()
        pm.Potential("releases", log_prob)
    return model


def padded(rows: list) -> tuple:
    """Stack arrays of different lengths into one rectangle, padded with zeros, plus the mask of real cells."""
    width = max(len(r) for r in rows)
    out, mask = np.zeros((len(rows), width)), np.zeros((len(rows), width))
    for i, r in enumerate(rows):
        out[i, :len(r)], mask[i, :len(r)] = r, 1.0
    return out, mask


def fit(job: tuple) -> dict:
    """Fit one model: (level, last training year, floor). Uses the cached draws if this fit was run before."""
    level, trained_through, floor = job
    path = FITS / fit_key(level, trained_through, floor)
    if path.exists():
        saved = np.load(path, allow_pickle=False)
        return {"draws": {k: saved[k] for k in saved.files if k != "health"}, **json.loads(str(saved["health"]))}
    started = time.time()
    h = sc.history()
    training = [b for year in range(FIRST_LAG_YEAR + 1, trained_through + 1) for b in blocks(h, level, year)]
    if level == "state":
        model = state_model(np.stack([log_shares(last, floor) for _, last, _ in training]),
                            np.stack([now for _, _, now in training]).astype(int))
    else:
        log_last, mask = padded([log_shares(last, floor) for _, last, _ in training])
        counts, _ = padded([now for _, _, now in training])
        other, _ = padded([np.eye(len(last))[-1] for _, last, _ in training])  # 1 in each block's last real cell
        model = county_model(log_last, counts, mask, other)
    draws, health = sample(model)
    health = {"level": level, "trained_through": trained_through, "transitions": trained_through - FIRST_LAG_YEAR,
              "floor": floor, **health, "blocks": len(training), "seconds": round(time.time() - started)}
    FITS.mkdir(parents=True, exist_ok=True)
    np.savez(path, health=json.dumps(health), **{k: v for k, v in draws.items() if k != "z"})
    print(f"  fitted {level} through FY{trained_through} (floor {floor}): {health['seconds']} s, R-hat {health['max_rhat']}, "
          f"ESS {health['min_ess_bulk']}, divergences {health['divergences']}", flush=True)
    return {"draws": draws, **health}


def forecast(level: str, draws: dict, last: np.ndarray) -> np.ndarray:
    """Next year's expected shares for one block: softmax(...) for every draw, then averaged over the draws.

    The average is the predicted probability that a release goes to each place (math doc, section 7).
    """
    log_last = log_shares(last)
    if level == "state":
        return softmax(draws["alpha"] + draws["rho"][:, None] * log_last).mean(axis=0)
    other = np.eye(len(last))[-1]
    return softmax(draws["rho"][:, None] * log_last + draws["delta"][:, None] * other).mean(axis=0)


# --------------------------------------------------------------------------- scoring

def naive(last: np.ndarray, floor: float = EPS) -> np.ndarray:
    """Last year's shares, as src/share_baseline.py makes them."""
    return (last + floor) / (last + floor).sum()


def score_year(year_blocks: list, model_shares: list) -> list:
    """Score naive and the model on one held-out year, under the three scorings.

    year_blocks: (label, last, now) per block; model_shares: the model's forecast for each block.
    MAE is the average gap over every category of every block, in share points. The log score is the
    average log-probability given to each actual release, pooled over the blocks. Returns one dict per
    method and scoring.
    """
    forecasts = {"naive": {"floor_0.0001": [naive(last) for _, last, _ in year_blocks],
                           "floor_0.5": [naive(last, CHECK_FLOOR) for _, last, _ in year_blocks]},
                 METHOD: {"floor_0.0001": model_shares, "floor_0.5": model_shares}}  # the model's forecast never changes
    rows = []
    for method, by_scoring in forecasts.items():
        by_scoring["zeros_left_out"] = by_scoring["floor_0.0001"]
        for scoring in SCORINGS:
            gaps, log_sum, releases = [], 0.0, 0.0
            for (_, last, now), pred in zip(year_blocks, by_scoring[scoring]):
                if scoring == "zeros_left_out":  # drop places with nothing last year; rescale to add to 1
                    keep = last > 0
                    now, pred = now[keep], (last[keep] / last[keep].sum() if method == "naive" else pred[keep] / pred[keep].sum())
                gaps.append(np.abs(pred - now / now.sum()))
                log_sum += float(np.sum(now * np.log(pred)))
                releases += now.sum()
            rows.append({"method": method, "scoring": scoring, "releases": int(releases),
                         "mae_share_points": round(100 * float(np.concatenate(gaps).mean()), 4),
                         "log_score": round(log_sum / releases, 6)})
    return rows


def passes_winner_rule(table: pd.DataFrame, level: str) -> bool:
    """The fixed rule on one scoring's table (fiscal_year, level, method, releases, log_score)."""
    mine = table[(table.level == level) & (table.method == METHOD)].set_index("fiscal_year")
    base = table[(table.level == level) & (table.method == "naive")].set_index("fiscal_year")
    gap = (mine.log_score - base.log_score).round(6)  # six decimals, so a gap of exactly 0.0005 is a win
    if len(gap) != len(HELD_OUT) or gap.isna().any():
        return False
    release_weighted = round((gap * mine.releases).sum() / mine.releases.sum(), 6)
    return bool(release_weighted >= TIE and round(gap.mean(), 6) >= TIE and int((gap >= TIE).sum()) >= MIN_WINS)


def winner(scores: pd.DataFrame) -> dict:
    """The method used at each level: the model only if it passes the rule under all three scorings."""
    return {level: METHOD if all(passes_winner_rule(scores[scores.scoring == s], level) for s in SCORINGS) else "naive"
            for level in LEVELS}


def summarize(backtest: pd.DataFrame) -> pd.DataFrame:
    """Averages over the held-out years, two ways, and how many years each method beat naive."""
    rows = []
    for (level, method), part in backtest.groupby(["level", "method"], sort=False):
        mine = part.set_index("fiscal_year")
        base = backtest[(backtest.level == level) & (backtest.method == "naive")].set_index("fiscal_year")
        wins_mae = int((mine.mae_share_points < base.mae_share_points).sum())
        wins_log = int(((mine.log_score - base.log_score).round(6) >= TIE).sum())
        for weighting in ("release", "equal"):
            weights = part.releases if weighting == "release" else pd.Series(1.0, index=part.index)
            rows.append({"level": level, "method": method, "weighting": weighting,
                         "mae_share_points": round((part.mae_share_points * weights).sum() / weights.sum(), 4),
                         "log_score": round((part.log_score * weights).sum() / weights.sum(), 6),
                         "years_beating_naive_mae": wins_mae, "years_beating_naive_log": wins_log})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- run everything

def main():
    h = sc.history()
    jobs = [(level, year, EPS) for level in LEVELS for year in range(HELD_OUT[0] - 1, LAST_YEAR + 1)]
    jobs.append(("state", LAST_YEAR, CHECK_FLOOR))  # the floor check: one refit with half a release
    print(f"{len(jobs)} fits, {WORKERS} at a time (cached fits are reused)", flush=True)
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        fits = dict(zip(jobs, pool.map(fit, jobs)))

    scores = []
    for level in LEVELS:
        for year in HELD_OUT:  # the model fitted through year-1 predicts year from year-1's actual shares
            year_blocks = blocks(h, level, year)
            draws = fits[(level, year - 1, EPS)]["draws"]
            shares = [forecast(level, draws, last) for _, last, _ in year_blocks]
            scores += [{"fiscal_year": year, "level": level, **row} for row in score_year(year_blocks, shares)]
    scores = pd.DataFrame(scores)
    main_scoring = scores[scores.scoring == SCORINGS[0]]
    backtest = main_scoring[["fiscal_year", "level", "method", "releases", "mae_share_points", "log_score"]]
    checks = scores[scores.scoring != SCORINGS[0]][["fiscal_year", "level", "method", "scoring", "releases", "log_score"]]
    summary = summarize(backtest)
    won = winner(scores)

    def record(job):  # what share_model.json keeps about one fit
        f = fits[job]
        mean = {f"{name}_mean": round(float(np.mean(f["draws"][name])), 4) for name in ("rho", "kappa", "sigma", "delta")
                if name in f["draws"]}
        return {k: f[k] for k in ("level", "trained_through", "transitions", "max_rhat", "min_ess_bulk", "divergences")} | mean

    floor_fits = [("state", LAST_YEAR, EPS), ("state", LAST_YEAR, CHECK_FLOOR)]
    model_record = {
        "model_method": METHOD, "winner_rule": WINNER_RULE, "winner": won, "scorings": list(SCORINGS),
        "first_lag_year": FIRST_LAG_YEAR, "floor": EPS,
        "floor_check": [{"level": "state", "trained_through": LAST_YEAR, "floor": job[2],
                         "rho_mean": round(float(np.mean(fits[job]["draws"]["rho"])), 4),
                         "max_rhat": fits[job]["max_rhat"], "min_ess_bulk": fits[job]["min_ess_bulk"],
                         "divergences": fits[job]["divergences"]} for job in floor_fits],
        "priors": PRIORS, "sampler": SAMPLER,
        "diagnostics": [record(job) for job in jobs if job[2] == EPS],
    }

    RESULTS.mkdir(exist_ok=True)
    backtest.to_csv(RESULTS / "share_model_backtest.csv", index=False)
    checks.to_csv(RESULTS / "share_model_backtest_checks.csv", index=False)
    summary.to_csv(RESULTS / "share_model_summary.csv", index=False)
    (RESULTS / "share_model.json").write_text(json.dumps(model_record, indent=1) + "\n", encoding="utf-8")

    health = pd.DataFrame(model_record["diagnostics"])
    failed = health[(health.max_rhat > MAX_RHAT) | (health.min_ess_bulk < MIN_ESS) | (health.divergences > 0)]
    print(summary.to_string(index=False))
    for level in LEVELS:
        wide = backtest[backtest.level == level].pivot(index="fiscal_year", columns="method", values="log_score")
        print(f"{level}: log-score gap by year (model minus naive):",
              {int(y): round(float(g), 5) for y, g in (wide[METHOD] - wide["naive"]).items()})
    print("passes the rule under each scoring:",
          {level: {s: passes_winner_rule(scores[scores.scoring == s], level) for s in SCORINGS} for level in LEVELS})
    print("winner:", won)
    print("rho by last training year:", {lv: {r["trained_through"]: r["rho_mean"] for r in model_record["diagnostics"]
                                             if r["level"] == lv} for lv in LEVELS})
    print("floor check, rho:", [(c["floor"], c["rho_mean"]) for c in model_record["floor_check"]])
    print("sampler checks:", "every fit passed" if failed.empty else f"{len(failed)} fits FAILED\n{failed.to_string(index=False)}")
    if not failed.empty:
        sys.exit(1)


if __name__ == "__main__":
    main()
