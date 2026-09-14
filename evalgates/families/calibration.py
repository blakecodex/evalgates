"""the calibration family: checks the predicted levels, not just the
ranking. deciles of predicted frequency, exposure-weighted, predicted vs
observed in each.

the same arithmetic exists in sut/fit.py for the freeze-time report; this
module re-implements it against the http contract on purpose. the fit-time
number answers "was the model calibrated when fitted"; this check answers
"is the deployed service calibrated now" - through the same interface a
real caller uses, so a serving bug (stale coefficients, a broken feature
mapping) lands here even though the fit-time report looked fine.

the two implementations also cut deciles differently (fit.py splits at
searchsorted index positions, this module walks cumulative exposure), so
their worst-gap numbers differ in the fourth decimal - 0.0237 at fit time
vs 0.0222 here on the same slice and model. expected, documented, and a
useful property: agreement between two independent implementations is
itself a check on the arithmetic.
"""
import csv
import gzip

from evalgates.runner import CheckResult
from evalgates.schema import Check

BATCH = 500


def _load_slice(path):
    rows = []
    with gzip.open(path, "rt") as f:
        for row in csv.DictReader(f):
            rows.append({
                "policy": {
                    "exposure": float(row["exposure"]),
                    "driv_age": int(row["driv_age"]),
                    "veh_age": int(row["veh_age"]),
                    "veh_power": int(row["veh_power"]),
                    "bonus_malus": int(row["bonus_malus"]),
                    "density": int(row["density"]),
                    "area": row["area"],
                },
                "claims": int(row["claim_nb"]),
            })
    return rows


def score_slice(client, path):
    """batch-score a slice through the service; returns (rows, refusals)."""
    rows = _load_slice(path)
    refused = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        r = client.post("/score/batch",
                        json={"policies": [c["policy"] for c in chunk]})
        r.raise_for_status()
        for c, result in zip(chunk, r.json()["results"]):
            if result["no_score"]:
                refused += 1
                c["rate"] = None
            else:
                c["rate"] = result["claim_frequency"]
    return rows, refused


def run(check: Check, client) -> CheckResult:
    slice_path = check.params["slice"]
    max_gap = float(check.params.get("max_decile_gap", 0.05))
    max_portfolio = float(check.params.get("max_portfolio_gap", 0.01))
    n_bins = int(check.params.get("deciles", 10))

    rows, refused = score_slice(client, slice_path)
    if refused:
        # the slice is in-domain by construction; any refusal means the
        # service's fences moved, so the check fails loudly instead of
        # quietly measuring calibration on a shrunken sample
        return CheckResult(check.id, "calibration", "fail",
                           measured={"refused": refused, "rows": len(rows)},
                           message=f"{refused} in-domain rows refused to score")

    # sort by predicted rate (stable: ties are common with discrete factors),
    # then cut at equal cumulative exposure so each decile carries the same
    # weight of policy-years
    rows.sort(key=lambda c: c["rate"])
    total_exp = sum(c["policy"]["exposure"] for c in rows)
    table, bucket, acc, decile = [], [], 0.0, 1
    per = total_exp / n_bins
    for c in rows:
        bucket.append(c)
        acc += c["policy"]["exposure"]
        if acc >= per * decile and decile < n_bins:
            table.append(_decile_row(decile, bucket))
            bucket, decile = [], decile + 1
    if bucket:
        table.append(_decile_row(decile, bucket))

    worst = max(abs(r["predicted"] - r["observed"]) for r in table)
    pred_total = sum(c["rate"] * c["policy"]["exposure"] for c in rows)
    obs_total = sum(c["claims"] for c in rows)
    portfolio_gap = abs(pred_total - obs_total) / total_exp

    ok = worst <= max_gap and portfolio_gap <= max_portfolio
    msgs = []
    if worst > max_gap:
        msgs.append(f"worst decile gap {worst:.4f} over {max_gap}")
    if portfolio_gap > max_portfolio:
        msgs.append(f"portfolio gap {portfolio_gap:.4f} over {max_portfolio}")
    return CheckResult(
        check.id, "calibration", "pass" if ok else "fail",
        measured={"deciles": table,
                  "worst_decile_gap": round(worst, 4),
                  "portfolio_gap": round(portfolio_gap, 4),
                  "thresholds": {"max_decile_gap": max_gap,
                                 "max_portfolio_gap": max_portfolio}},
        message="; ".join(msgs))


def _decile_row(decile, bucket):
    e = sum(c["policy"]["exposure"] for c in bucket)
    pred = sum(c["rate"] * c["policy"]["exposure"] for c in bucket) / e
    obs = sum(c["claims"] for c in bucket) / e
    return {"decile": decile, "exposure": round(e, 1),
            "predicted": round(pred, 4), "observed": round(obs, 4)}
