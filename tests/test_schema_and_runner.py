# the suite loader must refuse malformed suites loudly, and the runner must
# turn a dead service into errors, not skips.
import pytest

from evalgates.runner import ServiceClient, run_suite
from evalgates.schema import SuiteError, load_suite

GOOD_SUITE = """
suite: t
version: 1
checks:
  - id: a
    family: contract
    params: {aspect: healthz}
"""


def _write(tmp_path, text):
    p = tmp_path / "s.yaml"
    p.write_text(text)
    return p


def test_good_suite_loads(tmp_path):
    s = load_suite(_write(tmp_path, GOOD_SUITE))
    assert s.name == "t" and len(s.checks) == 1
    assert s.checks[0].family == "contract"


def test_typo_in_top_level_key_is_fatal(tmp_path):
    # `cheks:` must not silently load a suite with zero checks
    with pytest.raises(SuiteError, match="cheks"):
        load_suite(_write(tmp_path, "suite: t\nversion: 1\ncheks: []\n"))


def test_missing_checks_is_fatal(tmp_path):
    with pytest.raises(SuiteError, match="missing required"):
        load_suite(_write(tmp_path, "suite: t\nversion: 1\n"))


def test_unknown_top_level_key_is_fatal(tmp_path):
    with pytest.raises(SuiteError, match="unknown top-level"):
        load_suite(_write(tmp_path, GOOD_SUITE + "extra: 1\n"))


def test_empty_checks_is_fatal(tmp_path):
    with pytest.raises(SuiteError, match="non-empty"):
        load_suite(_write(tmp_path, "suite: t\nversion: 1\nchecks: []\n"))


def test_duplicate_check_id_is_fatal(tmp_path):
    text = GOOD_SUITE + "  - id: a\n    family: contract\n"
    with pytest.raises(SuiteError, match="duplicate"):
        load_suite(_write(tmp_path, text))


def test_unknown_family_is_fatal(tmp_path):
    text = GOOD_SUITE.replace("family: contract", "family: vibes")
    with pytest.raises(SuiteError, match="unknown family"):
        load_suite(_write(tmp_path, text))


def test_dead_service_is_error_per_check_not_skip(tmp_path):
    suite = load_suite(_write(tmp_path, GOOD_SUITE))
    # nothing listens on this port; connection refused
    client = ServiceClient(base_url="http://127.0.0.1:9")
    run = run_suite(suite, client)
    assert run.counts == {"pass": 0, "fail": 0, "error": 1}
    assert not run.ok
    assert "unreachable" in run.results[0].message
