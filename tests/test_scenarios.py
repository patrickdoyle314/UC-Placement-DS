"""Tests for the scenario engine's own calculations (src/scenarios.py), on made-up inputs with known answers.

tests/test_acceptance.py checks the files the engine writes. These tests check the steps inside it.
"""
# ===================================================================================================
# HOW TO READ THIS FILE
# Business purpose: the scenario tables rest on a few calculations. Each test feeds one of them a small
# made-up input whose right answer is known in advance. The most important is the recovery test: data is
# generated with a known kappa, and the fit has to find that kappa again. If the fit were wrong, the
# 80% ranges would be too narrow or too wide and nobody would see why.
#
# Python ideas: NumPy's seeded random Generator (the same "random" numbers every run), pytest.approx with
# a relative tolerance, building small pandas tables by hand, monkeypatch to change a setting for one test.
# ===================================================================================================
import numpy as np
import pandas as pd
import pytest

from src import scenarios as sc


def comparison(a_cover, a_score, b_cover, b_score) -> pd.DataFrame:
    """A comparison table like the engine's, where only the pooled coverage and score matter."""
    rows = []
    for version, cover, score in (("a", a_cover, a_score), ("b", b_cover, b_score)):
        for group, places in (("all", 408), ("large", 80), ("small", 328)):
            rows.append({"version": version, "size_group": group, "places": places,
                         "inside_80": round(cover * places), "coverage": cover,
                         "mean_width_share_points": score / 2, "mean_interval_score": score})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- step 1: scenarios

def test_scenarios_are_the_lowest_middle_and_highest_year():
    national = pd.Series({2014: 5, 2015: 30, 2016: 50, 2017: 40, 2018: 35, 2019: 70, 2020: 10, 2021: 110,
                          2022: 120, 2023: 110 + 1, 2024: 100, 2025: 25})
    low, median, high = sc.scenario_volumes(national)
    assert (low["national_releases"], low["source_fiscal_year"]) == (10, 2020)
    assert (median["national_releases"], median["source_fiscal_year"]) == (50, 2016)  # the 6th of 11 values
    assert (high["national_releases"], high["source_fiscal_year"]) == (120, 2022)     # FY2014's 5 is not used


# --------------------------------------------------------------------------- step 3: the error model

def made_up_years(rng, kappa, years=60, places=30):
    """Counts that follow the engine's own model with a known kappa: each year's shares are a Dirichlet
    draw around last year's actual shares, and the children are counted out with a multinomial."""
    counts = [rng.multinomial(50_000, rng.dirichlet(np.ones(places) * 3)).astype(float)]
    for _ in range(years):
        last = counts[-1]
        shares = rng.dirichlet(kappa * last / last.sum()) if kappa else last / last.sum()
        counts.append(rng.multinomial(int(rng.integers(20_000, 120_000)), shares).astype(float))
    return counts


def ratios_of(counts) -> pd.DataFrame:
    rows = []
    for last, now in zip(counts[:-1], counts[1:]):
        n, ratio, keep = sc.miss_ratios(last, now)
        rows += [(n, r) for r, k in zip(ratio, keep) if k]
    return pd.DataFrame(rows, columns=["n", "ratio"])


@pytest.mark.parametrize("true_kappa", [400, 2_000, 10_000])
def test_fit_recovers_a_known_kappa(true_kappa):
    rng = np.random.default_rng(7)
    fitted = sc.fit_kappa(ratios_of(made_up_years(rng, true_kappa)))
    assert fitted == pytest.approx(true_kappa, rel=0.15)


def test_shares_that_never_move_give_ratios_near_one_and_the_largest_kappa():
    rng = np.random.default_rng(7)
    ratios = ratios_of(made_up_years(rng, kappa=None))  # only counting noise, no movement in the shares
    assert ratios.ratio.mean() == pytest.approx(1.0, abs=0.1)
    assert sc.fit_kappa(ratios) > 100_000


def test_large_states_are_the_ten_biggest_in_the_training_years():
    states = [f"S{i:02d}" for i in range(15)]
    h = sc.History(national=None, counties={}, state_names={}, county_info=None,
                   states=pd.DataFrame([[i + 1.0 for i in range(15)]] * 3, index=[2014, 2015, 2016], columns=states))
    h.states.loc[2016, "S00"] = 10_000  # a jump in 2016 must not count for a forecast of 2016
    assert set(sc.large_states(h, 2016)) == set(states[5:])
    assert "S00" in sc.large_states(h, 2017)


# --------------------------------------------------------------------------- step 4: the simulation

def test_simulated_years_add_up_and_center_on_last_years_shares():
    rng = np.random.default_rng(1)
    last = np.array([500.0, 300.0, 150.0, 50.0, 0.0])
    draws = sc.simulate_states(rng, last, kappas=2_000, total=20_000)
    assert draws.shape == (sc.DRAWS, 5)
    assert (draws.sum(axis=1) == 20_000).all()  # every simulated year hands out exactly the national total
    assert draws.mean(axis=0)[:4] == pytest.approx(20_000 * last[:4] / 1_000, rel=0.01)
    assert draws[:, 4].max() <= 2  # a place with nothing last year gets (almost) nothing, not a crash


