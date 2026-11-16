"""Tests for the share model's own calculations (src/share_model.py), on made-up inputs with known answers.

tests/test_acceptance.py checks the files the model writes. These tests check the steps inside it. The
last test fits the model to made-up data and takes about a minute, so it runs only when asked:
    UC_SLOW_TESTS=1 python -m pytest tests/test_share_model.py
"""
# ===================================================================================================
# HOW TO READ THIS FILE
# Business purpose: the backtest decides whether a model or "same as last year" feeds the scenario tables,
# so the scoring and the winner rule have to be right. Each test gives one step a small input whose answer
# can be worked out by hand. The recovery test at the end builds data from known settings (rho, kappa)
# and checks that the model finds them again.
#
# Python ideas: building a dataclass by hand for a test, pytest.approx, pytest.mark.skipif with an
# environment variable, monkeypatch to shorten the sampler run for a test.
# ===================================================================================================
import os

import numpy as np
import pandas as pd
import pytest

from src import scenarios as sc
from src import share_model as sm

slow = pytest.mark.skipif(not os.environ.get("UC_SLOW_TESTS"), reason="set UC_SLOW_TESTS=1 to run the model fit")


def tiny_history() -> sc.History:
    """Two states over two years. AA has two counties listed both years and one listed only in 2021;
    BB has no listed county."""
    states = pd.DataFrame({"AA": [1000.0, 1200.0], "BB": [40.0, 30.0]}, index=[2020, 2021])
    counties = {(2020, "AA"): pd.Series({"x|AA": 500.0, "y|AA": 300.0}),
                (2021, "AA"): pd.Series({"x|AA": 700.0, "y|AA": 200.0, "new|AA": 100.0})}
    return sc.History(national=None, states=states, counties=counties, state_names={}, county_info=None)


def table(gaps: list, level="state") -> pd.DataFrame:
    """A one-scoring score table where the model's log score is naive's plus the given gap each year."""
    rows = []
    for year, gap in zip(sm.HELD_OUT, gaps):
        rows.append({"fiscal_year": year, "level": level, "method": "naive", "releases": 1000 * (year - 2000), "log_score": -3.0})
        rows.append({"fiscal_year": year, "level": level, "method": sm.METHOD, "releases": 1000 * (year - 2000), "log_score": -3.0 + gap})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- data and forecasts

def test_county_blocks_use_counties_listed_in_both_years_plus_other():
    blocks = sm.blocks(tiny_history(), "county", 2021)
    assert [label for label, _, _ in blocks] == ["AA"]  # BB has only "other counties": nothing to predict
    _, last, now = blocks[0]
    assert last.tolist() == [500.0, 300.0, 200.0]  # x, y, then everything else in the state
    assert now.tolist() == [700.0, 200.0, 300.0]   # the county new to the list stays inside "other"


def test_state_block_is_the_whole_row():
    (label, last, now), = sm.blocks(tiny_history(), "state", 2021)
    assert (label, last.tolist(), now.tolist()) == ("US", [1000.0, 40.0], [1200.0, 30.0])


def test_rho_one_and_no_tilts_is_exactly_naive():
    last = np.array([500.0, 300.0, 0.0, 200.0])
    state = {"alpha": np.zeros((7, 4)), "rho": np.ones(7)}
    county = {"rho": np.ones(7), "delta": np.zeros(7)}
    assert sm.forecast("state", state, last) == pytest.approx(sm.naive(last))
    assert sm.forecast("county", county, last) == pytest.approx(sm.naive(last))


def test_rho_below_one_pulls_shares_together_and_the_other_offset_lifts_other():
    last = np.array([800.0, 150.0, 50.0])
    pulled = sm.forecast("state", {"alpha": np.zeros((3, 3)), "rho": np.full(3, 0.5)}, last)
    assert pulled[0] < 0.8 and pulled[2] > 0.05 and pulled.sum() == pytest.approx(1.0)
    lifted = sm.forecast("county", {"rho": np.ones(3), "delta": np.full(3, 0.5)}, last)
    assert lifted[-1] > 0.05 and lifted[0] < 0.8


