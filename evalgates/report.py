"""a run report a reviewer can read without the terminal: one static html
file, no javascript, no external assets - it attaches to a ticket, opens
from a ci artifact bucket, and prints.

sections: verdict banner, per-check table, the calibration decile table and
drift bins when those families ran, regressions when a baseline was given,
and the last few runs from history for trend context.
"""
import html
from pathlib import Path

from evalgates import history
from evalgates.runner import RunResult

CSS = """
body { font: 14px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
       color: #1a1d21; max-width: 880px; margin: 2rem auto; padding: 0 16px; }
h1 { font-size: 1.3rem; } h2 { font-size: 1.05rem; margin-top: 2rem; }
table { border-collapse: collapse; width: 100%; margin: .6rem 0; }
th, td { text-align: left; padding: .3rem .6rem; border-bottom: 1px solid #e2e5e9; }
th { font-weight: 600; background: #f6f7f9; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.verdict { padding: .7rem 1rem; border-radius: 6px; font-weight: 600; margin: 1rem 0; }
.v0 { background: #e6f4ea; color: #17603a; }
.v1, .v2 { background: #fdecea; color: #8f1f1a; }
.v3 { background: #fef3e2; color: #8a5200; }
.pass { color: #17603a; font-weight: 600; }
.fail { color: #b3261e; font-weight: 600; }
.error { color: #8a5200; font-weight: 600; }
.bar { display: inline-block; height: 9px; background: #7a9cc4; vertical-align: middle; }
.bar.obs { background: #c48a7a; }
.msg { color: #5f6570; font-size: 13px; }
code { background: #f2f3f5; padding: 0 4px; border-radius: 3px; }
"""

VERDICT = {
    0: "exit 0 — all checks passed, no regressions, safe to ship",
    1: "exit 1 — threshold failure: at least one check failed its pass rule",
    2: "exit 2 — regression: thresholds passed, but a tracked metric is worse than baseline",
    3: "exit 3 — error: the gate could not prove the release is good",
}


def _e(x) -> str:
    return html.escape(str(x))


def _results_table(run: RunResult) -> str:
    rows = []
    for r in run.results:
        rows.append(
            f"<tr><td class='{r.status}'>{r.status.upper()}</td>"
            f"<td><code>{_e(r.id)}</code></td><td>{_e(r.family)}</td>"
            f"<td class='num'>{r.elapsed_ms} ms</td>"
            f"<td class='msg'>{_e(r.message) or '—'}</td></tr>")
    return ("<table><tr><th>status</th><th>check</th><th>family</th>"
            "<th class='num'>time</th><th>message</th></tr>"
            + "".join(rows) + "</table>")


def _calibration_section(run: RunResult) -> str:
    for r in run.results:
        if r.family == "calibration" and "deciles" in r.measured:
            scale = 2200        # px per unit frequency, fits the widest decile
            rows = []
            for d in r.measured["deciles"]:
                pw = max(int(d["predicted"] * scale), 2)
                ow = max(int(d["observed"] * scale), 2)
                rows.append(
                    f"<tr><td class='num'>{d['decile']}</td>"
                    f"<td class='num'>{d['exposure']}</td>"
                    f"<td class='num'>{d['predicted']:.4f}</td>"
                    f"<td class='num'>{d['observed']:.4f}</td>"
                    f"<td><span class='bar' style='width:{pw}px'></span><br>"
                    f"<span class='bar obs' style='width:{ow}px'></span></td></tr>")
            m = r.measured
            return (f"<h2>calibration — {_e(r.id)}</h2>"
                    f"<p>worst decile gap <b>{m['worst_decile_gap']}</b> "
                    f"(max {m['thresholds']['max_decile_gap']}), portfolio gap "
                    f"<b>{m['portfolio_gap']}</b> "
                    f"(max {m['thresholds']['max_portfolio_gap']}). "
                    f"blue = predicted, red = observed.</p>"
                    "<table><tr><th class='num'>decile</th><th class='num'>exposure</th>"
                    "<th class='num'>predicted</th><th class='num'>observed</th>"
                    "<th>frequencies</th></tr>" + "".join(rows) + "</table>")
    return ""


def _drift_section(run: RunResult) -> str:
    for r in run.results:
        if r.family == "drift" and "bins" in r.measured:
            rows = []
            for b in r.measured["bins"]:
                rw = max(int(b["reference_share"] * 700), 2)
                cw = max(int(b["current_share"] * 700), 2)
                rows.append(
                    f"<tr><td class='num'>{b['bin']}</td>"
                    f"<td class='num'>{b['reference_share']:.4f}</td>"
                    f"<td class='num'>{b['current_share']:.4f}</td>"
                    f"<td class='num'>{b['term']:.5f}</td>"
                    f"<td><span class='bar' style='width:{rw}px'></span><br>"
                    f"<span class='bar obs' style='width:{cw}px'></span></td></tr>")
            m = r.measured
            return (f"<h2>drift — {_e(r.id)}</h2>"
                    f"<p>psi <b>{m['psi']}</b> (watch {m['fences']['warn_at']}, "
                    f"fail {m['fences']['fail_at']}). "
                    f"blue = reference share, red = current share.</p>"
                    "<table><tr><th class='num'>bin</th><th class='num'>reference</th>"
                    "<th class='num'>current</th><th class='num'>term</th>"
                    "<th>shares</th></tr>" + "".join(rows) + "</table>")
    return ""


def _history_section() -> str:
    runs = history.recent_runs(limit=10)
    if not runs:
        return ""
    rows = []
    for r in runs:
        rows.append(
            f"<tr><td><code>{_e(r['run_id'])}</code></td>"
            f"<td>{_e(r['suite'])}</td><td>{_e(r['model_version'])}</td>"
            f"<td class='num'>{r['passes']}/{r['passes'] + r['fails'] + r['errors']}</td>"
            f"<td class='num'>{'—' if r['gate_exit'] is None else r['gate_exit']}</td>"
            f"<td class='num'>{r['duration_ms']} ms</td></tr>")
    return ("<h2>recent runs</h2>"
            "<table><tr><th>run</th><th>suite</th><th>model</th>"
            "<th class='num'>passed</th><th class='num'>exit</th>"
            "<th class='num'>time</th></tr>" + "".join(rows) + "</table>")


def render(run: RunResult, regs: list[str], exit_code: int) -> str:
    c = run.counts
    regs_html = ""
    if regs:
        items = "".join(f"<li><code>{_e(x)}</code></li>" for x in regs)
        regs_html = f"<h2>regressions vs baseline</h2><ul>{items}</ul>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>evalgates — {_e(run.suite)}</title><style>{CSS}</style></head><body>
<h1>evalgates run report</h1>
<p>suite <code>{_e(run.suite)}</code> v{run.suite_version} ·
model <code>{_e(run.model_version)}</code> · started {_e(run.started_at)} ·
{run.duration_ms} ms · {c['pass']} passed / {c['fail']} failed / {c['error']} errored</p>
<div class="verdict v{exit_code}">{VERDICT.get(exit_code, exit_code)}</div>
{_results_table(run)}
{regs_html}
{_calibration_section(run)}
{_drift_section(run)}
{_history_section()}
</body></html>
"""


def write(run: RunResult, regs: list[str], exit_code: int, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(render(run, regs, exit_code))
