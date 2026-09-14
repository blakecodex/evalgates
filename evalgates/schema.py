"""the suite file contract. suites are data under version control: changing
a threshold is a reviewable one-line diff with an author and a reason, not a
code change buried in a test file.

a suite file looks like:

    suite: release_v1
    version: 1
    description: everything that must hold before a release ships
    checks:
      - id: calibration_deciles
        family: calibration
        params:
          slice: data/sample/fremtpl_evaluation.csv.gz
          max_decile_gap: 0.05

rules enforced here, before anything runs:
  - required top-level keys present, no unknown ones (a typo like `cheks:`
    must fail loudly, not silently run zero checks)
  - at least one check; every check has a unique id and a known family
  - params is a dict (possibly empty)
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

KNOWN_FAMILIES = ("contract", "monotonic", "calibration", "drift")
TOP_KEYS = {"suite", "version", "description", "checks"}
CHECK_KEYS = {"id", "family", "params"}


class SuiteError(ValueError):
    """a malformed suite file - always a blocking error, never a skip."""


@dataclass
class Check:
    id: str
    family: str
    params: dict = field(default_factory=dict)


@dataclass
class Suite:
    name: str
    version: int
    description: str
    checks: list[Check]
    path: str


def load_suite(path: str | Path) -> Suite:
    path = Path(path)
    doc = yaml.safe_load(path.read_text())
    if not isinstance(doc, dict):
        raise SuiteError(f"{path}: not a mapping")

    unknown = set(doc) - TOP_KEYS
    if unknown:
        raise SuiteError(f"{path}: unknown top-level keys {sorted(unknown)}")
    missing = {"suite", "version", "checks"} - set(doc)
    if missing:
        raise SuiteError(f"{path}: missing required keys {sorted(missing)}")

    raw_checks = doc["checks"]
    if not isinstance(raw_checks, list) or not raw_checks:
        raise SuiteError(f"{path}: checks must be a non-empty list")

    checks, seen = [], set()
    for i, c in enumerate(raw_checks):
        if not isinstance(c, dict):
            raise SuiteError(f"{path}: check #{i} is not a mapping")
        unknown = set(c) - CHECK_KEYS
        if unknown:
            raise SuiteError(f"{path}: check #{i} unknown keys {sorted(unknown)}")
        if "id" not in c or "family" not in c:
            raise SuiteError(f"{path}: check #{i} needs id and family")
        if c["id"] in seen:
            raise SuiteError(f"{path}: duplicate check id {c['id']!r}")
        seen.add(c["id"])
        if c["family"] not in KNOWN_FAMILIES:
            raise SuiteError(f"{path}: check {c['id']!r} names unknown family "
                             f"{c['family']!r}; known: {KNOWN_FAMILIES}")
        params = c.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise SuiteError(f"{path}: check {c['id']!r} params must be a mapping")
        checks.append(Check(id=c["id"], family=c["family"], params=params))

    return Suite(name=doc["suite"], version=int(doc["version"]),
                 description=doc.get("description", ""), checks=checks,
                 path=str(path))
