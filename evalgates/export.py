"""export a run in the shape testrail's bulk-results api takes
(add_results_for_cases): one entry per check with a status_id, a comment,
and an elapsed string. teams that live in testrail get gate results in
their system of record without retyping anything.

status ids follow testrail's fixed convention: 1 = passed, 5 = failed.
an errored check exports as failed with the error in the comment - the
export reports exactly what the gate decided.
"""
import json
from pathlib import Path

from evalgates.runner import RunResult

STATUS_PASSED = 1
STATUS_FAILED = 5


def testrail_payload(run: RunResult) -> dict:
    results = []
    for r in run.results:
        ok = r.status == "pass"
        comment = r.message or ("all thresholds met" if ok else "")
        if r.status == "error":
            comment = f"ERROR: {comment}"
        results.append({
            "case_id": r.id,
            "status_id": STATUS_PASSED if ok else STATUS_FAILED,
            "comment": comment,
            "elapsed": f"{max(r.elapsed_ms, 1) / 1000:.3f}s",
            "version": run.model_version,
            "custom_measured": r.measured,
        })
    return {"suite": run.suite, "suite_version": run.suite_version,
            "started_at": run.started_at, "results": results}


def write(run: RunResult, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(testrail_payload(run), indent=2) + "\n")