def test_one_kappa_gives_the_dirichlet_spread_and_a_smaller_kappa_a_wider_one():
    expected = np.array([0.4, 0.3, 0.2, 0.1])
    same = sc.draw_shares(np.random.default_rng(2), expected, 1_000)
    theory = np.sqrt(expected * (1 - expected) / (1_000 + 1))  # the Dirichlet's standard deviation
    assert same.std(axis=0) == pytest.approx(theory, rel=0.05)
    assert same.sum(axis=1) == pytest.approx(1.0)
    mixed = sc.draw_shares(np.random.default_rng(2), expected, np.array([250, 1_000, 1_000, 1_000]))
    assert mixed[:, 0].std() > 1.5 * same[:, 0].std()  # the place with the smaller kappa wanders further
    assert mixed.mean(axis=0) == pytest.approx(expected, abs=0.005)  # and the averages stay where they were


def test_counties_split_each_state_draw_exactly():
    rng = np.random.default_rng(3)
    state_draws = rng.integers(900, 1_100, size=sc.DRAWS)
    draws = sc.simulate_counties(rng, state_draws, np.array([600.0, 300.0, 100.0]), kappa=400)
    assert (draws.sum(axis=1) == state_draws).all()
    only_other = sc.simulate_counties(rng, state_draws, np.array([1_000.0]), kappa=400)
    assert only_other.shape == (sc.DRAWS, 1) and (only_other[:, 0] == state_draws).all()


# --------------------------------------------------------------------------- step 5: the 50-release rule

def test_a_county_under_fifty_is_folded_into_other_counties():
    rng = np.random.default_rng(4)
    draws = np.column_stack([rng.poisson(200, sc.DRAWS), rng.poisson(30, sc.DRAWS), rng.poisson(100, sc.DRAWS)])
    shown, other = sc.fold_small(draws, expected=np.array([200.0, 30.0]))
    assert list(shown) == [0]  # the county expecting about 30 gets no row
    assert (other == draws[:, 1] + draws[:, 2]).all()  # its draws moved into "other counties", draw by draw
    assert (draws[:, shown].sum(axis=1) + other == draws.sum(axis=1)).all()  # nothing lost


def test_the_fifty_rule_does_not_depend_on_the_random_draws():
    # Two counties with the same count last year expect the same number, so they are shown or folded together.
    expected = sc.expected_county_releases(total=16_864, state_share=0.01, last_counts=np.array([72.0, 72.0, 100.0]))
    assert expected[0] == pytest.approx(expected[1]) and expected[0] == pytest.approx(16_864 * 0.01 * 72 / 244, rel=1e-4)
    draws = np.column_stack([np.full(sc.DRAWS, 49), np.full(sc.DRAWS, 51), np.full(sc.DRAWS, 68)])
    shown, _ = sc.fold_small(draws, expected=np.array([50.06, 50.06]))  # both shown, though one's draws average 49
    assert list(shown) == [0, 1]
    shown, _ = sc.fold_small(draws, expected=np.array([49.9, 49.9]))
    assert list(shown) == []


def test_rows_are_whole_children_in_order_and_school_age_never_exceeds_releases():
    rng = np.random.default_rng(5)
    for draws in (rng.poisson(700, sc.DRAWS), rng.poisson(0.02, sc.DRAWS)):  # a normal place and a lopsided one
        releases, school_age = sc.measure_rows({"state": "XX"}, draws, 0.967)
        for row in (releases, school_age):
            assert isinstance(row["expected"], int)
            assert 0 <= row["lower_80"] <= row["expected"] <= row["upper_80"]
        assert school_age["expected"] <= releases["expected"]


# --------------------------------------------------------------------------- step 8: choosing the version

def test_the_lower_interval_score_wins_among_versions_that_pass():
    assert sc.choose_version(comparison(0.83, 1.13, 0.84, 1.04))[0] == "b"
    assert sc.choose_version(comparison(0.83, 1.04, 0.84, 1.13))[0] == "a"
    assert sc.choose_version(comparison(0.83, 1.10, 0.84, 1.10))[0] == "a"  # a tie goes to the simpler version


def test_a_version_outside_the_coverage_band_cannot_win():
    assert sc.choose_version(comparison(0.83, 1.13, 0.93, 0.90))[0] == "a"  # (b) scores lower but is too wide
    assert sc.choose_version(comparison(0.60, 0.90, 0.75, 1.50))[0] == "b"
    version, reason = sc.choose_version(comparison(0.60, 0.90, 0.95, 1.50))
    assert version == "a" and "Neither" in reason


def test_the_version_can_be_set_by_hand(monkeypatch):
    monkeypatch.setattr(sc, "FORCE_VERSION", "a")
    version, reason = sc.choose_version(comparison(0.83, 1.13, 0.84, 1.04))
    assert version == "a" and "by hand" in reason
