# the four check families. a family is a module with one entry point:
#   run(check, client) -> CheckResult
# adding a family = one module + one line here + its name in schema.KNOWN_FAMILIES.
from evalgates.families import calibration, contract, drift, monotonic
from evalgates.runner import CheckResult
from evalgates.schema import Check

REGISTRY = {
    "contract": contract.run,
    "monotonic": monotonic.run,
    "calibration": calibration.run,
    "drift": drift.run,
}


def run_check(check: Check, client) -> CheckResult:
    return REGISTRY[check.family](check, client)
