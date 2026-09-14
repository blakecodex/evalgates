# unit tests on the scorer alone - no service, no http. every domain fence
# edge, both tier boundaries around every cut, and the probability algebra.
import hashlib
import json
import math
from pathlib import Path

import pytest

from sut import model
from sut.features import AREAS, DOMAIN

# a policy comfortably inside every fence; each test perturbs one field
BASE = {"exposure": 0.5, "driv_age": 45, "veh_age": 5, "veh_power": 6,
        "bonus_malus": 60, "density": 500, "area": "C"}


def with_(field, value):
    p = dict(BASE)
    p[field] = value
    return p


def test_scored_response_shape():
    out = model.score(BASE)
    assert out["no_score"] is False
    assert set(out) == {"no_score", "claim_frequency", "claim_probability",
                        "risk_tier", "model_version"}
    assert out["claim_frequency"] > 0
    assert 0 < out["claim_probability"] < 1
    assert out["risk_tier"] in {"low", "moderate", "high", "very_high"}


# every fence, both sides of both edges. exposure's lower bound is open
# (0.002 itself is out); all other bounds are closed.
EDGES = [
    ("exposure", 0.002, False), ("exposure", 0.0021, True),
    ("exposure", 1.0, True), ("exposure", 1.01, False),
    ("driv_age", 17, False), ("driv_age", 18, True),
    ("driv_age", 100, True), ("driv_age", 101, False),
    ("veh_age", -1, False), ("veh_age", 0, True),
    ("veh_age", 60, True), ("veh_age", 61, False),
    ("veh_power", 3, False), ("veh_power", 4, True),
    ("veh_power", 15, True), ("veh_power", 16, False),
    ("bonus_malus", 49, False), ("bonus_malus", 50, True),
    ("bonus_malus", 230, True), ("bonus_malus", 231, False),
    ("density", 0, False), ("density", 1, True),
    ("density", 30000, True), ("density", 30001, False),
]


@pytest.mark.parametrize("field,value,inside", EDGES)
def test_every_fence_edge(field, value, inside):
    out = model.score(with_(field, value))
    if inside:
        assert out["no_score"] is False, f"{field}={value} should score"
    else:
        assert out["no_score"] is True, f"{field}={value} should refuse"
        assert any(field in r for r in out["reasons"])


def test_all_areas_score_and_unknown_area_refuses():
    for a in AREAS:
        assert model.score(with_("area", a))["no_score"] is False
    # the latent bug this fence exists for: an unfenced unknown area would
    # one-hot to all zeros and silently score as area A
    out = model.score(with_("area", "G"))
    assert out["no_score"] is True
    assert any("area" in r for r in out["reasons"])


def test_multiple_violations_all_named():
    p = dict(BASE, driv_age=17, bonus_malus=300)
    out = model.score(p)
    assert out["no_score"] is True
    assert len(out["reasons"]) == 2
    joined = " ".join(out["reasons"])
    assert "driv_age" in joined and "bonus_malus" in joined


def test_reasons_name_value_and_fence():
    out = model.score(with_("driv_age", 17))
    assert out["reasons"] == [f"driv_age 17 outside [18, 100]"]


@pytest.mark.parametrize("rate,tier", [
    (0.0699, "low"), (0.07, "moderate"),
    (0.1099, "moderate"), (0.11, "high"),
    (0.1699, "high"), (0.17, "very_high"),
    (0.90, "very_high"),
])
def test_tier_boundaries(rate, tier):
    assert model.risk_tier(rate) == tier


def test_probability_is_one_minus_exp_of_rate_times_exposure():
    out = model.score(BASE)
    expected = 1.0 - math.exp(-out["claim_frequency"] * BASE["exposure"])
    assert abs(out["claim_probability"] - expected) < 1e-6


def test_shorter_exposure_lowers_probability_not_frequency():
    full = model.score(with_("exposure", 1.0))
    half = model.score(with_("exposure", 0.5))
    # frequency is annualized - same profile, same rate
    assert full["claim_frequency"] == half["claim_frequency"]
    # probability is over the policy's own exposure - less time, less chance
    assert half["claim_probability"] < full["claim_probability"]


def test_deterministic():
    assert model.score(BASE) == model.score(BASE)


def test_model_version_is_hash_of_coefficients_file():
    raw = (Path(model.__file__).parent / "coefficients.json").read_bytes()
    assert model.score(BASE)["model_version"] == hashlib.sha256(raw).hexdigest()[:12]


def test_domain_dict_drives_the_fences():
    # DOMAIN is the single source for numeric fences; a field probed at
    # its recorded bounds must score, one past must refuse
    for field, (lo, hi) in DOMAIN.items():
        if field == "exposure":
            continue                    # open lower bound, covered in EDGES
        assert model.score(with_(field, lo))["no_score"] is False
        assert model.score(with_(field, hi))["no_score"] is False
        assert model.score(with_(field, hi + 1))["no_score"] is True
