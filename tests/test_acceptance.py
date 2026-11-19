"""Acceptance tests for the owner's Week 5 share model and Week 6 scenario engine.

Each test is skipped until the output it checks exists (see docs/spec_week5_week6.md). The tests marked
"review" come from the outside review of the math doc (2026-11-05); "decided" marks the model decisions
the owner confirmed on 2026-11-08, and "decided 2026-11-11" those made after the logic check: the
pessimistic winner rule and the two versions of the fallback's error model.
"""
import json
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd
import pytest

from src import measure
from src import scenario_contract as sc
from src.share_baseline import EPS, state_shares

ROOT = Path(__file__).resolve().parent.parent
BACKTEST = ROOT / "results/share_model_backtest.csv"
SUMMARY = ROOT / "results/share_model_summary.csv"
MODEL_RECORD = ROOT / "results/share_model.json"
CHECKS = ROOT / "results/share_model_backtest_checks.csv"
BY_SIZE = ROOT / "results/scenario_calibration_by_size.csv"
VERSIONS = ROOT / "results/scenario_variant_comparison.csv"
AGE_FILE = ROOT / "data/raw/orr/UAC-Age-Data_Sep_2026_0.xlsx"
HELD_OUT = range(2018, 2026)
LEVELS = ("state", "county")
MAX_RHAT, MIN_ESS = 1.01, 400  # Vehtari et al. (2021), "Rank-normalization, folding, and localization"
TIE = 0.0005           # (decided) log-score differences smaller than this are ties, and ties go to naive
MIN_WINS = 6           # (decided) the model must beat naive in at least 6 of the 8 held-out years
FIRST_LAG_YEAR = 2014  # (decided) FY2014 serves only as "last year" for FY2015
CHECK_FLOOR = 0.5      # (decided) the refit that shows the floor barely moves rho
LAMBDA_EVEN = 8 / 13   # (decided) the low end: ages spread evenly within ORR's 0-12 group
# (decided 2026-11-11) The winner rule is pessimistic: it must also hold under these two scorings.
#   floor_0.5       naive's forecast gets a floor of 0.5 of a release instead of 0.0001
#   zeros_left_out  places with no releases the year before are left out of that year's score
CHECK_SCORINGS = ("floor_0.5", "zeros_left_out")
SIZE_GROUPS = {"all": 408, "large": 80, "small": 328}  # state-years pooled over the 8 held-out years

week5 = pytest.mark.skipif(not BACKTEST.exists() or not SUMMARY.exists(),
                           reason="Week 5 output not built yet (src/share_model.py)")
week5_record = pytest.mark.skipif(not MODEL_RECORD.exists(),
                                  reason="Week 5 model record not written yet (results/share_model.json)")
week6 = pytest.mark.skipif(not sc.available(), reason="Week 6 output not built yet (src/scenarios.py)")
week6_by_size = pytest.mark.skipif(not BY_SIZE.exists(),
                                   reason="Week 6 calibration by state size not written yet")
week5_checks = pytest.mark.skipif(not CHECKS.exists(),
                                  reason="pessimistic scorings not written yet (share_model_backtest_checks.csv)")
week6_versions = pytest.mark.skipif(not VERSIONS.exists(),
                                    reason="comparison of the two fallback versions not written yet")
needs_data = pytest.mark.skipif(not (ROOT / "data/processed/releases_by_fy_geo.parquet").exists(),
                                reason="run src/build_dataset.py and src/measure.py first")


def log_gap(bt: pd.DataFrame, level: str, method: str) -> pd.DataFrame:
    """Per held-out year: the method's log score minus naive's, with that year's releases.

    Gaps are rounded to six decimals, so a difference of exactly 0.0005 counts as a win and is not left to
    floating-point noise (-3.1675 minus -3.1680 is not exactly 0.0005 in binary).
    """
    mine = bt[(bt.level == level) & (bt.method == method)].set_index("fiscal_year")
    naive = bt[(bt.level == level) & (bt.method == "naive")].set_index("fiscal_year")
    return pd.DataFrame({"gap": (mine.log_score - naive.log_score).round(6), "releases": mine.releases})


