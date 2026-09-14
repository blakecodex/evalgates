"""fit the claim-frequency model: a poisson glm, by hand, in numpy.

the model:  claim_nb ~ poisson(mu),  ln(mu) = x'beta + ln(exposure)

exposure enters as an offset with coefficient fixed at 1, so beta describes
a rate per policy-year. the log link keeps mu positive and makes every
coefficient a percent effect: exp(beta) is the multiplier on frequency.

the fit is iteratively reweighted least squares (irls) - newton's method on
the poisson log-likelihood, where each newton step turns out to be a weighted
least-squares solve. no library does the statistics here; statsmodels fits
the identical spec once, in verify(), as an independent cross-check.

usage (after `python data/fetch_fremtpl.py` has produced the extract):
    python -m sut.fit --data /tmp/fremtpl/fremtpl_indomain.csv.gz
"""
import argparse
import csv
import gzip
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

from sut.features import DOMAIN, FEATURE_NAMES, features

RIDGE = 1e-8          # conditioning only; small enough to not move the 4th decimal
TOL = 1e-10           # stop when no coefficient moves more than this
MAX_ITER = 50


def load(path: str):
    """csv.gz -> design matrix X, claim counts y, offsets ln(exposure)."""
    rows_x, y, off = [], [], []
    with gzip.open(path, "rt") as f:
        for row in csv.DictReader(f):
            p = {
                "exposure": float(row["exposure"]),
                "driv_age": int(row["driv_age"]),
                "veh_age": int(row["veh_age"]),
                "veh_power": int(row["veh_power"]),
                "bonus_malus": int(row["bonus_malus"]),
                "density": int(row["density"]),
                "area": row["area"],
            }
            rows_x.append(features(p))
            y.append(int(row["claim_nb"]))
            off.append(np.log(p["exposure"]))
    return np.array(rows_x), np.array(y, float), np.array(off)


def deviance(y, mu):
    """poisson deviance: 2 * sum[ y ln(y/mu) - (y - mu) ], with 0 ln 0 = 0."""
    with np.errstate(divide="ignore", invalid="ignore"):
        term = np.where(y > 0, y * np.log(y / mu), 0.0)
    return 2.0 * float(np.sum(term - (y - mu)))


def irls(X, y, off, verbose=True):
    """the fit: four update lines, repeated to convergence:

        eta = X beta + off          current linear predictor
        mu  = exp(eta)              current mean
        z   = eta - off + (y-mu)/mu the working response
        solve (X'WX) beta = X'Wz,   W = diag(mu)

    warm start: every beta 0 except the intercept, set to the log of the
    portfolio rate - so iteration one already predicts the right total.
    """
    n, k = X.shape
    beta = np.zeros(k)
    beta[0] = np.log(y.sum() / np.exp(off).sum())
    log = []
    for it in range(1, MAX_ITER + 1):
        eta = X @ beta + off
        mu = np.exp(eta)
        z = eta - off + (y - mu) / mu
        W = mu                                   # poisson: weight = mean
        XtW = X.T * W
        new = np.linalg.solve(XtW @ X + RIDGE * np.eye(k), XtW @ z)
        step = float(np.max(np.abs(new - beta)))
        beta = new
        dev = deviance(y, np.exp(X @ beta + off))
        log.append({"iter": it, "deviance": round(dev, 4), "max_step": step})
        if verbose:
            print(f"  iter {it:2d}  deviance {dev:14.4f}  max|dbeta| {step:.2e}")
        if step < TOL:
            break
    # standard errors from the information matrix at the optimum:
    # var(beta) ~ (X'WX)^-1, W = diag(mu_hat)
    mu = np.exp(X @ beta + off)
    cov = np.linalg.inv((X.T * mu) @ X)
    se = np.sqrt(np.diag(cov))
    return beta, se, log


def verify(X, y, off, beta_ours) -> float:
    """independent cross-check: statsmodels fits the identical spec.
    returns the largest absolute coefficient difference."""
    import statsmodels.api as sm
    model = sm.GLM(y, X, family=sm.families.Poisson(), offset=off)
    theirs = model.fit().params
    return float(np.max(np.abs(np.asarray(theirs) - beta_ours)))


def decile_calibration(slice_path: str, beta):
    """rank by predicted frequency, cut into ten exposure-weighted groups,
    compare predicted to observed frequency inside each. the level check:
    a model can rank well and still be wrong about levels; pricing uses
    the levels."""
    X, y, off = load(slice_path)
    exposure = np.exp(off)
    pred_rate = np.exp(X @ beta)                 # per policy-year
    # stable sort: predicted rates tie heavily (discrete features), and an
    # unstable tiebreak would make the decile table depend on numpy internals
    order = np.argsort(pred_rate, kind="stable")
    exposure, y, pred_rate = exposure[order], y[order], pred_rate[order]
    cum = np.cumsum(exposure)
    edges = np.searchsorted(cum, np.linspace(0, cum[-1], 11)[1:-1])
    groups = np.split(np.arange(len(y)), edges)
    table = []
    for i, g in enumerate(groups, 1):
        e = exposure[g].sum()
        table.append({
            "decile": i,
            "exposure": round(float(e), 1),
            "predicted": round(float((pred_rate[g] * exposure[g]).sum() / e), 4),
            "observed": round(float(y[g].sum() / e), 4),
        })
    worst = max(abs(r["predicted"] - r["observed"]) for r in table)
    portfolio_pred = float((pred_rate * exposure).sum() / exposure.sum())
    portfolio_obs = float(y.sum() / exposure.sum())
    return {
        "table": table,
        "worst_decile_gap": round(worst, 4),
        "portfolio_gap": round(abs(portfolio_pred - portfolio_obs), 4),
    }


def main() -> int:
    repo = Path(__file__).resolve().parents[1]   # defaults work from any cwd
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="in-domain csv.gz (fit set)")
    ap.add_argument("--eval-slice", default=str(repo / "data/sample/fremtpl_evaluation.csv.gz"))
    ap.add_argument("--out", default=str(repo / "sut/coefficients.json"))
    args = ap.parse_args()

    print("loading", args.data)
    X, y, off = load(args.data)
    print(f"  {X.shape[0]:,} rows, {X.shape[1]} features")

    print("fitting (irls):")
    beta, se, log = irls(X, y, off)

    print("verifying against statsmodels:")
    diff = verify(X, y, off, beta)
    print(f"  max |beta_ours - beta_statsmodels| = {diff:.2e}")
    if diff > 1e-4:
        print("  DISAGREEMENT - not freezing coefficients"); return 1

    print("calibration on the evaluation slice:")
    cal = decile_calibration(args.eval_slice, beta)
    for r in cal["table"]:
        print(f"  decile {r['decile']:2d}  predicted {r['predicted']:.4f}  observed {r['observed']:.4f}")
    print(f"  worst decile gap {cal['worst_decile_gap']}  portfolio gap {cal['portfolio_gap']}")

    out = {
        "model": "poisson glm, log link, offset ln(exposure)",
        "fitted": str(date.today()),
        "fitted_on_rows": int(X.shape[0]),
        "data": "freMTPL2freq, in-domain filter per data/sample/provenance.json",
        "domain": {k: list(v) for k, v in DOMAIN.items()},
        "coefficients": {n: round(float(b), 6) for n, b in zip(FEATURE_NAMES, beta)},
        "standard_errors": {n: round(float(s), 6) for n, s in zip(FEATURE_NAMES, se)},
        "fit_log": log,
        "twin_check": {"cross_check": "statsmodels GLM poisson", "max_abs_diff": diff},
        "calibration_on_evaluation_slice": cal,
    }
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    print("froze", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
