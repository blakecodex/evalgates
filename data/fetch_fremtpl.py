"""reproduce the data artifacts from the public source, end to end.

four stages. fetch and extract are skipped when their outputs already
exist; filter and slice always re-run and overwrite - they are deterministic,
so re-running them is free and proves it.

  1. fetch    - sparse git checkout of one file, freMTPL2freq.rda, from the
                public CASdatasets mirror (github.com/dutangc/CASdatasets).
                no api keys, no scraping - plain git over https.
  2. extract  - parse the .rda with the pure-python `rdata` package and write
                fremtpl_full.csv.gz (677,991 rows, 12 columns, unmodified).
  3. filter   - keep rows inside the model's fitted domain, counting what
                each rule drops; write fremtpl_indomain.csv.gz.
  4. slice    - one seeded shuffle of the in-domain rows; the first 12,000
                become the REFERENCE slice (drift bins are frozen on it, the
                baseline is set on it), the next 12,000 become the EVALUATION
                slice (calibration and drift are measured on it). disjoint by
                construction. both are committed under data/sample/ so the
                repo tests run without any download.

usage:
    python data/fetch_fremtpl.py --workdir /tmp/fremtpl --out data/sample

provenance for the committed artifacts is written to data/sample/provenance.json.
"""
import argparse
import contextlib
import csv
import gzip
import hashlib
import io
import json
import random
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = "https://github.com/dutangc/CASdatasets"
RDA_PATH = "data/freMTPL2freq.rda"

# the model's fitted domain. deliberately NOT imported from sut/features.py:
# the pipeline and the service each carry their own copy, and a repo test
# asserts the two copies agree - so a drift between them fails loudly instead
# of hiding inside shared code.
AREAS = ("A", "B", "C", "D", "E", "F")
RULES = [
    ("exposure",    lambda r: 0.002 < r["exposure"] <= 1.0),
    ("driv_age",    lambda r: 18 <= r["driv_age"] <= 100),
    ("veh_age",     lambda r: 0 <= r["veh_age"] <= 60),
    ("veh_power",   lambda r: 4 <= r["veh_power"] <= 15),
    ("bonus_malus", lambda r: 50 <= r["bonus_malus"] <= 230),
    ("density",     lambda r: 1 <= r["density"] <= 30000),
    ("area",        lambda r: r["area"] in AREAS),
]

SEED = 20260910          # date the slices were cut (yyyymmdd)
SLICE_ROWS = 12000

COLUMNS = ["exposure", "driv_age", "veh_age", "veh_power",
           "bonus_malus", "density", "area", "claim_nb"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_content(gz_path: Path) -> str:
    """sha of the decompressed bytes - survives gzip-level differences, so
    it is the number to compare across machines and library versions."""
    with gzip.open(gz_path, "rb") as f:
        h = hashlib.sha256()
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@contextlib.contextmanager
def gz_writer(path: Path):
    """gzip text stream with mtime=0 and no filename field: identical
    content gives identical bytes, on every run, whatever the file is
    called - so the checksums in provenance.json stay meaningful."""
    with open(path, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
            with io.TextIOWrapper(gz, newline="") as f:
                yield f


def fetch(workdir: Path) -> Path:
    rda = workdir / "CASdatasets" / RDA_PATH
    if rda.exists():
        return rda
    clone = workdir / "CASdatasets"
    if clone.exists():
        # a clone directory without the target file is a failed earlier
        # attempt; say so instead of dying inside git with a worse message
        sys.exit(f"{clone} exists but {RDA_PATH} is missing - "
                 f"delete the directory and re-run")
    workdir.mkdir(parents=True, exist_ok=True)
    # sparse checkout: clone metadata only, then materialize the one file
    subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none",
                    "--sparse", REPO], cwd=workdir, check=True)
    subprocess.run(["git", "sparse-checkout", "set", RDA_PATH],
                   cwd=clone, check=True)
    return rda


