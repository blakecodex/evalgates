"""the scorer: a policy in, a fenced decision out.

two possible answers, both normal:

  scored    - {"no_score": false, "claim_frequency": ..., "claim_probability": ...,
               "risk_tier": ..., "model_version": ...}
  no-score  - {"no_score": true, "reasons": [...], "model_version": ...}

the no-score path is a designed outcome for well-formed requests outside the
model's fitted domain. the service does not extrapolate: a 17-year-old driver
or a 1.5-year exposure gets a refusal with named reasons, and the caller
routes it to manual review. malformed requests never reach this module - the
api layer rejects those with 422 before any model code runs.

pure stdlib on purpose: scoring is a dot product over 14 floats, and a numpy
dependency at serve time buys nothing but a bigger container.
"""
import hashlib
import json
import math
from pathlib import Path

from sut.features import AREAS, DOMAIN, FEATURE_NAMES, features

# risk tiers on the annualized frequency. cut points chosen on the reference
# slice so the book splits roughly 60 / 25 / 10 / 5 (measured: 59.8, 25.1,
# 10.1, 5.0 percent). tiers read the rate per policy-year, not the
# probability, so a six-month policy and a full-year policy with the same
# driving profile land in the same tier.
TIERS = (
    (0.07, "low"),
    (0.11, "moderate"),
    (0.17, "high"),
    (math.inf, "very_high"),
)

_CACHE = {}


def _model():
    """load coefficients.json once; version = first 12 hex of its sha256,
    so every response names the exact artifact that produced it. built as a
    local dict and installed with one update() so a concurrent first call
    never sees a half-filled cache (uvicorn workers are processes, but
    threaded servers exist and the guard costs nothing)."""
    if not _CACHE:
        path = Path(__file__).with_name("coefficients.json")
        raw = path.read_bytes()
        doc = json.loads(raw)
        loaded = {"beta": [doc["coefficients"][n] for n in FEATURE_NAMES],
                  "version": hashlib.sha256(raw).hexdigest()[:12]}
        _CACHE.update(loaded)
    return _CACHE


def fence_reasons(p: dict) -> list[str]:
    """every domain violation in the request, each with the offending value
    and the fence it broke - the caller should not have to guess."""
    reasons = []
    lo, hi = DOMAIN["exposure"]
    if not (lo < p["exposure"] <= hi):
        reasons.append(f"exposure {p['exposure']} outside ({lo}, {hi}]")
    for field in ("driv_age", "veh_age", "veh_power", "bonus_malus", "density"):
        lo, hi = DOMAIN[field]
        if not (lo <= p[field] <= hi):
            reasons.append(f"{field} {p[field]} outside [{lo}, {hi}]")
    if p["area"] not in AREAS:
        # without this fence an unknown area would one-hot to all zeros and
        # silently score as area A - checked by a unit test
        reasons.append(f"area {p['area']!r} not one of {'-'.join(AREAS)}")
    return reasons


def risk_tier(rate: float) -> str:
    for cut, name in TIERS:
        if rate < cut:
            return name
    return TIERS[-1][1]          # unreachable; the last cut is +inf


def score(p: dict) -> dict:
    """score one policy dict (already shape-validated by the api layer)."""
    m = _model()
    reasons = fence_reasons(p)
    if reasons:
        return {"no_score": True, "reasons": reasons,
                "model_version": m["version"]}
    eta = sum(b * x for b, x in zip(m["beta"], features(p)))
    rate = math.exp(eta)                       # claims per policy-year
    # poisson count with mean rate*exposure, so the probability of at least
    # one claim over the policy's own exposure is 1 - exp(-rate*exposure)
    prob = 1.0 - math.exp(-rate * p["exposure"])
    return {
        "no_score": False,
        "claim_frequency": round(rate, 6),
        "claim_probability": round(prob, 6),
        "risk_tier": risk_tier(rate),
        "model_version": m["version"],
    }


def score_many(policies: list[dict]) -> list[dict]:
    return [score(p) for p in policies]
