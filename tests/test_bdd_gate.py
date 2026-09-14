# gherkin bindings for the gate scenarios. the feature file is the readable
# contract; these steps make it executable. every scenario drives the real
# gate entry point (evalgates.gate.main) end to end - no mocking of the gate
# itself, only planted defects in the model underneath it.
import json
import shutil
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from evalgates import gate
from sut import model

ROOT = Path(__file__).resolve().parents[1]

scenarios("features/gate.feature")


@pytest.fixture(autouse=True)
def _model_guard():
    """snapshot the model cache around EVERY scenario. autouse matters:
    pytest-bdd builds a requested fixture at the first step that names it,
    which can be after a given has already mutated the model - a snapshot
    taken there would save the defect and 'restore' it into later scenarios
    (found the hard way: the biased intercept leaked into the regression
    scenario and turned its exit 2 into an exit 1)."""
    model._model()
    saved = {"beta": list(model._CACHE["beta"]),
             "version": model._CACHE["version"]}
    yield
    model._CACHE.clear()
    model._CACHE.update(saved)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    """per-scenario workspace: scratch history db, exit code, paths."""
    monkeypatch.setenv("RUNS_DB", str(tmp_path / "runs.db"))
    return {"tmp": tmp_path, "exit": None}


# --- given -----------------------------------------------------------------

@given("the scoring service is healthy")
def healthy():
    pass                                  # the real service, unmodified


@given("the model ships with a biased intercept")
def biased_intercept():
    model._model()
    model._CACHE["beta"] = list(model._CACHE["beta"])
    model._CACHE["beta"][0] += 0.35       # +42% frequency across the board


@given("a baseline from a run with tighter calibration")
def tight_baseline(ctx):
    # a previous release measured a worst decile gap of 0.005; slack is
    # 0.005, today's 0.022 exceeds both - a regression, not noise
    baseline = {"suite": "release_v1", "model_version": "previous",
                "metrics": {"calibration_deciles": {"worst_decile_gap": 0.005,
                                                    "portfolio_gap": 0.0002}}}
    p = ctx["tmp"] / "baseline.json"
    p.write_text(json.dumps(baseline))
    ctx["baseline"] = p


@given("a suite that points at a slice file that does not exist")
def broken_suite(ctx):
    text = (ROOT / "suites/release_v1.yaml").read_text()
    text = text.replace("data/sample/fremtpl_evaluation.csv.gz",
                        "data/sample/no_such_file.csv.gz")
    p = ctx["tmp"] / "broken.yaml"
    p.write_text(text)
    ctx["suite"] = p


# --- when ------------------------------------------------------------------

def _run(ctx, extra=()):
    argv = ["--suite", str(ctx.get("suite", ROOT / "suites/release_v1.yaml")),
            *extra]
    ctx["exit"] = gate.main(argv)


@when("the gate runs the release suite")
def run_plain(ctx, capsys):
    _run(ctx)
    ctx["out"] = capsys.readouterr().out


@when("the gate runs the release suite against that baseline")
def run_with_baseline(ctx, capsys):
    _run(ctx, ("--baseline", str(ctx["baseline"])))
    ctx["out"] = capsys.readouterr().out


@when("the gate runs that suite")
def run_that_suite(ctx, capsys):
    _run(ctx)
    ctx["out"] = capsys.readouterr().out


@when("the gate runs the release suite asking to save the baseline")
def run_saving(ctx, capsys):
    ctx["baseline"] = ctx["tmp"] / "new_baseline.json"
    _run(ctx, ("--baseline", str(ctx["baseline"]), "--save-baseline"))
    ctx["out"] = capsys.readouterr().out


# --- then ------------------------------------------------------------------

@then(parsers.parse("the gate exits {code:d}"))
def exits(ctx, code):
    assert ctx["exit"] == code, f"expected exit {code}, got {ctx['exit']}"


@then("every check in the run passes")
def all_pass(ctx):
    assert "FAIL" not in ctx["out"] and "ERR " not in ctx["out"]
    assert "0 failed, 0 errored" in ctx["out"]


@then("the calibration check is the one that failed")
def calibration_failed(ctx):
    failing = [ln for ln in ctx["out"].splitlines() if ln.strip().startswith("FAIL")]
    assert failing and all("calibration" in ln for ln in failing), failing


@then("the regression names the metric that got worse")
def regression_named(ctx):
    assert "REGRESSION" in ctx["out"]
    assert "calibration_deciles.worst_decile_gap" in ctx["out"]


@then("no baseline file is written")
def no_baseline(ctx):
    assert not ctx["baseline"].exists()