def extract(rda: Path, out_csv: Path) -> None:
    if out_csv.exists():
        return
    import rdata  # pure python, parses R data files
    parsed = rdata.parsing.parse_file(rda)
    converted = rdata.conversion.convert(parsed)
    df = converted["freMTPL2freq"]
    with gz_writer(out_csv) as w:      # mtime=0: byte-stable given the same pandas
        df.to_csv(w, index=False)


def read_full(path: Path):
    with gzip.open(path, "rt") as f:
        for row in csv.DictReader(f):
            yield {
                "exposure": float(row["Exposure"]),
                "driv_age": int(float(row["DrivAge"])),
                "veh_age": int(float(row["VehAge"])),
                "veh_power": int(float(row["VehPower"])),
                "bonus_malus": int(float(row["BonusMalus"])),
                "density": int(float(row["Density"])),
                "area": row["Area"].strip("'\""),
                "claim_nb": int(float(row["ClaimNb"])),
            }


def filter_indomain(full_csv: Path, out_csv: Path) -> dict:
    """apply the domain rules; return input count and per-rule drop counts."""
    drops = {name: 0 for name, _ in RULES}
    kept = total = 0
    with gz_writer(out_csv) as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in read_full(full_csv):
            total += 1
            failed = [name for name, ok in RULES if not ok(r)]
            if failed:
                # a row failing several rules is counted once per rule -
                # the counts answer "how much does each rule cost alone"
                for name in failed:
                    drops[name] += 1
                continue
            kept += 1
            w.writerow(r)
    return {"input_rows": total, "kept": kept, "drops": drops}


def cut_slices(indomain_csv: Path, out_dir: Path) -> dict:
    with gzip.open(indomain_csv, "rt") as f:
        rows = list(csv.DictReader(f))
    if len(rows) < 2 * SLICE_ROWS:
        sys.exit(f"only {len(rows)} in-domain rows - need {2 * SLICE_ROWS} "
                 f"for two slices; upstream data has shrunk, investigate")
    rng = random.Random(SEED)
    rng.shuffle(rows)
    names = {"reference": rows[:SLICE_ROWS],
             "evaluation": rows[SLICE_ROWS:2 * SLICE_ROWS]}
    info = {}
    for name, part in names.items():
        path = out_dir / f"fremtpl_{name}.csv.gz"
        with gz_writer(path) as f:
            text = [",".join(COLUMNS)]
            text += [",".join(r[c] for c in COLUMNS) for r in part]
            f.write("\n".join(text) + "\n")
        info[name] = {"rows": len(part), "sha256": sha256(path),
                      "sha256_content": sha256_content(path)}
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default="/tmp/fremtpl")
    ap.add_argument("--out", default="data/sample")
    ap.add_argument("--full-csv", default=None,
                    help="skip fetch/extract and start from an existing full csv.gz")
    args = ap.parse_args()

    workdir, out_dir = Path(args.workdir), Path(args.out)
    workdir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.full_csv:
        full_csv = Path(args.full_csv)
    else:
        rda = fetch(workdir)
        full_csv = workdir / "fremtpl_full.csv.gz"
        extract(rda, full_csv)

    indomain_csv = workdir / "fremtpl_indomain.csv.gz"
    stats = filter_indomain(full_csv, indomain_csv)
    slices = cut_slices(indomain_csv, out_dir)

    provenance = {
        "dataset": "freMTPL2freq (french motor third-party liability, claim counts)",
        "source": f"{REPO} -> {RDA_PATH}",
        "license_note": "CASdatasets distributes freMTPL2freq for public research use",
        "extracted": str(date.today()),
        "full_rows": stats["input_rows"],          # counted, not asserted
        "full_sha256": sha256(full_csv),           # gzip bytes of this extraction
        "full_sha256_content": sha256_content(full_csv),  # decompressed - compare this across machines
        "indomain": stats,
        "slice_seed": SEED,
        "slices": slices,
        "columns": COLUMNS,
        "method": "git sparse-checkout -> rdata parse -> domain filter -> seeded shuffle -> two disjoint 12k slices",
    }
    (out_dir / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
