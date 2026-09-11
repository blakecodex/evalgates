# evalgates

A release gate for model-backed services: versioned check suites, a
fail-closed gate with a regression baseline, TestRail-shaped results,
an HTML run report, and CI as the merge blocker.

The system under test here is deliberately not an LLM. It is a
claim-frequency model (Poisson GLM, fitted from scratch on 677k public
French motor policies) served over HTTP - the same failure class as any
model service, including LLM systems: well-formed answers that are
quietly wrong. A deterministic SUT means every check, threshold, and
seeded defect in this repo runs keyless and proves out end to end in CI.
The harness pattern is the part built to transfer; the SUT is the part
built to be verifiable.

## run it

    pip install -r requirements.txt
    python -m pytest tests/ -q                                  # 83 tests
    python -m evalgates.gate --suite suites/release_v1.yaml \
        --baseline baseline.json --report out/report.html       # 12 checks, exit 0
    uvicorn sut.app:app --port 8080                             # the service

## the four check families

| family | what it catches |
|---|---|
| contract | broken shapes, a dropped out-of-domain refusal, batch errors, latency over ceiling |
| monotonic | a risk factor pointing the wrong way - every response well-formed, every price wrong |
| calibration | predicted levels drifting from observed while ranking metrics stay green |
| drift | today's scored population no longer matching the approved one (PSI, frozen bins) |

Thresholds live in yaml under `suites/`; changing one is a reviewable
diff, not a code change.

## proven able to fail

Every family ships with a seeded-defect test: flip a coefficient sign
and the monotonic family fails; bias the intercept and calibration fails
while ranking metrics would still pass; feed a shifted cohort and PSI
reads 3.59 against a 0.20 fence; drop the out-of-domain refusal and the
contract family fails. A harness that has never been seen to fail proves
nothing.

## the gate

Exit 0 ship, 1 threshold failure, 2 regression against the saved
baseline, 3 error - and an error blocks exactly like a failure. A red
run can never be saved as the baseline. Run history is SQL (`RUNS_DB`
env is the Postgres seam); results export in TestRail's bulk-results
shape.

## ops

CI runs tests, then the gate, as the merge blocker, and uploads the run
report even when red. `docker compose run gate` points the same suites
at a running container; the k8s manifest wires readiness to `/healthz`,
which loads the model artifact - a broken artifact never becomes ready.

## limits

Frequency only, no severity model. One latency ceiling, no load testing.
No auth - a test target, not a production service.
