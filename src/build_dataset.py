"""Reshape MPI release data to one row per fiscal year x geography, keyed by county FIPS.

Rows:
  national        all releases that fiscal year
  state           state total
  county          a county MPI lists that year (>= 50 releases); suppressed county-years are not rows.
                  The District of Columbia is one county-equivalent that MPI's county sheet leaves out;
                  it gets a county row from its state total in the years it reached 50.
  other_counties  state total minus listed counties: the real, unlisted group of smaller counties.
                  Never split further (plan guardrail: no backing out counties under 50). When the
                  group is a single county, the row is marked publishable = False.

Census join: July 1, 2024 county estimates (Vintage 2024) as one reference year for every row:
total population and school-age population (ages 5-17).

Inputs : data/raw/mpi/mpi-data-hub_uacsbystate-county-fy2014-fy2025.xlsx
         data/raw/census/cc-est2024-agesex-all.csv
Outputs: data/processed/releases_by_fy_geo.csv
         data/processed/reconciliation.csv      (one row per state x fiscal year)
         data/processed/county_fips_unmatched.csv
Usage  : python src/build_dataset.py
"""
# ===================================================================================================
# HOW TO READ THIS FILE
# Business purpose: the release dataset. It turns MPI's spreadsheet of children released to sponsors
# into one tidy table: one row per fiscal year and place (nation, state, listed county, "other
# counties"), with the Census population of each place attached. Every later step reads this table.
#
# Guardrail built in here: counties appear only in years ORR published them (50+ releases). The rest
# of a state is one "other counties" row and is never split or estimated. If that row covers exactly
# one county (Delaware in four years), it is that county's own unpublished count, so it is marked
# publishable = False and the publishing code (exchange/, the app) leaves it out.
#
# Layout: settings and lookup tables at the top; then the readers (norm and county_key clean county
# names, load_census and load_mpi read the two source files); then reshape(), which matches counties to
# FIPS codes, builds the rows and checks that the totals add up; then main(), which writes three CSV files.
#
# Python ideas: openpyxl (reading Excel), regular expressions for cleaning names, defaultdict,
# dict comprehensions, csv.DictWriter, reconciliation checks that prove the totals add up.
# ===================================================================================================
import csv
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
MPI = ROOT / "data/raw/mpi/mpi-data-hub_uacsbystate-county-fy2014-fy2025.xlsx"
CENSUS = ROOT / "data/raw/census/cc-est2024-agesex-all.csv"
OUT = ROOT / "data/processed"
FYS = list(range(2014, 2026))
CENSUS_YEAR_CODE = "6"  # July 1, 2024 in Vintage 2024 files
THRESHOLD = 50  # ORR publishes a county only in years with 50 or more releases
# A state that is one county-equivalent: its state total is its county's count, but MPI's Counties sheet
# has no row for it. {state name: (county name, postal code)}
SINGLE_COUNTY_STATES = {"District of Columbia": ("District of Columbia", "DC")}
# The Census file lists Connecticut's nine planning regions; MPI and ORR use its eight historical counties.
COUNTIES_IN_STATE = {"CT": 8}

USPS = {  # state name -> two-letter postal code
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA",
    "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    "Puerto Rico": "PR", "Virgin Islands": "VI",  # MPI lists both; national totals include them
}
# The output table's columns, in order
COLUMNS = ["fiscal_year", "geo_level", "state", "state_name", "county_fips", "county_name", "county_key",
           "releases", "listed_counties", "pop_total_2024", "pop_5_17_2024", "unlisted_counties", "publishable"]


# MPI and the Census spell county names differently (accents, "St." vs "Saint", "County" suffix).
# Cleaning both sides the same way lets them match. re.sub(pattern, replacement, text) is a regular-
# expression find-and-replace.
def norm(name):
    """Comparable county name: no accents, no punctuation, 'saint' for 'st.', no 'county'/'parish'."""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"\bst\.?\s", "saint ", n)
    n = re.sub(r"[^a-z0-9 ]", "", n)
    n = re.sub(r"\s+(county|parish|borough|census area|municipality)$", "", n.strip())
    return re.sub(r"\s+", " ", n)


def county_key(name, st):
    """Exchange-contract key: lower case, without 'county'/'parish' (see exchange/EXCHANGE.md)."""
    n = re.sub(r"\s+(county|parish|borough|census area|municipality)$", "", name.strip().lower())
    return f"{n}|{st}"