def passes_winner_rule(bt: pd.DataFrame, level: str, method: str) -> bool:
    """(decided) Both mean log scores beat naive's, and at least 6 of the 8 years do; ties go to naive."""
    g = log_gap(bt, level, method)
    if len(g) != len(HELD_OUT) or g.gap.isna().any():
        return False  # a missing year can't count as a win
    release_weighted = round((g.gap * g.releases).sum() / g.releases.sum(), 6)
    equal_weighted = round(g.gap.mean(), 6)
    return release_weighted >= TIE and equal_weighted >= TIE and int((g.gap >= TIE).sum()) >= MIN_WINS


def passes_pessimistic_rule(bt: pd.DataFrame, checks: pd.DataFrame, level: str, method: str) -> bool:
    """(decided 2026-11-11) The winner rule must hold under the main scoring and under each check scoring."""
    return passes_winner_rule(bt, level, method) and all(
        passes_winner_rule(checks[checks.scoring == scoring], level, method) for scoring in CHECK_SCORINGS)


def naive_state_log_score(wide: pd.DataFrame, fy: int, scoring: str) -> tuple[float, int]:
    """Naive's state log score for one held-out year under a check scoring, and the releases it scores."""
    last, actual = wide.loc[fy - 1].to_numpy(), wide.loc[fy].to_numpy()
    if scoring == "zeros_left_out":
        keep = last > 0
        last, actual = last[keep], actual[keep]
        p = last / last.sum()
    else:
        p = (last + CHECK_FLOOR) / (last + CHECK_FLOOR).sum()
    return float(np.sum(actual * np.log(p)) / actual.sum()), int(actual.sum())


def orr_yearly_age_shares(path=AGE_FILE) -> dict:
    """ORR's yearly table: {fiscal year: {age group: share}}, each year rescaled to add to 1."""
    rows = [r for r in openpyxl.load_workbook(path, data_only=True).worksheets[0].iter_rows(values_only=True)]
    start = next(i for i, r in enumerate(rows) if r[0] == "Age" and str(r[1] or "").startswith("FY"))
    years = [int(str(v)[2:]) for v in rows[start][1:] if v]
    shares = {fy: {} for fy in years}
    for r in rows[start + 1:]:
        if not r[0] or str(r[0]).startswith("*"):
            break
        for fy, v in zip(years, r[1:]):
            shares[fy][str(r[0]).rstrip("*")] = float(v)
    return {fy: {g: v / sum(s.values()) for g, v in s.items()} for fy, s in shares.items()}


def orr_monthly_lambda(path=AGE_FILE) -> float:
    """(decided 2026-11-10) Part of the 0-12 group aged 5-12, from ORR's FY2026 month-end counts:
    (6-12 + one sixth of 0-5) / (0-5 + 6-12), summed over the months. ORR does not split 0-5."""
    rows = [r for r in openpyxl.load_workbook(path, data_only=True).worksheets[0].iter_rows(values_only=True)]
    start = next(i for i, r in enumerate(rows) if r[0] == "Age Group")
    counts = {r[0]: sum(v for v in r[1:] if v is not None) for r in rows[start + 1:start + 6]}
    return (counts["6-12"] + counts["0-5"] / 6) / (counts["0-5"] + counts["6-12"])


def school_age_fraction(shares: dict, lam: float) -> float:
    """f = share(13-14) + share(15-16) + share(17+) + lambda x share(0-12)."""
    return 1 - (1 - lam) * shares["0-12"]


@week5
def test_backtest_has_every_held_out_year_and_the_baseline():  # FR-12
    bt = pd.read_csv(BACKTEST)
    for level in LEVELS:
        for fy in HELD_OUT:
            methods = set(bt[(bt.level == level) & (bt.fiscal_year == fy)].method)
            assert "naive" in methods and len(methods) >= 2, (level, fy, methods)


@week5
def test_backtest_scores_are_valid():  # FR-12
    bt = pd.read_csv(BACKTEST)
    assert bt[["mae_share_points", "log_score"]].notna().all().all()
    assert (bt.mae_share_points >= 0).all() and (bt.log_score <= 0).all()


@week5
def test_summary_compares_the_model_with_naive():  # FR-12
    summary = pd.read_csv(SUMMARY)
    for level in LEVELS:
        methods = set(summary[summary.level == level].method)
        assert "naive" in methods and len(methods) >= 2, (level, methods)


