# the family checks, proven in both directions:
#   healthy service  -> every check passes (the release suite runs green)
#   broken service   -> the responsible family FAILS
#
# the second half is the seeded-defect suite. a check that has never been
# seen to fail proves nothing; each test below plants one specific defect
# and requires the one family built to catch it to actually catch it.
import gzip

import pytest

from evalgates.families import calibration, contract, drift, monotonic
from evalgates.runner import ServiceClient
from evalgates.schema import Check
from sut import model
from sut.features import FEATURE_NAMES


@pytest.fixture
def client():
    return ServiceClient()          # in-process against the real app


@pytest.fixture
def patched_model():
    """snapshot the loaded model cache; tests mutate it, this restores it.
    the beta list is copied element-wise - a shallow dict copy would share
    the list, and a test that flips a coefficient in place would leak the
    flip into every later test (found the hard way; kept as a warning)."""
    model._model()
    saved = {"beta": list(model._CACHE["beta"]),
             "version": model._CACHE["version"]}
    yield model._CACHE
    model._CACHE.clear()
    model._CACHE.update(saved)


def check(family, id, **params):
    return Check(id=id, family=family, params=params)


# --- healthy paths ---------------------------------------------------------

def test_contract_aspects_all_pass_on_healthy_service(client):
    for aspect in ("healthz", "scored_shape", "no_score_band",
                   "malformed_422", "batch"):
        r = contract.run(check("contract", aspect, aspect=aspect), client)
        assert r.status == "pass", f"{aspect}: {r.message}"


def test_monotonic_directions_pass_on_healthy_service(client):
    r = monotonic.run(check("monotonic", "bm", aspect="pairs",
                            factor="bonus_malus",
                            steps=[50, 90, 150, 230]), client)
    assert r.status == "pass", r.message
    r = monotonic.run(check("monotonic", "cap", aspect="flat_past_cap",
                            factor="veh_power", values=[12, 13, 14, 15]), client)
    assert r.status == "pass", r.message


def test_calibration_passes_on_healthy_service(client):
    r = calibration.run(
        check("calibration", "cal",
              slice="data/sample/fremtpl_evaluation.csv.gz",
              max_decile_gap=0.05, max_portfolio_gap=0.01), client)
    assert r.status == "pass", r.message
    assert r.measured["worst_decile_gap"] <= 0.05
    assert len(r.measured["deciles"]) == 10


def test_drift_near_zero_between_matched_slices(client):
    r = drift.run(
        check("drift", "psi",
              reference="data/sample/fremtpl_reference.csv.gz",
              current="data/sample/fremtpl_evaluation.csv.gz",
              warn_at=0.10, fail_at=0.20), client)
    assert r.status == "pass", r.message
    # same book, disjoint samples: psi should be sampling noise
    assert r.measured["psi"] < 0.05


# --- seeded defects --------------------------------------------------------

def test_dropped_fallback_is_caught_by_contract_family(client, monkeypatch):
    """defect: the service stops refusing out-of-domain requests and starts
    extrapolating - the exact quiet failure the no-score band exists for."""
    monkeypatch.setattr(model, "fence_reasons", lambda p: [])
    r = contract.run(check("contract", "band", aspect="no_score_band"), client)
    assert r.status == "fail"
    assert r.measured["refused_correctly"] == 0


def test_flipped_coefficient_is_caught_by_monotonic_family(client, patched_model):
    """defect: the bonus-malus coefficient ships with the wrong sign - every
    response is well-formed, every schema check passes, and every surcharged
    driver gets a discount."""
    i = FEATURE_NAMES.index("bonus_malus")
    patched_model["beta"][i] = -patched_model["beta"][i]
    r = monotonic.run(check("monotonic", "bm", aspect="pairs",
                            factor="bonus_malus",
                            steps=[50, 90, 150, 230]), client)
    assert r.status == "fail"
    assert "did not rise" in r.message


def test_biased_intercept_is_caught_by_calibration_family(client, patched_model):
    """defect: a refit shifts the intercept up 0.35 (about +42% frequency
    everywhere). ranking is untouched - auc-style checks would pass - but
    every predicted level is wrong, and the decile table shows it."""
    patched_model["beta"] = list(patched_model["beta"])
    patched_model["beta"][0] += 0.35
    r = calibration.run(
        check("calibration", "cal",
              slice="data/sample/fremtpl_evaluation.csv.gz",
              max_decile_gap=0.05, max_portfolio_gap=0.01), client)
    assert r.status == "fail"
    assert r.measured["portfolio_gap"] > 0.01


def test_removed_power_cap_is_caught_by_monotonic_family(client, monkeypatch):
    """defect: someone 'fixes' the feature builder by removing the power
    cap - power 13 now scores above 12, and the flat-past-cap check that
    pins the cap must notice."""
    from sut.features import AREAS

    def uncapped(p):
        import math
        age, vage = p["driv_age"], p["veh_age"]
        x = [1.0, (p["bonus_malus"] - 50) / 10.0, math.log(p["density"]),
             float(p["veh_power"] - 4),              # cap removed
             1.0 if 18 <= age <= 25 else 0.0,
             1.0 if 26 <= age <= 40 else 0.0,
             1.0 if age >= 61 else 0.0,
             1.0 if vage <= 1 else 0.0,
             1.0 if vage >= 10 else 0.0]
        return x + [1.0 if p["area"] == a else 0.0 for a in AREAS[1:]]

    monkeypatch.setattr(model, "features", uncapped)
    r = monotonic.run(check("monotonic", "cap", aspect="flat_past_cap",
                            factor="veh_power", values=[12, 13, 14, 15]), client)
    assert r.status == "fail"
    assert "differs" in r.message


def test_population_shift_is_caught_by_drift_family(client, tmp_path):
    """defect: the current cohort loses its low-risk tail (a channel mix
    change - only surcharged drivers arrive). no code changed, no model
    changed; only the population moved. psi is the check that sees it."""
    src = "data/sample/fremtpl_evaluation.csv.gz"
    shifted = tmp_path / "shifted.csv.gz"
    with gzip.open(src, "rt") as f:
        header = f.readline()
        rows = [ln for ln in f]
    kept = [ln for ln in rows if int(ln.split(",")[4]) >= 72]  # bonus_malus col
    assert len(kept) > 500, "need a real cohort for the test to mean anything"
    with gzip.open(shifted, "wt") as f:
        f.write(header)
        f.writelines(kept)

    r = drift.run(
        check("drift", "psi",
              reference="data/sample/fremtpl_reference.csv.gz",
              current=str(shifted), warn_at=0.10, fail_at=0.20), client)
    assert r.status == "fail"
    assert r.measured["psi"] >= 0.20
    assert "fail fence" in r.message


def test_refused_in_domain_rows_fail_calibration_not_skip(client, monkeypatch):
    """defect: the service's fences tighten (deploy config drift) and start
    refusing rows the model was fitted on. the slice is in-domain by
    construction, so any refusal must fail the check, never shrink the
    sample quietly."""
    real = model.fence_reasons
    monkeypatch.setattr(
        model, "fence_reasons",
        lambda p: real(p) + (["bonus_malus 60 outside [50, 55]"]
                             if p["bonus_malus"] > 55 else []))
    r = calibration.run(
        check("calibration", "cal",
              slice="data/sample/fremtpl_evaluation.csv.gz",
              max_decile_gap=0.05, max_portfolio_gap=0.01), client)
    assert r.status == "fail"
    assert "refused" in r.message