# Read the Census county file: total and school-age (5-17) population per county and per state.
# defaultdict(lambda: [0, 0]) creates a [total, school-age] pair the first time a state appears, so
# the code can add to it without checking whether it exists yet.
def load_census():
    counties, states = {}, defaultdict(lambda: [0, 0])
    for r in csv.DictReader(open(CENSUS, encoding="latin-1")):
        if r["YEAR"] != CENSUS_YEAR_CODE or r["STNAME"] not in USPS:
            continue
        st = USPS[r["STNAME"]]
        total, school = int(r["POPESTIMATE"]), int(r["AGE513_TOT"]) + int(r["AGE1417_TOT"])
        counties[(st, norm(r["CTYNAME"]))] = (r["STATE"] + r["COUNTY"], r["CTYNAME"], total, school)
        states[st][0] += total
        states[st][1] += school
    return counties, states


def num(v):  # unpublished cells become None (missing), never 0
    """MPI cells: an integer, or blank / '-' where the county-year is not published."""
    return v if isinstance(v, (int, float)) else None


# Read the MPI spreadsheet. data_only=True returns the values Excel displays (not formulas);
# iter_rows(values_only=True) gives each row as a tuple. The data starts at row 9 on the States sheet
# and row 8 on the Counties sheet. {f: ... for i, f in enumerate(FYS)} is a dict comprehension that
# maps each fiscal year to its column.
def load_mpi():
    wb = openpyxl.load_workbook(MPI, data_only=True)
    states = {}
    for r in wb["States"].iter_rows(min_row=9, values_only=True):
        if r[0] in USPS or r[0] == "United States":
            states[r[0]] = {f: num(r[1 + i]) for i, f in enumerate(FYS)}
    counties = []
    for r in wb["Counties"].iter_rows(min_row=8, values_only=True):
        if r[0] and r[1]:
            counties.append((r[0].rsplit(",", 1)[0].strip(), r[1].strip(),
                             {f: num(r[2 + i]) for i, f in enumerate(FYS)}))
    return states, counties


# The District of Columbia had 50 or more releases in most years, yet it is missing from MPI's county
# list because it is reported as a state. Without a county row it would look like a county that never
# reached the threshold. The rule is the same as for every county: a row only in years with 50 or more.
def add_single_county_states(mpi_states, mpi_counties):
    """Add a county entry, built from the state total, for each single-county state the source leaves out."""
    for st_name, (county, st) in SINGLE_COUNTY_STATES.items():
        if st_name in mpi_states and not any(s == st for _, s, _ in mpi_counties):
            mpi_counties.append((county, st, {fy: (v if v is not None and v >= THRESHOLD else None)
                                              for fy, v in mpi_states[st_name].items()}))


