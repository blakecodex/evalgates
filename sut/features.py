"""the feature spec - one function, used by BOTH the fit and the scorer.

train/serve skew is the classic model-service bug: the training pipeline
builds features one way, the service re-implements them slightly differently,
and every score is quietly wrong while every test of either half passes.
the fix here is structural: there is exactly one feature function, this one,
and both sides import it. the two paths cannot diverge.
"""

# the domain the model is fitted on. requests outside these fences get a
# no-score response - the service does not guess beyond its data.
# same numbers as the data pipeline's filter rules; the pipeline keeps its
# own copy on purpose and a test asserts the copies agree.
# the full fence set is DOMAIN plus area membership in AREAS - the scorer
# enforces both; features() assumes both already hold.
DOMAIN = {
    "exposure":    (0.002, 1.0),
    "driv_age":    (18, 100),
    "veh_age":     (0, 60),
    "veh_power":   (4, 15),
    "bonus_malus": (50, 230),
    "density":     (1, 30000),
}

AREAS = ("A", "B", "C", "D", "E", "F")

# column order is part of the model contract - coefficients.json stores
# a beta per name, and the fit builds its design matrix in this order.
FEATURE_NAMES = (
    "intercept",
    "bonus_malus",        # (bm - 50) / 10 : one unit = ten bonus-malus points
    "log_density",        # ln(inhabitants per km^2)
    "veh_power",          # min(power, 12) - 4 : capped, zero at the floor
    "drivage_18_25",      # age bands; 41-60 is the base band
    "drivage_26_40",
    "drivage_61_plus",
    "vehage_0_1",         # vehicle age bands; 2-9 is the base band
    "vehage_10_plus",
    "area_B",             # area one-hots; A (most rural) is the base
    "area_C",
    "area_D",
    "area_E",
    "area_F",
)


def features(p: dict) -> list[float]:
    """policy dict -> feature vector, in FEATURE_NAMES order.

    expects a policy already inside DOMAIN with area in AREAS; fencing is
    the caller's job (the scorer fences, the data pipeline filters).
    keeping this function fence-free keeps it identical on both paths.
    an unfenced unknown area would one-hot to all zeros and score as area A -
    which is why the scorer's fence includes area membership.
    """
    import math

    age = p["driv_age"]
    vage = p["veh_age"]
    x = [
        1.0,
        (p["bonus_malus"] - 50) / 10.0,
        math.log(p["density"]),
        float(min(p["veh_power"], 12) - 4),
        1.0 if 18 <= age <= 25 else 0.0,
        1.0 if 26 <= age <= 40 else 0.0,
        1.0 if age >= 61 else 0.0,
        1.0 if vage <= 1 else 0.0,
        1.0 if vage >= 10 else 0.0,
    ]
    x += [1.0 if p["area"] == a else 0.0 for a in AREAS[1:]]
    return x


# why these features and not more:
#   - bonus_malus is the strongest signal in this dataset - it is the french
#     no-claims system, so it summarizes each driver's own claim history.
#     scaled by 10 so one coefficient unit reads as "per ten points".
#   - density enters in logs: the difference between 40 and 400 people/km^2
#     matters like the difference between 400 and 4000, not like 360 vs 3600.
#   - vehicle power is capped at 12: only 8,474 in-domain rows (1.3%) sit
#     above 12, too few to estimate a separate slope for the top of the
#     range; the cap writes the flattening into the model.
#   - age and vehicle age are bands, not lines: their effects are not
#     straight lines, and bands represent that without assuming a
#     functional form.
#   - area one-hots order themselves (A most rural .. F most urban) - the fit
#     can disagree with that ordering, and whether it does is checked, not
#     assumed.
#   - brand, fuel, and region are left out on purpose: they add little on top
#     of the above for frequency, and every extra factor is another thing the
#     monotonicity family would need a defensible direction for.
