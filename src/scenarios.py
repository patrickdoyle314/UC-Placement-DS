"""Scenario engine: what a low, median or high national year would mean for each state and listed county.

For each scenario the engine starts from last year's shares (FY2025), simulates 10,000 possible next years,
and reports for every state, and every county it may show, the expected number of children released to
sponsors with an 80% range, plus the school-age children among them.

This is the fallback the business requirements allow while the share model is not validated (risk R-03):
"last year's shares" with an error model. The error model is built in two versions and compared head to
head on FY2018-FY2025; the tables use the version the comparison picks (docs/ASSUMPTIONS.md, AS-39, AS-40).

Reads : data/processed/releases_by_fy_geo.parquet, data/raw/orr/UAC-Age-Data_Sep_2026_0.xlsx
Writes: results/scenarios.json, scenario_releases.csv, scenario_calibration.csv,
        scenario_calibration_by_size.csv, scenario_variant_comparison.csv
Usage : python src/scenarios.py   (after src/build_dataset.py and src/measure.py)
"""
# ===================================================================================================
# HOW TO READ THIS FILE
# Business purpose: schools, legal aid and child welfare agencies plan months ahead. They cannot know
# next year's national volume, so this file answers "if the national total were low, typical or high,
# how many children would each place expect, and how sure is that?" The answer for each place is an
# expected number and an 80% range, never a single promise.
#
# The idea in four steps (docs/spec_week5_week6.md; the step numbers match coaching/scenario_engine_steps.md):
#   1-2  Scenarios and starting shares: three national totals taken from history, and each place's share
#        of FY2025's releases.
#   3    The error model: how far did shares really move from one year to the next? One number, kappa,
#        measures it. A large kappa means shares stay close to last year's; a small one means they wander.
#   4-6  Simulation: draw possible shares 10,000 times, count the children out place by place, apply
#        ORR's 50-release rule to counties, and convert releases to school-age children.
#   8    Calibration: replay FY2018-FY2025 using only earlier years, and count how often the 80% range
#        held what really happened. Both versions of the error model go through the same replay.
#
# Guardrails: counties appear only if they were listed in FY2025 and expect 50 or more releases; every
# other county stays inside its state's "other counties" figure and is never estimated one by one.
#
# Python ideas: a dataclass to carry several tables together, NumPy's random Generator (gamma and
# multinomial draws), np.percentile, scipy's brentq to solve an equation with one unknown, f-strings.
# ===================================================================================================
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd
from scipy.optimize import brentq

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # lets "python src/scenarios.py" import the project's other files
from src import scenario_contract as contract  # noqa: E402  the agreed layout of the output files
from src.share_baseline import EPS  # noqa: E402  the tiny floor for a count of zero, shared with the baseline

DATA = ROOT / "data/processed/releases_by_fy_geo.parquet"
AGE_FILE = ROOT / "data/raw/orr/UAC-Age-Data_Sep_2026_0.xlsx"
RESULTS = ROOT / "results"

BASE_YEAR = 2025              # the most recent published year: next year starts from its shares (AS-23)
FIRST_LAG_YEAR = 2014         # FY2014 serves only as "last year" for FY2015 (AS-15)
ANALYSIS_YEARS = range(2015, 2026)  # the scenarios come from these years' national totals
HELD_OUT = range(2018, 2026)  # years replayed in the calibration, each from earlier years only (AS-19)
TERRITORIES = ["PR", "VI"]    # in the national total, not among the 51 places (AS-07)

DRAWS = 10_000                # simulated next years per scenario (AS-27)
SEED = 20261101               # fixed, so a rerun gives the same numbers
RANGE = (0.1, 0.9)            # the 80% range runs from the 10th to the 90th percentile of the draws
THRESHOLD = contract.THRESHOLD  # ORR's rule: a county is shown by itself only at 50 or more releases
N_LARGE = 10                  # "large" states: the 10 with the most releases in the training years (AS-29)
VERSIONS = ("a", "b")         # (a) one kappa for all states; (b) one for large states, one for the rest
FORCE_VERSION = None          # set to "a" or "b" to overrule choose_version() below
COVERAGE_BAND = (0.70, 0.90)  # pooled coverage of the 80% ranges that counts as passing (AS-28)
MISS_PENALTY = 2 / (2 * RANGE[0])  # interval score: each share point outside the range costs 10 (2 / 0.2)