# The reshaping step: match MPI counties to Census FIPS codes, build one row per fiscal year and place,
# and check that the numbers add up. It reads and writes no files, so tests can run it on made-up counties.
def reshape(us, mpi_states, mpi_counties, census, census_states):
    # Match each MPI county to its Census FIPS code by cleaned name. Names that don't match are written
    # out for review (for example Connecticut, whose newer Census geography uses planning regions).
    fips, unmatched = {}, []
    for name, st, _ in mpi_counties:
        hit = census.get((st, norm(name)))
        if hit:
            fips[(name, st)] = hit
        else:
            unmatched.append((st, name))

    # How many counties each state has, to know how many sit inside "other counties" in a given year.
    # Counter counts how often each state code appears among the Census county keys.
    n_counties = Counter(st for st, _ in census)
    n_counties.update({st: n - n_counties[st] for st, n in COUNTIES_IN_STATE.items() if st in n_counties})

    rows, recon = [], []
    for fy in FYS:
        rows.append(dict(fiscal_year=fy, geo_level="national", releases=us[fy] or 0, publishable=True,
                         pop_total_2024=sum(v[0] for v in census_states.values()),
                         pop_5_17_2024=sum(v[1] for v in census_states.values())))
        state_sum = 0
        for st_name, st in USPS.items():
            # A blank state cell counts as 0 releases, as in MPI's own "FY 2014 - 2025 Total" column (Alaska's
            # total of 48 adds its blank years as 0). 15 state-years are blank, mostly small states and the
            # territories. `x or 0` gives 0 when x is None.
            total = mpi_states[st_name][fy] or 0
            state_sum += total
            spop = census_states[st] if st in census_states else ["", ""]  # PR and VI are not in the county file
            rows.append(dict(fiscal_year=fy, geo_level="state", state=st, state_name=st_name, releases=total,
                             pop_total_2024=spop[0], pop_5_17_2024=spop[1], publishable=True))
            listed = [(n, s, v[fy]) for n, s, v in mpi_counties if s == st and v[fy]]
            listed_pop = [0, 0]
            for n, s, val in listed:
                f, cname, tot, school = fips.get((n, s), ("", n, "", ""))
                if tot != "":
                    listed_pop[0] += tot
                    listed_pop[1] += school
                rows.append(dict(fiscal_year=fy, geo_level="county", state=st, state_name=st_name, county_fips=f,
                                 county_name=f"{n}, {st}", county_key=county_key(n, st), releases=val,
                                 pop_total_2024=tot, pop_5_17_2024=school, publishable=True))
            # "Other counties" = state total minus the listed counties: a real, published remainder. It is never
            # split further; estimating counties under 50 releases would undo ORR's privacy threshold.
            other = total - sum(v for _, _, v in listed)
            # The other counties' population is also found by subtraction (state minus listed counties), so it
            # needs every listed county's population. If one has no Census match (Connecticut), it stays blank
            # rather than being guessed. all(...) is True only when every item in the list is True.
            all_matched = all((n, s) in fips for n, s, _ in listed)
            # How many counties the remainder covers. If it is exactly one, the remainder is that county's own
            # count, which the source did not publish: keep it so totals add up, but mark it not publishable.
            unlisted = max(n_counties[st] - len(listed), 0) if st in n_counties else ""
            rows.append(dict(fiscal_year=fy, geo_level="other_counties", state=st, state_name=st_name,
                             county_name=f"Other counties, {st}", releases=other, listed_counties=len(listed),
                             unlisted_counties=unlisted, publishable=unlisted != 1,
                             pop_total_2024=spop[0] - listed_pop[0] if all_matched and spop[0] != "" else "",
                             pop_5_17_2024=spop[1] - listed_pop[1] if all_matched and spop[1] != "" else ""))
            # Reconciliation: in every state-year the listed counties must not add up to more than the state
            # total, and the states must add up to the national total. Any failure is printed at the end.
            recon.append(dict(fiscal_year=fy, state=st, state_total=total,
                              listed_county_sum=sum(v for _, _, v in listed), other_counties=other,
                              listed_counties=len(listed), ok=other >= 0))
        recon.append(dict(fiscal_year=fy, state="US", state_total=us[fy], listed_county_sum=state_sum,
                          other_counties=(us[fy] or 0) - state_sum, listed_counties="", ok=(us[fy] or 0) == state_sum))
    return rows, recon, unmatched, fips


# Read both sources, reshape them, and write three CSV files.
def main():
    census, census_states = load_census()
    mpi_states, mpi_counties = load_mpi()
    us = mpi_states.pop("United States")
    in_source = len(mpi_counties)
    add_single_county_states(mpi_states, mpi_counties)
    rows, recon, unmatched, fips = reshape(us, mpi_states, mpi_counties, census, census_states)
    OUT.mkdir(parents=True, exist_ok=True)

    with open(OUT / "releases_by_fy_geo.csv", "w", newline="", encoding="utf-8") as f:
        # DictWriter writes one dict per row; r.get(c, "") leaves a blank where a row has no value
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})
    with open(OUT / "reconciliation.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(recon[0]))
        w.writeheader()
        w.writerows(recon)
    with open(OUT / "county_fips_unmatched.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["state", "mpi_county_name"])
        w.writerows(sorted(unmatched))

    bad = [r for r in recon if not r["ok"]]
    print(f"rows: {len(rows)}  (county rows: {sum(r['geo_level'] == 'county' for r in rows)})")
    print(f"counties: {len(mpi_counties)} ({in_source} in MPI's list, {len(mpi_counties) - in_source} added from "
          f"a state total), matched to FIPS: {len(fips)}, unmatched: {len(unmatched)}")
    held = [r for r in rows if r["publishable"] is False]
    print(f"other-counties rows that are one county (not publishable): {len(held)}",
          sorted({(r['state'], r['fiscal_year']) for r in held}))
    print(f"reconciliation: {len(recon)} checks, {len(bad)} failed")
    for r in bad[:10]:
        print("  FAILED:", r)


if __name__ == "__main__":
    main()
