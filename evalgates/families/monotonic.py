"""the monotonicity family: worse factor in, higher frequency out.

metamorphic checks: no ground truth needed, only a relation between outputs.
take one base policy, walk one factor up through the suite's list of values,
score every variant through the service, and require the frequencies to move
the declared direction. which factors get asserted, and why age does not, is
docs/monotonicity-notes.md - the suite only encodes directions the fitted
model was shown to support.

two aspects:
  pairs           frequencies strictly increase along params.steps
  flat_past_cap   frequencies identical for every value in params.values
                  (pins the veh_power cap at 12)
"""
from evalgates.runner import CheckResult
from evalgates.schema import Check

BASE = {"exposure": 0.5, "driv_age": 45, "veh_age": 5, "veh_power": 6,
        "bonus_malus": 60, "density": 500, "area": "C"}


def run(check: Check, client) -> CheckResult:
    aspect = check.params.get("aspect", "pairs")
    if aspect == "pairs":
        return _pairs(check, client)
    if aspect == "flat_past_cap":
        return _flat(check, client)
    return CheckResult(check.id, "monotonic", "error",
                       message=f"unknown monotonic aspect {aspect!r}")


def _frequencies(check, client, factor, values):
    """score the base policy at each value of the factor; every variant must
    score - a refusal inside the declared range is itself a failure."""
    base = dict(BASE, **check.params.get("base", {}))
    freqs, problems = [], []
    for v in values:
        r = client.post("/score", json=dict(base, **{factor: v}))
        if r.status_code != 200:
            problems.append(f"{factor}={v}: http {r.status_code}")
            continue
        b = r.json()
        if b.get("no_score"):
            problems.append(f"{factor}={v}: refused ({b.get('reasons')})")
            continue
        freqs.append((v, b["claim_frequency"]))
    return freqs, problems


def _pairs(check, client):
    factor = check.params["factor"]
    steps = check.params["steps"]
    freqs, problems = _frequencies(check, client, factor, steps)
    violations = [
        f"{factor} {a_v}->{b_v}: frequency {a_f} -> {b_f} did not rise"
        for (a_v, a_f), (b_v, b_f) in zip(freqs, freqs[1:])
        if b_f <= a_f
    ]
    ok = not problems and not violations
    return CheckResult(
        check.id, "monotonic", "pass" if ok else "fail",
        measured={"factor": factor,
                  "frequencies": {str(v): f for v, f in freqs}},
        message="; ".join(problems + violations))


def _flat(check, client):
    factor = check.params["factor"]
    values = check.params["values"]
    freqs, problems = _frequencies(check, client, factor, values)
    baseline = freqs[0][1] if freqs else None
    violations = [
        f"{factor}={v}: frequency {f} differs from {baseline} at the cap"
        for v, f in freqs[1:] if f != baseline
    ]
    ok = not problems and not violations
    return CheckResult(
        check.id, "monotonic", "pass" if ok else "fail",
        measured={"factor": factor,
                  "frequencies": {str(v): f for v, f in freqs}},
        message="; ".join(problems + violations))
