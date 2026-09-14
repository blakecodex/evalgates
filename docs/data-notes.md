# Data notes — freMTPL2freq

Public French motor third-party liability data: one row per policy, with the
claim count and the exposure (the fraction of a year the policy was on risk).
The standard public dataset for claim-frequency work.

## Source chain

```
github.com/dutangc/CASdatasets          public mirror of the CASdatasets R package
  └─ data/freMTPL2freq.rda              fetched by sparse git checkout (one file)
       └─ parsed with `rdata`           pure-python parser, no R needed
            └─ fremtpl_full.csv.gz      677,991 rows, 12 columns, unmodified
                 └─ domain filter       676,688 rows kept (table below)
                      └─ seeded shuffle, two disjoint 12,000-row slices
```

Every hop is reproducible with `python data/fetch_fremtpl.py`. All gzip
artifacts are written with `mtime=0`, so identical content gives identical
bytes run over run. `data/sample/provenance.json` records two checksums per
artifact: the gzip bytes (byte-stable on one toolchain) and the decompressed
content (the one to compare across machines and pandas versions).

## The domain filter, rule by rule

The scorer refuses inputs outside the domain it was fitted on, so the fit
must use only in-domain rows — the filter and the service fences are the same
numbers by design.

| rule | kept range | rows dropped | why |
|---|---|---:|---|
| exposure | (0.002, 1.0] | 1,224 | exposures run to 2.01 in the raw file; more than one policy-year on a one-year contract is a recording artifact, and the actuarial literature on this dataset caps exposure at 1. The floor removes near-zero exposures whose observed frequency is pure noise. |
| veh_age | 0–60 | 79 | sixty-plus-year-old vehicles are vintage cars or data errors; either way, not the book being priced |
| driv_age | 18–100 | 0 | already clean in the source |
| veh_power | 4–15 | 0 | already clean |
| bonus_malus | 50–230 | 0 | already clean (French legal range) |
| density | 1–30,000 | 0 | already clean |

Rows failing several rules count once per rule, so the column answers "what
does this rule cost alone" and does not sum to the total dropped.

## The two slices, and why there are two

| slice | rows | job |
|---|---:|---|
| `fremtpl_reference.csv.gz` | 12,000 | the population the release was approved on: drift bins are frozen on its scores, the gate baseline is set from it |
| `fremtpl_evaluation.csv.gz` | 12,000 | the "today" cohort: calibration and drift are measured on it |

One seeded shuffle (seed 20260910) of the in-domain rows; the first 12,000
are the reference, the next 12,000 the evaluation slice — disjoint by
construction.

## Slice representativeness against the book

Measured after cutting (the audit that decided the slices were usable):

| | in-domain (676,688) | reference (12,000) | evaluation (12,000) |
|---|---|---|---|
| claim frequency (claims / exposure-year) | 0.0739 | 0.0768 | 0.0712 |
| exposure mean / median | 0.528 / 0.49 | 0.531 / 0.49 | 0.532 / 0.49 |
| bonus-malus median / p90 | 50 / 85 | 50 / 85 | 50 / 85 |
| density median / p90 | 393 / 4,128 | 384 / 4,128 | 374 / 4,253 |
| area mix A–F | .153 .111 .283 .224 .202 .026 | .154 .115 .282 .219 .204 .026 | .160 .117 .276 .217 .202 .029 |

With 489 claims in the reference slice and 454 in the evaluation slice, the
frequency's sampling error is about ±5% relative; both slice frequencies sit
inside it. Mix and quantiles track the full book.

## Known limitations of the 12k slices

- **The claim-count tail.** 75 policies in the full data have 3+ claims; the
  slices carry 2 and 1 of them. Fine here: the harness checks frequency
  calibration by decile, which does not depend on the extreme tail. A
  severity model would need a different sample.
- **Row identity.** The IDpol column is dropped; the source contains a few
  fully-duplicated attribute rows (49 identical tuples appear in both
  slices). The slices are still disjoint by position; the collisions are
  duplicates in the source, not a slicing bug.