LAMBDA_EVEN = 8 / 13          # low end for the school-age fraction: ages spread evenly within 0-12
POINT_FISCAL_YEARS = [2025]   # year(s) of ORR's age mix behind the point estimate (AS-37): the base year


# --------------------------------------------------------------------------- the data, in one bundle

# A dataclass is a simple container with named parts. Passing one "History" around is easier to read
# than passing five separate tables to every function.
@dataclass
class History:
    national: pd.Series       # fiscal year -> national releases (includes Puerto Rico and the Virgin Islands)
    states: pd.DataFrame      # rows: fiscal years, columns: the 51 places, values: releases
    counties: dict            # (fiscal year, state) -> releases by county_key, listed counties only
    state_names: dict         # "TX" -> "Texas"
    county_info: pd.DataFrame  # county_key -> county_fips, county_name


def history(df: pd.DataFrame | None = None) -> History:
    """Read the Week 1 table and lay it out the way the steps below need it."""
    df = pd.read_parquet(DATA) if df is None else df
    df = df[df.fiscal_year.between(FIRST_LAG_YEAR, BASE_YEAR)]
    places = df[(df.geo_level == "state") & ~df.state.isin(TERRITORIES)]
    county = df[df.geo_level == "county"]
    return History(
        national=df[df.geo_level == "national"].set_index("fiscal_year").releases.astype(int),
        states=places.pivot(index="fiscal_year", columns="state", values="releases").fillna(0).astype(float),
        counties={key: g.set_index("county_key").releases.astype(float)
                  for key, g in county.groupby(["fiscal_year", "state"])},
        state_names=places.drop_duplicates("state").set_index("state").state_name.to_dict(),
        county_info=county.drop_duplicates("county_key").set_index("county_key")[["county_fips", "county_name"]],
    )


def listed(h: History, state: str, year: int) -> list:
    """The county keys a state had on ORR's list (50 or more releases) in a year; often none."""
    counties = h.counties.get((year, state))
    return [] if counties is None else list(counties.index)


def category_counts(h: History, state: str, year: int, keys: list) -> np.ndarray:
    """Releases in `year` for the given counties of a state, then the rest of the state as the last entry.

    The last entry is the state's "other counties": the state total minus the counties named. A county
    that is not named is never zero; it is inside that remainder (AS-04, AS-25).
    """
    counts = h.counties[(year, state)][keys].to_numpy() if keys else np.array([])
    return np.append(counts, h.states.loc[year, state] - counts.sum())


# --------------------------------------------------------------------------- step 1: the three scenarios

