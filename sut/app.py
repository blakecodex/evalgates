"""the scoring service. two layers of protection, doing different jobs:

  shape fences (this file, pydantic)     -> 422, request never reaches the model
  domain fences (model.py)               -> 200 with no_score: true and reasons

the split matters. "exposure": "banana" is a malformed request - reject it
before any model code runs. "exposure": 1.5 is a well-formed request for
something the model was not fitted on - accept it, refuse to score it, and
say why, so the caller can route the policy to manual review. collapsing the
two cases into one error code would force every caller to parse error text
to tell a client bug from a model limitation.

shape bounds are deliberately wider than domain bounds: shape answers "is
this a physically plausible request", domain answers "was the model fitted
there". the gap between the two is exactly the no-score band, and the
contract family tests requests inside that gap.

run it:  uvicorn sut.app:app --port 8080
"""
from fastapi import FastAPI
from pydantic import BaseModel, Field

from sut import model

MAX_BATCH = 500

app = FastAPI(title="claim-frequency scorer", version="1")


class Policy(BaseModel):
    exposure: float = Field(gt=0.0, le=2.0)        # domain will cap at 1.0
    driv_age: int = Field(ge=0, le=130)            # domain: 18-100
    veh_age: int = Field(ge=0, le=100)             # domain: 0-60
    veh_power: int = Field(ge=0, le=30)            # domain: 4-15
    bonus_malus: int = Field(ge=0, le=350)         # domain: 50-230
    density: int = Field(ge=0, le=1_000_000)       # domain: 1-30000
    area: str = Field(min_length=1, max_length=1)  # domain: A-F

    model_config = {"extra": "forbid"}             # unknown fields are a client bug


class Batch(BaseModel):
    policies: list[Policy] = Field(min_length=1, max_length=MAX_BATCH)


@app.get("/healthz")
def healthz():
    # loads the coefficients, so a broken model artifact fails the probe
    # instead of failing the first customer request
    return {"status": "ok", "model_version": model._model()["version"]}


@app.post("/score")
def score(p: Policy):
    return model.score(p.model_dump())


@app.post("/score/batch")
def score_batch(b: Batch):
    results = model.score_many([p.model_dump() for p in b.policies])
    scored = sum(1 for r in results if not r["no_score"])
    return {"count": len(results), "scored": scored,
            "no_score": len(results) - scored, "results": results}