@week5
def test_summary_matches_the_backtest():  # FR-12 (review: both averages, and years won against naive)
    bt, summary = pd.read_csv(BACKTEST), pd.read_csv(SUMMARY)
    assert "releases" in bt.columns and (bt.releases > 0).all()
    for col in ("weighting", "years_beating_naive_mae", "years_beating_naive_log"):
        assert col in summary.columns, col
    for (level, method), rows in bt.groupby(["level", "method"]):
        naive = bt[(bt.level == level) & (bt.method == "naive")].set_index("fiscal_year")
        mine = rows.set_index("fiscal_year")
        wins_mae = int((mine.mae_share_points < naive.mae_share_points).sum())
        wins_log = int(((mine.log_score - naive.log_score).round(6) >= TIE).sum())  # (decided) smaller gaps are ties
        for weighting in ("release", "equal"):
            row = summary[(summary.level == level) & (summary.method == method) & (summary.weighting == weighting)]
            assert len(row) == 1, (level, method, weighting)
            row = row.iloc[0]
            for col in ("mae_share_points", "log_score"):
                expect = ((rows[col] * rows.releases).sum() / rows.releases.sum() if weighting == "release"
                          else rows[col].mean())
                assert abs(row[col] - expect) <= 0.001, (level, method, weighting, col, row[col], expect)
            assert (row.years_beating_naive_mae, row.years_beating_naive_log) == (wins_mae, wins_log), \
                (level, method, weighting)


@week5_record
def test_model_record_has_the_rule_the_winner_priors_and_sampler():  # FR-12, NFR-07 (review)
    record = json.loads(MODEL_RECORD.read_text(encoding="utf-8"))
    for key in ("winner_rule", "winner", "priors", "sampler", "diagnostics"):
        assert key in record, f"share_model.json needs '{key}'"
    assert str(record["winner_rule"]).strip()
    assert record["priors"] and any("kappa" in name.lower() for name in record["priors"])
    assert all(str(text).strip() for text in record["priors"].values())
    assert {"chains", "draws", "tune", "target_accept", "seed"} <= set(record["sampler"])
    assert record["sampler"]["chains"] >= 2
    if SUMMARY.exists():
        summary = pd.read_csv(SUMMARY)
        for level in LEVELS:
            assert record["winner"][level] in set(summary[summary.level == level].method), level


@week5
@week5_record
def test_the_winner_is_the_one_the_fixed_rule_picks():  # FR-12 (decided; pessimistic since 2026-11-11)
    assert CHECKS.exists(), "the winner needs the pessimistic scorings: write results/share_model_backtest_checks.csv"
    bt, checks = pd.read_csv(BACKTEST), pd.read_csv(CHECKS)
    record = json.loads(MODEL_RECORD.read_text(encoding="utf-8"))
    method = record.get("model_method")
    assert method and method != "naive" and method in set(bt.method), \
        "share_model.json needs 'model_method': your method's name in the backtest"
    assert set(record.get("scorings", [])) == {"floor_0.0001", *CHECK_SCORINGS}, "list the three scorings in 'scorings'"
    for level in LEVELS:
        expected = method if passes_pessimistic_rule(bt, checks, level, method) else "naive"
        assert record["winner"][level] == expected, (level, record["winner"][level], expected)


@week5
@week5_checks
def test_pessimistic_scorings_cover_every_year_level_and_method():  # FR-12 (decided 2026-11-11)
    bt, checks = pd.read_csv(BACKTEST), pd.read_csv(CHECKS)
    assert {"fiscal_year", "level", "method", "scoring", "releases", "log_score"} <= set(checks.columns)
    assert set(checks.scoring) == set(CHECK_SCORINGS), set(checks.scoring)
    assert checks.log_score.notna().all() and (checks.log_score <= 0).all()
    key = ["fiscal_year", "level", "method"]
    for scoring in CHECK_SCORINGS:
        part = checks[checks.scoring == scoring]
        assert not part.duplicated(key).any(), scoring
        both = bt.merge(part, on=key, how="left", suffixes=("_main", ""))
        assert both.log_score.notna().all(), (scoring, "a year, level or method in the backtest is missing")
        if scoring == "floor_0.5":       # the same children are scored; only naive's floor changes
            assert (both.releases == both.releases_main).all()
        else:                            # leaving places out can only score fewer children
            assert (both.releases <= both.releases_main).all()


@week5_checks
@needs_data
def test_naive_state_scores_under_the_check_scorings_match_the_data():  # FR-12 (decided 2026-11-11)
    checks, wide = pd.read_csv(CHECKS), state_shares()
    naive = checks[(checks.level == "state") & (checks.method == "naive")].set_index(["scoring", "fiscal_year"])
    for scoring in CHECK_SCORINGS:
        for fy in HELD_OUT:
            score, releases = naive_state_log_score(wide, fy, scoring)
            row = naive.loc[(scoring, fy)]
            assert row.log_score == pytest.approx(score, abs=1e-5), (scoring, fy, row.log_score, score)
            assert row.releases == releases, (scoring, fy)


