# evalgates — specification

Written before the build. Everything below is a commitment the test suite
must verify. If the repo and this page disagree, change the repo to match
this page.

## What this repository is

Two things, deliberately in one repo:

1. **A system under test (SUT):** a claim-frequency scoring service — a
   Poisson GLM fitted on public French motor third-party liability data
   (freMTPL2freq, 678k policies), served over HTTP.
2. **A release gate for it:** a harness that runs versioned suites of checks
   against the service and exits 0 only when the release is safe to ship.

The point of building both is that model-backed services fail differently
from ordinary services. A code bug returns a wrong shape; a model bug returns
a well-formed number that is quietly wrong. The gate has to catch both.

## What the gate promises

`python -m evalgates.gate --suite suites/release_v1.yaml` exits 0 when all
three hold, and nonzero otherwise:

1. **Thresholds.** Every check in the suite passes its own pass rule.
2. **No regression.** No check got worse than the saved baseline by more than
   its allowed slack. A pass that is worse than last release still fails.
3. **No errors.** A check that crashes or cannot reach the service counts as
   a failure, not a skip. If the gate cannot prove the release is good, it
   says no. That is what fail-closed means here.

CI runs the gate on every push and blocks the merge on the exit code.

## The four check families

**1. Contract and fallback** — checks that the service keeps its API
contract. Response shapes and status codes; batch size limits; the health
endpoint.
The split that matters: a *malformed* request (wrong types, missing fields,
values outside the schema) gets **422** and never reaches the model; a
*well-formed* request outside the model's fitted domain (a 17-year-old
driver, an exposure of 1.5 years) gets **200 with `no_score: true`** and
named reasons. The service refuses to guess outside the data it was fitted on, and
the refusal is a normal response the caller can handle — not an error.

**2. Monotonicity** — checks that risk moves the expected direction.
Metamorphic checks:
take a base policy, worsen one factor, score both, and require the frequency
to rise. Bonus-malus up ⇒ frequency up. Density up ⇒ frequency up. Vehicle
power flat past the model's cap at 12. Driver age is deliberately **not** in
this family: on this dataset, with bonus-malus in the model, the young-driver
coefficient comes out negative, because bonus-malus already carries the young
drivers' surcharge. The exclusion is documented with the fitted numbers in
`docs/monotonicity-notes.md`. An assertion the data does not support is a
false alarm generator, and false alarms are how gates get turned off.

**3. Calibration** — checks that predicted frequencies match observed ones.
On the evaluation slice: rank policies by predicted frequency, cut into ten
exposure-weighted deciles, compare predicted to observed frequency in each.
Pass rules: worst decile gap ≤ 0.05, portfolio-level gap ≤ 0.01. Ranking
metrics only check ordering; calibration checks predicted levels, and
pricing uses the levels.

**4. Drift** — checks that today's scored population still matches the
population the model was approved on. PSI of the score distribution, current
slice against bins frozen from the reference slice. Fences: warn at 0.10,
fail at 0.20 (the standard credit-risk fences). PSI needs no labels, so it
can run every day — months before enough claims accumulate to show the same
problem in loss data.

## Proof the harness itself works

Every family ships with a **seeded-defect test**: a fixture breaks the
service on purpose — flips a coefficient, biases the intercept, shifts the
scored population, drops the fallback — and the test asserts the family
*fails*. A harness that has never been seen to fail is not evidence of
anything. This is the core SDET requirement: show that each check detects
the failure it exists to catch.

## Stack, mapped to practice

| In the JD | In this repo |
|---|---|
| Python | everything; stdlib + numpy + fastapi + pyyaml |
| Pytest | `tests/` — unit, service, family, seeded-defect |
| BDD | `tests/features/gate.feature` + pytest-bdd bindings |
| TestRail | `evalgates/export.py` writes TestRail-shaped result JSON |
| SQL / PostgreSQL | run history in SQLite; `RUNS_DB` env var is the seam a Postgres DSN plugs into |
| Docker / K8s | Dockerfile, docker-compose, `k8s/scorer.yaml` |
| CI/CD | GitHub Actions: tests, then the gate, as the merge blocker |
| Linux / AWS | container-first layout; deploy notes in the README |

## Data rules

Public data only (freMTPL2freq via CASdatasets). Committed artifacts are
small samples with provenance files stating source, extraction method, seed,
and row counts. The full extract is reproducible with `data/fetch_fremtpl.py`.
No client data, no company names, no proprietary anything.

## Out of scope, stated up front

- Severity (claim cost) modeling — frequency only.
- AuthN/AuthZ on the service — it is a test target, not a production system.
- Load testing — one p95 latency check, nothing more.
- Model improvement — the GLM is deliberately simple; the harness is the
  deliverable.