def test_padding_keeps_values_and_marks_real_cells():
    values, mask = sm.padded([np.array([1.0, 2.0, 3.0]), np.array([4.0])])
    assert values.tolist() == [[1.0, 2.0, 3.0], [4.0, 0.0, 0.0]]
    assert mask.tolist() == [[1.0, 1.0, 1.0], [1.0, 0.0, 0.0]]


# --------------------------------------------------------------------------- scoring

def test_the_three_scorings_on_a_block_worked_by_hand():
    block = ("US", np.array([60.0, 40.0, 0.0]), np.array([50.0, 45.0, 5.0]))
    model = np.array([0.5, 0.4, 0.1])
    rows = pd.DataFrame(sm.score_year([block], [model])).set_index(["method", "scoring"])

    assert rows.releases[("naive", "floor_0.0001")] == 100 and rows.releases[("naive", "zeros_left_out")] == 95
    # main scoring: the third place had nothing last year, so naive gives it only the floor
    p = np.array([60.0001, 40.0001, 0.0001]) / 100.0003
    assert rows.log_score[("naive", "floor_0.0001")] == pytest.approx((50 * np.log(p[0]) + 45 * np.log(p[1]) + 5 * np.log(p[2])) / 100, abs=1e-6)
    # floor_0.5 changes naive only
    p = np.array([60.5, 40.5, 0.5]) / 101.5
    assert rows.log_score[("naive", "floor_0.5")] == pytest.approx(float(np.sum(block[2] * np.log(p))) / 100, abs=1e-6)
    assert rows.log_score[(sm.METHOD, "floor_0.5")] == rows.log_score[(sm.METHOD, "floor_0.0001")]
    assert rows.log_score[(sm.METHOD, "floor_0.0001")] == pytest.approx((50 * np.log(0.5) + 45 * np.log(0.4) + 5 * np.log(0.1)) / 100, abs=1e-6)
    # zeros_left_out drops the third place and rescales both forecasts over the two that remain
    assert rows.log_score[("naive", "zeros_left_out")] == pytest.approx((50 * np.log(0.6) + 45 * np.log(0.4)) / 95, abs=1e-6)
    assert rows.log_score[(sm.METHOD, "zeros_left_out")] == pytest.approx((50 * np.log(0.5 / 0.9) + 45 * np.log(0.4 / 0.9)) / 95, abs=1e-6)
    # MAE: the average gap over the three places, in share points
    assert rows.mae_share_points[(sm.METHOD, "floor_0.0001")] == pytest.approx(100 * (0.0 + 0.05 + 0.05) / 3, abs=1e-3)


def test_county_scores_pool_the_blocks():
    a = ("AA", np.array([50.0, 50.0]), np.array([80.0, 20.0]))
    b = ("BB", np.array([10.0, 90.0]), np.array([10.0, 90.0]))
    rows = pd.DataFrame(sm.score_year([a, b], [np.array([0.8, 0.2]), np.array([0.1, 0.9])])).set_index(["method", "scoring"])
    assert rows.releases[(sm.METHOD, "floor_0.0001")] == 200
    by_hand = (80 * np.log(0.8) + 20 * np.log(0.2) + 10 * np.log(0.1) + 90 * np.log(0.9)) / 200
    assert rows.log_score[(sm.METHOD, "floor_0.0001")] == pytest.approx(by_hand, abs=1e-6)
    assert rows.mae_share_points[(sm.METHOD, "floor_0.0001")] == pytest.approx(0.0, abs=1e-9)  # the model was exactly right


# --------------------------------------------------------------------------- the winner rule

