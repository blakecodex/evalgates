# Monotonicity notes — what the fitted model actually supports

The monotonicity family asserts "worse factor in, higher frequency out."
Every assertion in that family has to be backed by the fitted numbers below —
an assertion the data does not support generates false alarms, and a gate
that raises false alarms gets bypassed within a quarter. This page records
the fitted numbers behind each assertion and each exclusion.

Fitted on 676,688 in-domain rows (see `sut/coefficients.json`; z = beta / se).

| feature | beta | z | exp(beta) | reading |
|---|---:|---:|---:|---|
| intercept | −3.187 | −61.9 | 0.041 | the all-base profile — age 41–60, vehicle age 2–9, area A, bonus 50, power 4, density 1/km²: 4.1 claims per 100 policy-years. At the median density (393) the same profile scores 5.7. |
| bonus_malus | +0.262 | +75.1 | 1.299 | +30% frequency per 10 bonus-malus points. The strongest factor in the model: z = 75 against 19.5 for the next one. |
| log_density | +0.055 | +3.7 | 1.057 | denser is worse, log-for-log. Modest but real. |
| veh_power | +0.034 | +10.8 | 1.035 | +3.5% per power unit, up to the cap at 12. |
| drivage_18_25 | −0.182 | −7.1 | 0.833 | see the exclusion note below |
| drivage_26_40 | −0.294 | −19.5 | 0.745 | " |
| drivage_61_plus | −0.111 | −6.0 | 0.895 | " |
| vehage_0_1 | −0.130 | −6.9 | 0.878 | newest cars claim less than the 2–9 base |
| vehage_10_plus | −0.156 | −11.4 | 0.856 | oldest cars claim less too — an inverted U |
| area_B | +0.045 | +1.5 | 1.046 | with density in the model, the area terms measure what area adds *on top of* density |
| area_C | +0.056 | +1.4 | 1.057 | " |
| area_D | +0.120 | +2.0 | 1.127 | the only one nominally significant, and barely |
| area_E | +0.132 | +1.7 | 1.142 | " |
| area_F | −0.034 | −0.3 | 0.966 | the densest band, and pure noise — density already said it |

## What the family asserts (three directions, all defensible)

1. **bonus_malus up ⇒ frequency up.** z = 75. The French no-claims system is
   each driver's own claims history; this direction is close to definitional.
2. **density up ⇒ frequency up.** z = 3.7 on the log term, and the area
   coefficients broadly agree (D and E, the denser bands, sit highest).
3. **veh_power flat past 12.** By construction — the feature caps there —
   and the cap exists because the data thins past 12. The check pins the cap:
   power 13, 14, 15 must score identically to 12.

## What the family deliberately does not assert

**Driver age.** The underwriting prior says young drivers claim more. The
fitted age coefficients say the opposite of the prior: every age band scores
below the 41–60 base, including 18–25 (beta −0.182, z −7.1). This is an
artifact of the model specification, not of driving behavior: bonus-malus
already carries the young-driver surcharge. A French driver cannot reach the
bonus floor of 50 without about thirteen clean years, so a 20-year-old at
bonus 50 does not exist in the data — the age coefficient is measured
*conditional on bonus-malus*, and conditional on bonus-malus, age adds
little explanatory power. Refit the same model without the bonus_malus
column and the young band flips to +0.72 (z +32), exactly as the prior
expects. Both fits were run; both numbers reproduce.

So: an "age up ⇒ frequency down for the young" assertion would encode a
conditional artifact as a business rule, and an "age up ⇒ frequency up"
assertion would fail against the actual model. Age stays out of the family.
The right home for the age question is the calibration family — if young
drivers were mispriced as a group, their deciles would show it.

**Vehicle age.** The effect is an inverted U (new and old cars both below
the 2–9 base) — real, but not monotone, so not a monotonicity check.

**Area.** Absorbed by density (area F, the densest, has a noise-level
coefficient because log_density already carries the information). Density
holds the assertion; an area assertion would double-count it.

## Seeded-defect coverage for this family

The seeded-defect test for this family flips the sign of `bonus_malus` in a
copy of the coefficients and asserts the family FAILS against the broken
service. If someone later edits the family until that test cannot fail, the
test suite reports it before the gate loses the ability to detect this
defect.
