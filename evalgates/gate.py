"""the release gate. runs a suite, applies three rules in order, exits with
a code ci can block on:

    exit 0   every check passed, nothing regressed, nothing errored
    exit 1   a check failed its threshold
    exit 2   every threshold passed, but a tracked metric got worse than
             the baseline by more than its slack
    exit 3   a check errored, or the suite would not load - the gate cannot
             prove the release is good, so it says no. fail closed.

precedence when rules trip together: errors first (exit 3), then threshold
failures (exit 1). exit 2 therefore only ever describes a run whose
thresholds all passed - regressions found alongside failures are still
printed, they just do not set the code.

usage:
    python -m evalgates.gate --suite suites/release_v1.yaml
        [--base-url http://staging:8080]     target a deployment instead of in-process
        [--baseline baseline.json]           compare tracked metrics against this
        [--save-baseline]                    write the baseline after a GREEN run
        [--export out/testrail.json]         testrail-shaped results
        [--report out/report.html]           human-readable run report
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from evalgates import export as export_mod
from evalgates import history
from evalgates.runner import RunResult, ServiceClient, run_suite
from evalgates.schema import SuiteError, load_suite

# the metrics the baseline tracks, and how much worse each may get before
# the gate calls it a regression. every entry is higher-is-worse. the slack
# absorbs sampling noise between runs; a real degradation exceeds it.
# binary families (contract pass/fail, monotonic directions) have no metric
# to ratchet - their regression IS the threshold failure. latency is
# deliberately not tracked: it measures whatever machine ran the gate, so a
# slower ci runner would trip a "regression" with no code change - the
# absolute ceiling in the suite is the latency control.
TRACKED = {
    ("calibration", "worst_decile_gap"): 0.005,
    ("calibration", "portfolio_gap"): 0.002,
    ("drift", "psi"): 0.02,
}


def regressions(run: RunResult, baseline: dict) -> list[str]:
    """every tracked metric that got worse than baseline + slack."""
    found = []
    base_metrics = baseline.get("metrics", {})
    for r in run.results:
        for (family, metric), slack in TRACKED.items():
            if r.family != family or metric not in r.measured:
                continue
            before = base_metrics.get(r.id, {}).get(metric)
            if before is None:
                continue                      # metric is new; nothing to ratchet
            now = float(r.measured[metric])
            if now > float(before) + slack:
                found.append(f"{r.id}.{metric}: {before} -> {now} "
                             f"(slack {slack})")
    return found


def snapshot(run: RunResult) -> dict:
    """the baseline a green run leaves behind for the next run to beat."""
    metrics = {}
    for r in run.results:
        vals = {m: float(r.measured[m])
                for (fam, m) in TRACKED
                if fam == r.family and m in r.measured}
        if vals:
            metrics[r.id] = vals
    return {"suite": run.suite,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model_version": run.model_version,
            "metrics": metrics}


def print_table(run: RunResult, regs: list[str]) -> None:
    print(f"\nsuite {run.suite} v{run.suite_version}  "
          f"model {run.model_version}  ({run.duration_ms} ms)")
    width = max(len(r.id) for r in run.results)
    for r in run.results:
        mark = {"pass": "PASS", "fail": "FAIL", "error": "ERR "}[r.status]
        note = r.message[:90] if r.message else ""
        print(f"  {mark}  {r.id:<{width}}  {note}")
    c = run.counts
    print(f"  {c['pass']} passed, {c['fail']} failed, {c['error']} errored")
    for reg in regs:
        print(f"  REGRESSION  {reg}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="evalgates.gate")
    ap.add_argument("--suite", required=True)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--save-baseline", action="store_true")
    ap.add_argument("--export", default=None)
    ap.add_argument("--report", default=None)
    args = ap.parse_args(argv)

    try:
        suite = load_suite(args.suite)
    except (SuiteError, FileNotFoundError, OSError) as e:
        print(f"gate: cannot load suite: {e}", file=sys.stderr)
        return 3

    run = run_suite(suite, ServiceClient(base_url=args.base_url))

    regs = []
    if args.baseline and Path(args.baseline).exists():
        baseline = json.loads(Path(args.baseline).read_text())
        regs = regressions(run, baseline)

    c = run.counts
    if c["error"]:
        code = 3
    elif c["fail"]:
        code = 1
    elif regs:
        code = 2
    else:
        code = 0

    print_table(run, regs)
    run_id = history.record(run, gate_exit=code)
    print(f"  recorded as {run_id} in {history.db_path()}")

    if args.export:
        export_mod.write(run, args.export)
        print(f"  exported {args.export}")
    if args.report:
        from evalgates import report as report_mod
        report_mod.write(run, regs, code, args.report)
        print(f"  report {args.report}")

    if args.save_baseline:
        if code == 0:
            Path(args.baseline or "baseline.json").write_text(
                json.dumps(snapshot(run), indent=2) + "\n")
            print(f"  baseline saved to {args.baseline or 'baseline.json'}")
        else:
            # never ratchet to a red run - the next run would compare
            # against a broken standard and call it normal
            print("  baseline NOT saved: run was not green", file=sys.stderr)

    print(f"  gate exit {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