def test_the_rule_needs_both_averages_and_six_years():
    assert sm.passes_winner_rule(table([0.002] * 8), "state")
    assert sm.passes_winner_rule(table([0.002] * 6 + [-0.001, -0.001]), "state")
    assert not sm.passes_winner_rule(table([0.002] * 5 + [-0.001] * 3), "state")       # only five years
    assert not sm.passes_winner_rule(table([0.0006] * 7 + [-0.02]), "state")           # seven years, but the averages lose


def test_a_gap_under_the_tie_is_not_a_win_and_exactly_the_tie_is():
    assert not sm.passes_winner_rule(table([0.0004] * 8), "state")
    assert sm.passes_winner_rule(table([0.0005] * 8), "state")
    assert not sm.passes_winner_rule(table([0.002] * 7), "state")  # a missing year cannot count as a win


def test_the_model_must_pass_under_every_scoring():
    good, bad = table([0.002] * 8), table([0.0001] * 8)
    scores = pd.concat([good.assign(scoring="floor_0.0001"), good.assign(scoring="floor_0.5"), bad.assign(scoring="zeros_left_out"),
                        *[table([0.002] * 8, "county").assign(scoring=s) for s in sm.SCORINGS]])
    assert sm.winner(scores) == {"state": "naive", "county": sm.METHOD}


def test_summary_averages_two_ways_and_counts_wins():
    bt = table([0.002, 0.002, -0.001, 0.0004, 0.002, 0.002, 0.002, 0.002]).assign(mae_share_points=0.2)
    bt.loc[bt.method == sm.METHOD, "mae_share_points"] = [0.1, 0.1, 0.3, 0.2, 0.1, 0.1, 0.1, 0.1]
    summary = sm.summarize(bt).set_index(["method", "weighting"])
    assert summary.years_beating_naive_log[(sm.METHOD, "equal")] == 6   # -0.001 and 0.0004 are not wins
    assert summary.years_beating_naive_mae[(sm.METHOD, "equal")] == 6   # 0.3 is worse, 0.2 is a tie
    mine = bt[bt.method == sm.METHOD]
    assert summary.log_score[(sm.METHOD, "equal")] == pytest.approx(mine.log_score.mean(), abs=1e-6)
    assert summary.log_score[(sm.METHOD, "release")] == pytest.approx((mine.log_score * mine.releases).sum() / mine.releases.sum(), abs=1e-6)
    assert summary.years_beating_naive_log[("naive", "equal")] == 0


# --------------------------------------------------------------------------- recovery on made-up data

@slow
def test_the_state_model_recovers_known_settings(monkeypatch):
    """Data made with rho = 0.8 and kappa = 1,500: the fit has to land near both."""
    monkeypatch.setattr(sm, "SAMPLER", {"chains": 2, "draws": 500, "tune": 700, "target_accept": 0.9, "seed": 3})
    rng = np.random.default_rng(11)
    places, years, true_rho, true_kappa = 15, 14, 0.8, 1_500
    alpha = rng.normal(0, 0.3, places)
    alpha -= alpha.mean()
    counts = [rng.multinomial(60_000, rng.dirichlet(np.ones(places) * 2)).astype(float)]
    for _ in range(years):
        expected = sm.softmax(alpha + true_rho * sm.log_shares(counts[-1]))
        counts.append(rng.multinomial(int(rng.integers(20_000, 120_000)), rng.dirichlet(true_kappa * expected)).astype(float))
    model = sm.state_model(np.stack([sm.log_shares(c) for c in counts[:-1]]), np.stack(counts[1:]).astype(int))
    draws, health = sm.sample(model)
    assert health["divergences"] == 0
    assert draws["rho"].mean() == pytest.approx(true_rho, abs=0.06)
    assert draws["kappa"].mean() == pytest.approx(true_kappa, rel=0.3)
    assert np.corrcoef(draws["alpha"].mean(axis=0), alpha)[0, 1] > 0.9  # the tilts come back in the right order