def scenario_volumes(national: pd.Series) -> list[dict]:
    """Low, median and high: the lowest, middle and highest national totals of the analysis years (FR-13).

    Eleven years have a real middle year. With an even number of years the median would fall between two
    years; the lower of the two is used then, so every scenario is a volume that actually happened.
    """
    years = national[national.index.isin(ANALYSIS_YEARS)].sort_values(kind="stable")
    position = {"low": 0, "median": (len(years) - 1) // 2, "high": len(years) - 1}
    return [{"id": sid, "label": sid.capitalize(), "national_releases": int(years.iloc[i]),
             "source_fiscal_year": int(years.index[i])} for sid, i in position.items()]


# --------------------------------------------------------------------------- step 3: the error model, kappa

def miss_ratios(last: np.ndarray, now: np.ndarray) -> tuple:
    """How far this year's counts strayed from last year's shares, in units of counting noise.

    For each category: (actual - n x share)^2 divided by n x share x (1 - share), where share is last
    year's share and n is this year's total. If shares never moved, counting children out at random would
    still make these ratios average 1; real shares move more, so the ratios come out well above 1.
    Categories with nothing the year before are skipped (their share is only the floor).
    Returns (n, the ratios, which categories were kept).
    """
    n = now.sum()
    share = last / last.sum()
    noise = n * share * (1 - share)
    keep = (last > 0) & (noise > 0)
    ratio = np.full(len(last), np.nan)
    ratio[keep] = (now[keep] - n * share[keep]) ** 2 / noise[keep]
    return n, ratio, keep


def state_ratios(h: History) -> pd.DataFrame:
    """One row per state and year-over-year change (FY2014-15 through FY2024-25)."""
    rows = []
    for year in range(FIRST_LAG_YEAR + 1, BASE_YEAR + 1):
        n, ratio, keep = miss_ratios(h.states.loc[year - 1].to_numpy(), h.states.loc[year].to_numpy())
        rows += [(year, st, n, r) for st, r, k in zip(h.states.columns, ratio, keep) if k]
    return pd.DataFrame(rows, columns=["year", "state", "n", "ratio"])


def county_ratios(h: History) -> pd.DataFrame:
    """The same inside each state: its counties listed in both years, plus "other", pooled over states."""
    rows = []
    for year in range(FIRST_LAG_YEAR + 1, BASE_YEAR + 1):
        for st in h.states.columns:
            keys = [k for k in listed(h, st, year - 1) if k in set(listed(h, st, year))]
            if not keys:
                continue  # a state with only "other" has no split to learn from
            n, ratio, keep = miss_ratios(category_counts(h, st, year - 1, keys), category_counts(h, st, year, keys))
            rows += [(year, st, n, r) for r, k in zip(ratio, keep) if k]
    return pd.DataFrame(rows, columns=["year", "state", "n", "ratio"])


def fit_kappa(ratios: pd.DataFrame) -> float:
    """The kappa at which the model's typical miss matches the misses that really happened.

    Under the Dirichlet-multinomial each ratio averages (n + kappa) / (1 + kappa). brentq searches for
    the kappa (on the log scale) where the expected total of the ratios equals the real total. Every
    place counts equally, large or small. If the real misses are no bigger than counting noise there is
    nothing to fit, and the largest kappa (shares that do not move) is returned.
    """
    def gap(log_kappa):
        kappa = np.exp(log_kappa)
        return ratios.ratio.sum() - ((ratios.n + kappa) / (1 + kappa)).sum()

    low, high = np.log(1.0), np.log(1e8)
    return float(np.exp(brentq(gap, low, high))) if gap(high) > 0 else float(np.exp(high))


def large_states(h: History, forecast_year: int) -> list:
    """The 10 states with the most releases in the training years: FY2014 up to the year before the forecast."""
    totals = h.states.loc[FIRST_LAG_YEAR:forecast_year - 1].sum()
    return list(totals.sort_values(ascending=False, kind="stable").index[:N_LARGE])


def state_kappas(ratios: pd.DataFrame, version: str, large: list, states) -> np.ndarray:
    """One kappa per state. Version (a): the same for all. Version (b): one for the large states and one
    for the other 41, each fitted on its own group's misses."""
    if version == "a":
        return np.full(len(states), fit_kappa(ratios))
    in_large = ratios.state.isin(large)
    k_large, k_small = fit_kappa(ratios[in_large]), fit_kappa(ratios[~in_large])
    return np.where(pd.Index(states).isin(large), k_large, k_small)


# --------------------------------------------------------------------------- steps 2 and 4: the simulation

def draw_shares(rng, expected: np.ndarray, kappa) -> np.ndarray:
    """DRAWS sets of shares scattered around `expected`; a larger kappa keeps them closer to it.

    Each share is drawn from a gamma distribution with shape kappa x share and scale 1 / kappa (its
    average is the share itself), and every set is rescaled to add to 1. With one kappa for all places
    this is exactly a Dirichlet(kappa x expected) draw. With different kappas, the places with the smaller
    kappa wander further, which is version (b).
    """
    kappa = np.broadcast_to(np.asarray(kappa, dtype=float), expected.shape)
    g = rng.gamma(shape=kappa * expected, scale=1 / kappa, size=(DRAWS, len(expected)))
    return g / g.sum(axis=1, keepdims=True)


def starting_shares(last_counts: np.ndarray) -> np.ndarray:
    """Last year's counts as shares that add to 1. The floor keeps a count of zero from becoming a share of zero."""
    return (last_counts + EPS) / (last_counts + EPS).sum()


def simulate_states(rng, last_counts: np.ndarray, kappas, total: int) -> np.ndarray:
    """DRAWS possible years: draw the states' shares, then count `total` children out across the states.

    Counting out (a multinomial draw) adds the chance that comes from children being whole people, which
    multiplying the total by the shares would leave out (AS-24). Every row adds up to exactly `total`.
    """
    return rng.multinomial(total, draw_shares(rng, starting_shares(last_counts), kappas))


def simulate_counties(rng, state_draws: np.ndarray, last_counts: np.ndarray, kappa: float) -> np.ndarray:
    """Split each simulated state total across its county categories (the last column is "other counties")."""
    if len(last_counts) == 1:
        return state_draws[:, None]  # no listed county: the whole state is "other counties"
    return rng.multinomial(state_draws, draw_shares(rng, starting_shares(last_counts), kappa))


# --------------------------------------------------------------------------- step 5: the 50-release rule

def expected_county_releases(total: int, state_share: float, last_counts: np.ndarray) -> np.ndarray:
    """What each listed county expects before any random draw: total x the state's share x the county's
    share of its state. The simulated average lands on this figure, give or take a little chance."""
    return total * state_share * starting_shares(last_counts)[:-1]


def fold_small(county_draws: np.ndarray, expected: np.ndarray) -> tuple:
    """Apply ORR's 50-release rule (FR-19, NFR-03, AS-26).

    A county expecting fewer than 50 releases gets no row: its draws are added to the "other counties"
    draws before any average or percentile is taken. The test uses `expected` (see the function above),
    not the average of the draws, so a county right at the line is shown or folded the same way whatever
    the random seed. Returns (the columns that keep their own row, the "other counties" draws with the
    folded counties added in).
    """
    keep = np.asarray(expected) >= THRESHOLD
    other = county_draws[:, -1] + county_draws[:, :-1][:, ~keep].sum(axis=1)
    return np.flatnonzero(keep), other


def measure_rows(place: dict, draws: np.ndarray, school_age_fraction: float) -> list[dict]:
    """The two rows for one place: releases, and the school-age children among them (step 6).

    expected = the average of the draws; the 80% range = their 10th and 90th percentiles; all rounded to
    whole children. School-age figures are the same three numbers times the school-age fraction.
    """
    low, high = np.percentile(draws, [100 * RANGE[0], 100 * RANGE[1]])
    rows = []
    for measure, factor in (("releases", 1.0), ("school_age", school_age_fraction)):
        expected = int(np.round(factor * draws.mean()))
        rows.append({**place, "measure": measure, "expected": expected,
                     "lower_80": min(int(np.round(factor * low)), expected),    # for a very lopsided place the
                     "upper_80": max(int(np.round(factor * high)), expected)})  # average can sit outside the range
    return rows


def scenario_table(h: History, volumes: list, kappas, kappa_county: float, school_age_fraction: float) -> pd.DataFrame:
    """Every row planners will see: scenario x place x measure (the layout is in the spec)."""
    rng = np.random.default_rng(SEED)
    last_states = h.states.loc[BASE_YEAR].to_numpy()
    rows = []
    for scenario in volumes:
        total = scenario["national_releases"]
        state_draws = simulate_states(rng, last_states, kappas, total)
        for j, st in enumerate(h.states.columns):
            place = {"scenario": scenario["id"], "state": st, "state_name": h.state_names[st]}
            keys = listed(h, st, BASE_YEAR)  # only counties listed in the base year can get a row (AS-25)
            last = category_counts(h, st, BASE_YEAR, keys)
            draws = simulate_counties(rng, state_draws[:, j], last, kappa_county)
            shown, other = fold_small(draws, expected_county_releases(total, starting_shares(last_states)[j], last))
            rows += measure_rows({**place, "geo_level": "state"}, state_draws[:, j], school_age_fraction)
            for i in shown:
                info = h.county_info.loc[keys[i]]
                rows += measure_rows({**place, "geo_level": "county", "county_key": keys[i],
                                      "county_fips": info.county_fips, "county_name": info.county_name},
                                     draws[:, i], school_age_fraction)
            rows += measure_rows({**place, "geo_level": "other_counties", "county_name": f"Other counties, {st}"},
                                 other, school_age_fraction)
    return pd.DataFrame(rows, columns=contract.COLUMNS)


# --------------------------------------------------------------------------- step 6: school-age children

def orr_age_tables(path=AGE_FILE) -> tuple:
    """ORR's age file: ({fiscal year: {age group: share}}, lambda).

    The yearly table gives the share of children in ORR's care in each age group; each year is rescaled to
    add to 1 because ORR rounds to two decimals. lambda is the part of the 0-12 group aged 5 to 12, from
    the FY2026 month-end counts: (6-12 + one sixth of 0-5) / (0-5 + 6-12) (AS-35).
    """
    rows = list(openpyxl.load_workbook(path, data_only=True).worksheets[0].iter_rows(values_only=True))
    start = next(i for i, r in enumerate(rows) if r[0] == "Age" and str(r[1] or "").startswith("FY"))
    years = [int(str(v)[2:]) for v in rows[start][1:] if v]
    shares = {fy: {} for fy in years}
    for r in rows[start + 1:]:
        if not r[0] or str(r[0]).startswith("*"):
            break  # the table ends at the first blank row or footnote
        for fy, v in zip(years, r[1:]):
            shares[fy][str(r[0]).rstrip("*")] = float(v)
    shares = {fy: {group: v / sum(s.values()) for group, v in s.items()} for fy, s in shares.items()}

    start = next(i for i, r in enumerate(rows) if r[0] == "Age Group")
    counts = {r[0]: sum(v for v in r[1:] if v is not None) for r in rows[start + 1:start + 6]}
    return shares, (counts["6-12"] + counts["0-5"] / 6) / (counts["0-5"] + counts["6-12"])


def age_mix() -> dict:
    """The school-age fraction f and its range, as the spec asks them to be recorded (FR-15, AS-34 to AS-37).

    f = share(13-14) + share(15-16) + share(17+) + lambda x share(0-12), which is 1 - (1 - lambda) x share(0-12).
    """
    shares, lam = orr_age_tables()
    f = lambda year, part: 1 - (1 - part) * shares[year]["0-12"]
    return {"ages": "13-14, 15-16 and 17+, plus lambda x 0-12", "lambda": round(lam, 4),
            "point_fiscal_years": POINT_FISCAL_YEARS,
            "school_age_fraction": round(float(np.mean([f(y, lam) for y in POINT_FISCAL_YEARS])), 4),
            "low": round(min(f(y, LAMBDA_EVEN) for y in shares), 4),   # ages spread evenly, in the lowest year
            "high": round(max(f(y, 1.0) for y in shares), 4)}          # every child counted


# --------------------------------------------------------------------------- step 8: calibration

def backtest(h: History, ratios_s: pd.DataFrame, ratios_c: pd.DataFrame, version: str) -> tuple:
    """Replay each held-out year from earlier years only and see whether the 80% ranges held (FR-14, NFR-10).

    For year t: fit kappa on the changes before t, start from year t-1's shares, use year t's actual
    national total, simulate, and compare each place's range with what really happened. County categories
    are the counties listed in both years plus "other" (AS-16); a county expecting fewer than 50 releases
    would get no row, so it is not scored. Returns (one row per state and year, one row per year for counties).
    """
    rng = np.random.default_rng(SEED)  # the same seed for both versions, so they face the same luck
    state_rows, county_rows = [], []
    for year in HELD_OUT:
        large = large_states(h, year)
        kappas = state_kappas(ratios_s[ratios_s.year < year], version, large, h.states.columns)
        kappa_county = fit_kappa(ratios_c[ratios_c.year < year])
        total = int(h.national[year])
        last_states = h.states.loc[year - 1].to_numpy()
        draws = simulate_states(rng, last_states, kappas, total)
        low, high = np.round(np.percentile(draws, [100 * RANGE[0], 100 * RANGE[1]], axis=0))
        actual = h.states.loc[year].to_numpy()
        width = 100 * (high - low) / total  # in share points, so large and small years can be pooled
        outside = 100 * (np.clip(low - actual, 0, None) + np.clip(actual - high, 0, None)) / total
        places = inside = 0
        for j, st in enumerate(h.states.columns):
            state_rows.append({"fiscal_year": year, "state": st, "size_group": "large" if st in large else "small",
                               "inside": bool(low[j] <= actual[j] <= high[j]), "width": width[j],
                               "score": width[j] + MISS_PENALTY * outside[j], "actual": actual[j]})
            keys = [k for k in listed(h, st, year - 1) if k in set(listed(h, st, year))]
            if not keys:
                continue
            last = category_counts(h, st, year - 1, keys)
            county_draws = simulate_counties(rng, draws[:, j], last, kappa_county)
            shown, _ = fold_small(county_draws, expected_county_releases(total, starting_shares(last_states)[j], last))
            if not len(shown):
                continue
            c_low, c_high = np.round(np.percentile(county_draws[:, shown], [100 * RANGE[0], 100 * RANGE[1]], axis=0))
            c_actual = h.counties[(year, st)][keys].to_numpy()[shown]
            places += len(shown)
            inside += int(((c_low <= c_actual) & (c_actual <= c_high)).sum())
        county_rows.append({"fiscal_year": year, "places": places, "inside_80": inside})
    return pd.DataFrame(state_rows), pd.DataFrame(county_rows)


def calibration_tables(states: pd.DataFrame, counties: pd.DataFrame) -> tuple:
    """The two calibration files: per year for states and counties, and per year by state size."""
    by_year = states.groupby("fiscal_year").inside.agg(places="size", inside_80="sum").reset_index()
    calibration = pd.concat([by_year.assign(geo_level="state"), counties.assign(geo_level="county")])
    calibration = calibration.sort_values(["fiscal_year", "geo_level"], ascending=[True, False], ignore_index=True)
    calibration["coverage"] = (calibration.inside_80 / calibration.places).round(3)
    by_size = states.groupby(["fiscal_year", "size_group"]).agg(
        places=("inside", "size"), inside_80=("inside", "sum"), mean_width_share_points=("width", "mean")).reset_index()
    by_size["coverage"] = (by_size.inside_80 / by_size.places).round(3)
    by_size["mean_width_share_points"] = by_size.mean_width_share_points.round(3)
    return (calibration[contract.CALIBRATION_COLUMNS].astype({"places": int, "inside_80": int}),
            by_size[["fiscal_year", "size_group", "places", "inside_80", "coverage", "mean_width_share_points"]])


def comparison_table(by_version: dict) -> pd.DataFrame:
    """The two versions side by side, pooled over the held-out years, for all, large and small states.

    The interval score of one state-year is the width of its 80% range plus 10 times any distance by which
    the actual figure fell outside it, in share points. Lower is better: it rewards ranges that are narrow
    and still hold, so coverage cannot be bought just by widening every range (Gneiting and Raftery 2007).
    """
    rows = []
    for version, states in by_version.items():
        for group in ("all", "large", "small"):
            part = states if group == "all" else states[states.size_group == group]
            rows.append({"version": version, "size_group": group, "places": len(part),
                         "inside_80": int(part.inside.sum()), "coverage": round(part.inside.mean(), 3),
                         "mean_width_share_points": round(part.width.mean(), 3),
                         "mean_interval_score": round(part.score.mean(), 3)})
    return pd.DataFrame(rows)


def choose_version(comparison: pd.DataFrame) -> tuple:
    """Which version the tables use, and why (AS-40).

    The rule: among the versions whose pooled coverage passes 70%-90%, take the one with the lower mean
    interval score over all state-years. A tie, or no version passing, goes to (a), the simpler one.
    FORCE_VERSION at the top of the file overrules the rule. Returns (version, the reason in a sentence).
    """
    rows = comparison.set_index(["version", "size_group"])
    pooled = rows.xs("all", level="size_group")
    if FORCE_VERSION in VERSIONS:
        return FORCE_VERSION, f"Version ({FORCE_VERSION}) was set by hand (FORCE_VERSION in src/scenarios.py)."
    passing = [v for v in VERSIONS if COVERAGE_BAND[0] <= pooled.coverage[v] <= COVERAGE_BAND[1]]
    best = min(passing, key=lambda v: (pooled.mean_interval_score[v], v)) if passing else "a"
    other = "b" if best == "a" else "a"
    if not passing:
        return best, "Neither version's pooled coverage is between 70% and 90%, so the simpler version (a) is used."
    if len(passing) == 1 or pooled.mean_interval_score[best] < pooled.mean_interval_score[other]:
        reason = (f"Version ({best}) has the lower mean interval score over the {pooled.places[best]} held-out "
                  f"state-years ({pooled.mean_interval_score[best]:.2f} against {pooled.mean_interval_score[other]:.2f} "
                  f"share points). Its ranges held for {rows.coverage[(best, 'large')]:.0%} of the 10 largest states' "
                  f"years and {rows.coverage[(best, 'small')]:.0%} of the others', against "
                  f"{rows.coverage[(other, 'large')]:.0%} and {rows.coverage[(other, 'small')]:.0%}.")
    else:
        reason = "The two versions have the same mean interval score, so the simpler version (a) is used."
    return best, reason + (" The rule is in choose_version in src/scenarios.py. The same replay picks the version, "
                           "so its coverage is not an independent check.")


# --------------------------------------------------------------------------- steps 7 and 9: write and report

def manifest(volumes: list, mix: dict, version: str, reason: str, kappa: dict) -> dict:
    """results/scenarios.json: what the tables are, how they were made, and with which settings."""
    spread = (f"one kappa for all 51 places ({kappa['state_one_kappa']:,.0f})" if version == "a" else
              f"one kappa for the {N_LARGE} largest states ({kappa['state_large']:,.0f}) and one for the other 41 "
              f"({kappa['state_small']:,.0f})")
    return {
        "base_fiscal_year": BASE_YEAR,
        "share_model": "Last year's shares with an error model (fallback, BRD risk R-03)",
        "draws": DRAWS, "seed": SEED, "range": list(RANGE),
        "scenarios": volumes,
        "measures": [
            {"id": "releases", "label": "Children released to sponsors",
             "definition": "Unaccompanied children expected to be released to sponsors in the place in one fiscal "
                           "year, if the national total were the scenario's. Counted at the first release location."},
            {"id": "school_age", "label": "School-age children",
             "definition": f"Children released who are aged 5 to 17: releases x {mix['school_age_fraction']:.3f}. The "
                           "fraction is ORR's published age mix of children in its care (ages 13 and over, plus the "
                           f"part of the 0-12 group aged 5 to 12), applied to every place alike (assumption A-03). "
                           f"Local age mixes may differ; the fraction could be as low as {mix['low']:.3f} or as high "
                           f"as {mix['high']:.1f}."}],
        "age_mix_source": "ORR UAC Age Data, yearly table FY2019-FY2025 and FY2026 monthly counts "
                          "(published 2026-10-07), downloaded 2026-11-04",
        "age_mix": mix,
        "fallback_error_model": (
            "Next year's expected shares are FY2025's actual shares. Each simulated year draws the states' shares "
            f"around them with {spread}, then counts the scenario's children out across the states (a multinomial "
            f"draw). Inside each state the listed counties and other counties are drawn the same way with kappa "
            f"{kappa['county']:,.0f}. Kappa is fitted to the year-over-year changes FY2014-FY2025: each place's "
            "squared miss under last year's shares is divided by its counting noise, and kappa is the value at which "
            "the Dirichlet-multinomial expects the same total, every place weighted equally."),
        "error_model_version": version,
        "version_choice": reason,
        "kappa": kappa,
    }


def main():
    h = history()
    volumes = scenario_volumes(h.national)
    ratios_s, ratios_c = state_ratios(h), county_ratios(h)

    # Step 8 first: both versions go through the same replay, and the comparison picks the version.
    runs = {version: backtest(h, ratios_s, ratios_c, version) for version in VERSIONS}
    comparison = comparison_table({version: states for version, (states, _) in runs.items()})
    version, reason = choose_version(comparison)
    calibration, by_size = calibration_tables(*runs[version])

    # Steps 2 to 7: the scenario tables, with kappa fitted on all eleven changes.
    large = large_states(h, BASE_YEAR + 1)
    kappas, kappa_county = state_kappas(ratios_s, version, large, h.states.columns), fit_kappa(ratios_c)
    in_large = ratios_s.state.isin(large)
    kappa = {"state_one_kappa": round(fit_kappa(ratios_s)), "state_large": round(fit_kappa(ratios_s[in_large])),
             "state_small": round(fit_kappa(ratios_s[~in_large])), "county": round(kappa_county),
             "large_states": large, "fitted_on": f"FY{FIRST_LAG_YEAR}-FY{BASE_YEAR}"}
    mix = age_mix()
    table = scenario_table(h, volumes, kappas, kappa_county, mix["school_age_fraction"])

    RESULTS.mkdir(exist_ok=True)
    record = manifest(volumes, mix, version, reason, kappa)
    (RESULTS / contract.MANIFEST).write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    table.to_csv(RESULTS / contract.TABLE, index=False)
    calibration.to_csv(RESULTS / contract.CALIBRATION, index=False)
    by_size.to_csv(RESULTS / contract.BY_SIZE, index=False)
    comparison.to_csv(RESULTS / "scenario_variant_comparison.csv", index=False)

    # Report the numbers a reader would check first, then run the same checks the app runs.
    releases = table[table.measure == "releases"]
    for s in volumes:
        rows = releases[releases.scenario == s["id"]]
        tx = rows[(rows.geo_level == "state") & (rows.state == "TX")].iloc[0]
        other = rows[rows.geo_level == "other_counties"].expected.sum() / s["national_releases"]
        print(f"{s['label']:6s} {s['national_releases']:>7,} (FY{s['source_fiscal_year']}): Texas {tx.expected:,} "
              f"({tx.lower_80:,} to {tx.upper_80:,}); county rows {int((rows.geo_level == 'county').sum())}; "
              f"other counties {other:.1%}")
    print("kappa:", {k: v for k, v in kappa.items() if k != "large_states"}, "| large states:", " ".join(large))
    print(comparison.to_string(index=False))
    print(f"version ({version}) chosen. {reason}")
    print("pooled coverage:", contract.coverage(calibration), contract.coverage_by_size(RESULTS),
          f"| school-age fraction {mix['school_age_fraction']} ({mix['low']} to {mix['high']})")
    problems = contract.problems(*contract.load(RESULTS))
    print("contract checks:", "all passed" if not problems else problems)
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