@week5_record
def test_the_floor_matches_naive_and_the_refit_is_recorded():  # FR-11 (decided)
    record = json.loads(MODEL_RECORD.read_text(encoding="utf-8"))
    assert record.get("floor") == pytest.approx(EPS), "use the floor naive uses (EPS in src/share_baseline.py)"
    checks = pd.DataFrame(record.get("floor_check", []))
    assert not checks.empty, "share_model.json needs 'floor_check'"
    state = checks[(checks["level"] == "state") & (checks["trained_through"] == max(HELD_OUT))]
    floors = sorted(state["floor"])
    assert floors == pytest.approx([EPS, CHECK_FLOOR]), floors
    assert state["rho_mean"].notna().all()


@week5_record
def test_fy2014_is_the_first_last_year():  # FR-11, FR-12 (decided)
    record = json.loads(MODEL_RECORD.read_text(encoding="utf-8"))
    assert record.get("first_lag_year") == FIRST_LAG_YEAR
    fits = pd.DataFrame(record["diagnostics"])
    assert "transitions" in fits.columns, "record 'transitions' for each fit"
    wrong = fits[fits.transitions != fits.trained_through - FIRST_LAG_YEAR]
    assert wrong.empty, wrong[["level", "trained_through", "transitions"]].to_dict("records")[:3]


@week5_record
def test_every_fit_passes_the_sampler_checks():  # FR-11 (review)
    fits = pd.DataFrame(json.loads(MODEL_RECORD.read_text(encoding="utf-8"))["diagnostics"])
    for level in LEVELS:
        trained = set(fits[fits.level == level].trained_through)
        needed = {fy - 1 for fy in HELD_OUT} | {max(HELD_OUT)}  # every backtest fit, plus the one the scenarios use
        assert needed <= trained, (level, sorted(needed - trained))
    failed = fits[(fits.max_rhat > MAX_RHAT) | (fits.min_ess_bulk < MIN_ESS) | (fits.divergences > 0)]
    assert failed.empty, failed.to_dict("records")[:3]


