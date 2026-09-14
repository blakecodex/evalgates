"""load a suite, run every check against the service, collect results.

the client seam: everything downstream calls client.get/client.post and does
not know whether the service is in-process (starlette TestClient wrapping the
asgi app - fast, hermetic, what ci uses) or a real deployment reached over
http (--base-url - what a staging smoke test uses). same checks, same
thresholds, both targets.

a check that raises is recorded as status "error", and the gate treats error
exactly like fail. if the harness cannot prove the check passed, the release
does not ship on the strength of that check.
"""
import time
from dataclasses import dataclass, field

from evalgates.schema import Suite


@dataclass
class CheckResult:
    id: str
    family: str
    status: str                  # "pass" | "fail" | "error"
    measured: dict = field(default_factory=dict)
    message: str = ""
    elapsed_ms: int = 0


@dataclass
class RunResult:
    suite: str
    suite_version: int
    model_version: str
    results: list[CheckResult]
    started_at: str
    duration_ms: int

    @property
    def counts(self):
        c = {"pass": 0, "fail": 0, "error": 0}
        for r in self.results:
            c[r.status] += 1
        return c

    @property
    def ok(self) -> bool:
        c = self.counts
        return c["fail"] == 0 and c["error"] == 0


class ServiceClient:
    """one interface, two transports."""

    def __init__(self, base_url: str | None = None):
        if base_url:
            import httpx
            self._c = httpx.Client(base_url=base_url, timeout=30.0)
        else:
            from starlette.testclient import TestClient
            from sut.app import app       # the only sut import in the harness,
            self._c = TestClient(app)     # used solely to host it in-process

    def get(self, path: str):
        return self._c.get(path)

    def post(self, path: str, json: dict):
        return self._c.post(path, json=json)


def run_suite(suite: Suite, client: ServiceClient) -> RunResult:
    from evalgates import families            # late import: avoids a cycle

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    t0 = time.perf_counter()

    # the service must identify itself before anything runs; a dead service
    # is one error per check plus a loud message, not a silent all-skip
    try:
        health = client.get("/healthz")
        model_version = health.json().get("model_version", "unknown")
    except Exception as e:                    # noqa: BLE001 - report, don't die
        model_version = "unreachable"
        results = [CheckResult(id=c.id, family=c.family, status="error",
                               message=f"service unreachable: {e}")
                   for c in suite.checks]
        return RunResult(suite.name, suite.version, model_version, results,
                         started, int((time.perf_counter() - t0) * 1000))

    results = []
    for check in suite.checks:
        t1 = time.perf_counter()
        try:
            r = families.run_check(check, client)
        except Exception as e:                # noqa: BLE001 - error = fail
            r = CheckResult(id=check.id, family=check.family, status="error",
                            message=f"{type(e).__name__}: {e}")
        r.elapsed_ms = int((time.perf_counter() - t1) * 1000)
        results.append(r)

    return RunResult(suite.name, suite.version, model_version, results,
                     started, int((time.perf_counter() - t0) * 1000))
