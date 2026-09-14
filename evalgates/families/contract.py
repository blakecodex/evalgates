"""the contract family: checks that the service keeps its api contract.

six aspects, each its own check id in the suite so a failure names itself:

  healthz        the probe answers and names the model
  scored_shape   a known-good policy returns the full scored shape
  no_score_band  well-formed but out-of-domain requests are refused with
                 named reasons, http 200 - the designed fallback
  malformed_422  broken requests are rejected before the model runs
  batch          mixed batch: counts add up, order preserved
  latency_p95    n sequential scores; p95 under the suite's ceiling

the no-score band is the one that catches real incidents: a service that
starts guessing outside its domain fails no schema check and no unit test -
only a check that posts an out-of-domain request and demands a refusal.
"""
import time

from evalgates.runner import CheckResult
from evalgates.schema import Check

GOOD = {"exposure": 0.5, "driv_age": 45, "veh_age": 5, "veh_power": 6,
        "bonus_malus": 60, "density": 500, "area": "C"}

# shape-valid, domain-invalid - one probe per fence, each names the field
# the refusal must mention
OUT_OF_DOMAIN = [
    ("exposure", dict(GOOD, exposure=1.5)),
    ("driv_age", dict(GOOD, driv_age=17)),
    ("veh_age", dict(GOOD, veh_age=80)),
    ("veh_power", dict(GOOD, veh_power=20)),
    ("bonus_malus", dict(GOOD, bonus_malus=300)),
    ("density", dict(GOOD, density=50000)),
    ("area", dict(GOOD, area="G")),
]

MALFORMED = [
    ("wrong type", dict(GOOD, exposure="banana")),
    ("missing field", {k: v for k, v in GOOD.items() if k != "driv_age"}),
    ("unknown field", dict(GOOD, turbo=True)),
    ("zero exposure", dict(GOOD, exposure=0)),
]

SCORED_FIELDS = {"no_score", "claim_frequency", "claim_probability",
                 "risk_tier", "model_version"}
TIERS = {"low", "moderate", "high", "very_high"}


def run(check: Check, client) -> CheckResult:
    aspect = check.params.get("aspect")
    fn = {
        "healthz": _healthz,
        "scored_shape": _scored_shape,
        "no_score_band": _no_score_band,
        "malformed_422": _malformed,
        "batch": _batch,
        "latency_p95": _latency,
    }.get(aspect)
    if fn is None:
        return CheckResult(check.id, "contract", "error",
                           message=f"unknown contract aspect {aspect!r}")
    return fn(check, client)


def _result(check, ok, measured, message=""):
    return CheckResult(check.id, "contract", "pass" if ok else "fail",
                       measured=measured, message=message)


def _healthz(check, client):
    r = client.get("/healthz")
    body = r.json() if r.status_code == 200 else {}
    ok = r.status_code == 200 and body.get("status") == "ok" \
        and bool(body.get("model_version"))
    return _result(check, ok, {"status_code": r.status_code,
                               "model_version": body.get("model_version", "")},
                   "" if ok else f"healthz returned {r.status_code}: {r.text[:200]}")


def _scored_shape(check, client):
    r = client.post("/score", json=GOOD)
    if r.status_code != 200:
        return _result(check, False, {"status_code": r.status_code},
                       f"expected 200, got {r.status_code}")
    b = r.json()
    problems = []
    if set(b) != SCORED_FIELDS:
        problems.append(f"fields {sorted(b)} != {sorted(SCORED_FIELDS)}")
    if b.get("no_score") is not False:
        problems.append("no_score should be false for an in-domain policy")
    if not (isinstance(b.get("claim_frequency"), float) and b["claim_frequency"] > 0):
        problems.append("claim_frequency must be a positive float")
    if not (isinstance(b.get("claim_probability"), float) and 0 < b["claim_probability"] < 1):
        problems.append("claim_probability must be in (0, 1)")
    if b.get("risk_tier") not in TIERS:
        problems.append(f"risk_tier {b.get('risk_tier')!r} not in {sorted(TIERS)}")
    return _result(check, not problems, {"body_fields": sorted(b)},
                   "; ".join(problems))


def _no_score_band(check, client):
    failures = []
    for field, probe in OUT_OF_DOMAIN:
        r = client.post("/score", json=probe)
        if r.status_code != 200:
            failures.append(f"{field}: got {r.status_code}, want 200")
            continue
        b = r.json()
        if b.get("no_score") is not True:
            failures.append(f"{field}: scored an out-of-domain request")
        elif not any(field in reason for reason in b.get("reasons", [])):
            failures.append(f"{field}: refusal does not name the field "
                            f"(reasons: {b.get('reasons')})")
    return _result(check, not failures,
                   {"probes": len(OUT_OF_DOMAIN),
                    "refused_correctly": len(OUT_OF_DOMAIN) - len(failures)},
                   "; ".join(failures))


def _malformed(check, client):
    failures = []
    for label, probe in MALFORMED:
        r = client.post("/score", json=probe)
        if r.status_code != 422:
            failures.append(f"{label}: got {r.status_code}, want 422")
    max_batch = int(check.params.get("max_batch", 500))
    r = client.post("/score/batch", json={"policies": [GOOD] * (max_batch + 1)})
    if r.status_code != 422:
        failures.append(f"oversize batch: got {r.status_code}, want 422")
    return _result(check, not failures,
                   {"probes": len(MALFORMED) + 1,
                    "rejected_correctly": len(MALFORMED) + 1 - len(failures)},
                   "; ".join(failures))


def _batch(check, client):
    policies = [GOOD, dict(GOOD, exposure=1.5), dict(GOOD, bonus_malus=90)]
    r = client.post("/score/batch", json={"policies": policies})
    if r.status_code != 200:
        return _result(check, False, {"status_code": r.status_code},
                       f"expected 200, got {r.status_code}")
    b = r.json()
    problems = []
    if b.get("count") != 3 or len(b.get("results", [])) != 3:
        problems.append(f"sent 3 policies, response says count="
                        f"{b.get('count')} with {len(b.get('results', []))} results")
    elif b.get("scored") != 2 or b.get("no_score") != 1:
        problems.append(f"expected 2 scored + 1 no_score, got "
                        f"{b['scored']} scored + {b['no_score']} no_score")
    elif b["results"][1].get("no_score") is not True:
        problems.append("order not preserved: the out-of-domain policy moved")
    return _result(check, not problems,
                   {k: b.get(k) for k in ("count", "scored", "no_score")},
                   "; ".join(problems))


def _latency(check, client):
    n = int(check.params.get("n", 200))
    ceiling = float(check.params.get("p95_ms", 50))
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        client.post("/score", json=GOOD)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    p95 = times[int(0.95 * n) - 1]
    ok = p95 <= ceiling
    return _result(check, ok,
                   {"n": n, "p50_ms": round(times[n // 2], 2),
                    "p95_ms": round(p95, 2), "ceiling_ms": ceiling},
                   "" if ok else f"p95 {p95:.1f}ms over the {ceiling}ms ceiling")