@week6
@needs_data
def test_scenarios_are_the_lowest_median_and_highest_years():  # FR-13, with FY2020 set aside (AS-45)
    df = measure.load()
    national = df[(df.geo_level == "national") & df.fiscal_year.isin(measure.FISCAL_YEARS)]
    national = national.set_index("fiscal_year").releases
    kept = national.drop(index=[2020]).sort_values()  # the owner's decision of 2026-11-18
    target = {"low": kept.iloc[0], "median": kept.iloc[(len(kept) - 1) // 2], "high": kept.iloc[-1]}  # lower middle
    manifest, _, _ = sc.load()
    for s in manifest["scenarios"]:
        assert s["national_releases"] == target[s["id"]]
        assert national[s["source_fiscal_year"]] == s["national_releases"]
        assert s["source_fiscal_year"] != 2020


@week6
def test_outputs_pass_the_contract_checks():  # FR-18, FR-19, NFR-03
    assert sc.problems(*sc.load()) == []


@week6
@needs_data
def test_only_counties_listed_in_fy2025_appear():  # FR-19, NFR-03 (decided)
    df = measure.load()
    listed_2025 = set(df[(df.geo_level == "county") & (df.fiscal_year == 2025)].county_key)
    _, table, _ = sc.load()
    shown = set(table[table.geo_level == "county"].county_key)
    assert shown <= listed_2025, sorted(shown - listed_2025)[:5]


@week6
def test_every_place_has_a_school_age_figure():  # FR-15
    _, table, _ = sc.load()
    places = table.assign(county_key=table.county_key.fillna(""))
    per_place = places.groupby(["scenario", "geo_level", "state", "county_key"]).measure.agg(set)
    assert per_place.apply(lambda m: {"releases", "school_age"} <= m).all()


@week6
def test_80_percent_ranges_cover_about_80_percent():  # FR-14, NFR-10
    _, _, calibration = sc.load()
    assert set(HELD_OUT) <= set(calibration.fiscal_year)
    cover = sc.coverage(calibration)
    for level in LEVELS:
        assert 0.70 <= cover[level] <= 0.90, (level, cover[level])


@week6_by_size
def test_coverage_is_reported_for_large_and_small_states():  # FR-14, NFR-10 (review)
    by_size = pd.read_csv(BY_SIZE)
    assert {"fiscal_year", "size_group", "places", "inside_80", "coverage", "mean_width_share_points"} <= set(
        by_size.columns)
    for fy in HELD_OUT:
        year = by_size[by_size.fiscal_year == fy].set_index("size_group")
        assert set(year.index) == {"large", "small"}, fy
        assert year.places["large"] == 10 and year.places.sum() == 51, (fy, year.places.to_dict())
    assert ((by_size.inside_80 <= by_size.places) & (by_size.mean_width_share_points > 0)).all()
    if sc.available():  # the two groups must add up to the state rows
        _, _, calibration = sc.load()
        states = calibration[calibration.geo_level == "state"].set_index("fiscal_year")
        both = by_size.groupby("fiscal_year")[["places", "inside_80"]].sum()
        for fy in HELD_OUT:
            assert tuple(both.loc[fy]) == (states.places[fy], states.inside_80[fy]), fy


@week6
def test_school_age_fraction_and_its_range_are_recorded():  # FR-15, A-03 (review)
    manifest, _, _ = sc.load()
    mix = manifest.get("age_mix")
    assert mix, "scenarios.json needs an age_mix block"
    assert str(mix.get("ages", "")).strip(), "say which ORR age groups count as school-age"
    assert 0 < mix["low"] <= mix["school_age_fraction"] <= mix["high"] <= 1, mix
    if AGE_FILE.exists():  # (decided) lambda, low, high and the point estimate follow ORR's file
        lam = orr_monthly_lambda()
        assert mix.get("lambda") == pytest.approx(lam, abs=0.001), f"(decided) lambda is ORR's split, {lam:.4f}"
        years = orr_yearly_age_shares()
        low = min(school_age_fraction(s, LAMBDA_EVEN) for s in years.values())
        high = max(school_age_fraction(s, 1.0) for s in years.values())
        point_years = mix.get("point_fiscal_years") or []
        assert point_years and set(point_years) <= set(years), point_years
        point = sum(school_age_fraction(years[fy], lam) for fy in point_years) / len(point_years)
        assert mix["low"] == pytest.approx(low, abs=0.005), (mix["low"], low)
        assert mix["high"] == pytest.approx(high, abs=0.005), (mix["high"], high)
        assert mix["school_age_fraction"] == pytest.approx(point, abs=0.005), (mix["school_age_fraction"], point)


@week6
def test_a_fallback_says_what_error_model_it_uses():  # R-03 (review)
    manifest, _, _ = sc.load()
    if "dirichlet" not in manifest["share_model"].lower():
        assert str(manifest.get("fallback_error_model", "")).strip(), "describe the fallback's error model"


@week6
@week6_versions
def test_the_two_fallback_versions_are_compared_head_to_head():  # FR-14, NFR-10 (decided 2026-11-11)
    versions = pd.read_csv(VERSIONS)
    assert {"version", "size_group", "places", "inside_80", "coverage", "mean_width_share_points",
            "mean_interval_score"} <= set(versions.columns)
    table = versions.set_index(["version", "size_group"])
    assert set(table.index) == {(v, g) for v in ("a", "b") for g in SIZE_GROUPS}, sorted(table.index)
    for version in ("a", "b"):
        rows = table.loc[version]
        assert rows.places.to_dict() == SIZE_GROUPS, (version, rows.places.to_dict())
        assert rows.inside_80["large"] + rows.inside_80["small"] == rows.inside_80["all"], version
        assert (rows.coverage - rows.inside_80 / rows.places).abs().max() <= 0.001, version
        assert (rows.mean_width_share_points > 0).all()
        assert (rows.mean_interval_score >= rows.mean_width_share_points - 1e-9).all()  # width plus penalties
    manifest, _, calibration = sc.load()
    chosen = manifest.get("error_model_version")
    assert chosen in ("a", "b"), "scenarios.json needs 'error_model_version': the version the tables use"
    assert str(manifest.get("version_choice", "")).strip(), "say in 'version_choice' why that version was chosen"
    states = calibration[calibration.geo_level == "state"]
    assert int(states.inside_80.sum()) == int(table.loc[(chosen, "all")].inside_80), \
        "scenario_calibration.csv must describe the chosen version"
