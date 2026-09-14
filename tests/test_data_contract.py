# the committed data artifacts must match their provenance, and the data
# pipeline's domain rules must agree with the model's fences - the two
# copies are deliberate, and this test is what makes the duplication safe.
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_content(path):
    with gzip.open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _provenance():
    return json.loads((SAMPLE / "provenance.json").read_text())


def test_slice_bytes_match_provenance():
    prov = _provenance()
    for name in ("reference", "evaluation"):
        path = SAMPLE / f"fremtpl_{name}.csv.gz"
        assert _sha(path) == prov["slices"][name]["sha256"], name
        assert _sha_content(path) == prov["slices"][name]["sha256_content"], name


def test_slice_row_counts_match_provenance():
    prov = _provenance()
    for name in ("reference", "evaluation"):
        path = SAMPLE / f"fremtpl_{name}.csv.gz"
        with gzip.open(path, "rt") as f:
            rows = sum(1 for _ in f) - 1          # minus header
        assert rows == prov["slices"][name]["rows"] == 12000


def test_provenance_counts_are_coherent():
    prov = _provenance()
    assert prov["full_rows"] == prov["indomain"]["input_rows"]
    assert prov["indomain"]["kept"] <= prov["full_rows"]
    assert prov["indomain"]["kept"] >= 2 * 12000


def _load_pipeline():
    spec = importlib.util.spec_from_file_location(
        "fetch_fremtpl", ROOT / "data" / "fetch_fremtpl.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pipeline_rules_agree_with_model_domain():
    """the pipeline and the scorer each carry their own copy of the domain.
    probe both with the same edge values; accept/reject must be identical -
    otherwise the service refuses rows it was fitted on, or scores rows it
    was never fitted on."""
    from sut.features import AREAS, DOMAIN
    pipeline = _load_pipeline()
    rules = dict(pipeline.RULES)

    base = {"exposure": 0.5, "driv_age": 45, "veh_age": 5, "veh_power": 6,
            "bonus_malus": 60, "density": 500, "area": "C"}

    for field, (lo, hi) in DOMAIN.items():
        if field == "exposure":
            probes = [lo, lo + 0.0001, 0.5, hi, hi + 0.01]
        else:
            probes = [lo - 1, lo, (lo + hi) // 2, hi, hi + 1]
        for v in probes:
            row = dict(base, **{field: v})
            pipeline_says = rules[field](row)
            if field == "exposure":
                model_says = lo < v <= hi
            else:
                model_says = lo <= v <= hi
            assert pipeline_says == model_says, f"{field}={v}: pipeline {pipeline_says}, model {model_says}"

    assert tuple(pipeline.AREAS) == tuple(AREAS)
    for a in ("A", "F", "G", "c"):
        assert rules["area"](dict(base, area=a)) == (a in AREAS), a
