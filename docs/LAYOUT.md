# Layout — decided before the build, held to

```
evalgates/
  sut/                     the system under test
    features.py            the one feature function, shared by fit and scorer
    model.py               scorer: fences, tiers, no-score reasons
    fit.py                 IRLS fit + calibration table; writes coefficients.json
    app.py                 FastAPI service: /healthz /score /score/batch
    coefficients.json      fitted parameters, provenance-stamped, committed
  evalgates/               the harness package (imports nothing from sut/)
    schema.py              versioned suite-file contract
    runner.py              loads a suite, calls the service, collects results
    families/              one module per check family
      contract.py  monotonic.py  calibration.py  drift.py
    gate.py                fail-closed decision + exit codes + baseline ratchet
    history.py             run store (SQLite; RUNS_DB env is the Postgres seam)
    export.py              TestRail-shaped result JSON
    report.py              static HTML run report (no js, no external assets)
  suites/                  versioned yaml suites (contract_v1, monotonic_v1, release_v1)
  data/
    fetch_fremtpl.py       reproduces the full extract from the public source
    sample/
      fremtpl_reference.csv.gz  12k-row reference slice (seeded)
      fremtpl_evaluation.csv.gz 12k-row evaluation slice (seeded, disjoint)
      provenance.json           source, method, seeds, counts, checksums
  tests/                   pytest; features/gate.feature + BDD bindings
  docs/                    SPEC, LAYOUT, data notes, method notes
  MANUAL/                  study manual (gitignored - local by default)
  k8s/scorer.yaml  Dockerfile  docker-compose.yml  Makefile  pytest.ini
  .github/workflows/ci.yml  requirements.txt  requirements-fit.txt
  baseline.json  README.md
```

Two rules the layout enforces:

1. **The harness never reads the SUT's internals.** `runner.py` talks to
   the service the way any client would — over the HTTP contract (in-process
   ASGI for speed locally, `--base-url` for a deployed target). The one
   deliberate import of `sut.app`, in `ServiceClient`, exists solely to host
   the service in-process; no check reads model state. If the harness
   reached into `sut.model`, it would pass when the service is down.
2. **Suites are data, not code.** Thresholds, fences, and check lists live in
   yaml under version control. Changing a threshold is a reviewable diff, not
   a code change.
