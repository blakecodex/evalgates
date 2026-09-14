# the service layer: shape fences give 422, domain fences give 200+no_score,
# and the gap between them is tested explicitly.
from starlette.testclient import TestClient

from sut import model
from sut.app import MAX_BATCH, app

client = TestClient(app)

GOOD = {"exposure": 0.5, "driv_age": 45, "veh_age": 5, "veh_power": 6,
        "bonus_malus": 60, "density": 500, "area": "C"}


def test_healthz_names_the_model():
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_version"] == model._model()["version"]


def test_score_matches_the_model_directly():
    r = client.post("/score", json=GOOD)
    assert r.status_code == 200
    assert r.json() == model.score(GOOD)


# --- shape fences: the request is malformed, the model must never run ---

def test_wrong_type_is_422():
    assert client.post("/score", json=dict(GOOD, exposure="banana")).status_code == 422


def test_missing_field_is_422():
    bad = dict(GOOD); del bad["driv_age"]
    assert client.post("/score", json=bad).status_code == 422


def test_unknown_field_is_422():
    assert client.post("/score", json=dict(GOOD, turbo=True)).status_code == 422


def test_zero_exposure_is_422():
    # zero is not a plausible request at all - shape, not domain
    assert client.post("/score", json=dict(GOOD, exposure=0)).status_code == 422


def test_batch_above_limit_is_422():
    r = client.post("/score/batch", json={"policies": [GOOD] * (MAX_BATCH + 1)})
    assert r.status_code == 422


def test_empty_batch_is_422():
    assert client.post("/score/batch", json={"policies": []}).status_code == 422


# --- the gap: well-formed request, outside the fitted domain -> 200 ---

def test_shape_valid_domain_invalid_is_200_no_score():
    # exposure 1.5 passes the shape fence (le=2.0) but not the domain (le 1.0):
    # this is the no-score band working as designed
    r = client.post("/score", json=dict(GOOD, exposure=1.5))
    assert r.status_code == 200
    body = r.json()
    assert body["no_score"] is True
    assert any("exposure" in reason for reason in body["reasons"])


def test_seventeen_year_old_driver_is_refused_not_rejected():
    r = client.post("/score", json=dict(GOOD, driv_age=17))
    assert r.status_code == 200
    assert r.json()["no_score"] is True


# --- batch behavior ---

def test_batch_counts_are_consistent():
    policies = [GOOD, dict(GOOD, exposure=1.5), dict(GOOD, bonus_malus=90)]
    r = client.post("/score/batch", json={"policies": policies})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert body["scored"] == 2 and body["no_score"] == 1
    assert len(body["results"]) == 3
    assert body["results"][1]["no_score"] is True
