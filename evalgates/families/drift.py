"""the drift family: checks that today's scored population still matches
the population the release was approved on.

population stability index over the score distribution:

    psi = sum over bins of (a - b) * ln(a / b)

a = share of the reference slice in the bin, b = share of the current slice.
every term is non-negative (both factors carry the same sign), zero only
when the shares match bin for bin. bin edges are quantiles of the REFERENCE
scores and stay frozen - both cohorts are binned against the same edges,
which is what makes the number comparable day over day.

psi needs no labels, so it can run on every batch of scored traffic, months
before enough claims accumulate to show the same shift in loss data. fences
are the standard ones: 0.10 watch, 0.20 investigate. the check fails at the
suite's fail fence; crossing the watch fence passes with the value named in
the message so the trend is visible in run history before it blocks anyone.
"""
import math

from evalgates.families.calibration import score_slice
from evalgates.runner import CheckResult
from evalgates.schema import Check


def psi(ref_scores, cur_scores, n_bins=10, epsilon=1e-4):
    """returns (psi, per-bin table). edges are reference quantiles; shares
    are floored at epsilon so the log never sees an empty bin."""
    ref = sorted(ref_scores)
    edges = [ref[int(i * len(ref) / n_bins)] for i in range(1, n_bins)]
    # collapse duplicate edges (heavy ties would make degenerate bins)
    edges = sorted(set(edges))

    def shares(scores):
        counts = [0] * (len(edges) + 1)
        for s in scores:
            i = 0
            while i < len(edges) and s >= edges[i]:
                i += 1
            counts[i] += 1
        return [max(c / len(scores), epsilon) for c in counts]

    a, b = shares(ref_scores), shares(cur_scores)
    table = []
    total = 0.0
    for i, (ai, bi) in enumerate(zip(a, b)):
        term = (ai - bi) * math.log(ai / bi)
        total += term
        table.append({"bin": i + 1,
                      "reference_share": round(ai, 4),
                      "current_share": round(bi, 4),
                      "term": round(term, 5)})
    return total, table


def run(check: Check, client) -> CheckResult:
    ref_path = check.params["reference"]
    cur_path = check.params["current"]
    n_bins = int(check.params.get("bins", 10))
    warn_at = float(check.params.get("warn_at", 0.10))
    fail_at = float(check.params.get("fail_at", 0.20))

    ref_rows, ref_refused = score_slice(client, ref_path)
    cur_rows, cur_refused = score_slice(client, cur_path)
    if ref_refused or cur_refused:
        return CheckResult(check.id, "drift", "fail",
                           measured={"reference_refused": ref_refused,
                                     "current_refused": cur_refused},
                           message=f"in-domain rows refused during scoring: "
                                   f"{ref_refused} in the reference cohort, "
                                   f"{cur_refused} in the current cohort")

    value, table = psi([r["rate"] for r in ref_rows],
                       [r["rate"] for r in cur_rows], n_bins=n_bins)

    ok = value < fail_at
    message = ""
    if value >= fail_at:
        message = f"psi {value:.4f} at or over the fail fence {fail_at}"
    elif value >= warn_at:
        message = f"psi {value:.4f} over the watch fence {warn_at} - not blocking, watch it"
    return CheckResult(
        check.id, "drift", "pass" if ok else "fail",
        measured={"psi": round(value, 4), "bins": table,
                  "fences": {"warn_at": warn_at, "fail_at": fail_at}},
        message=message)
