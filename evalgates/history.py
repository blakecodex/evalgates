"""run history. every gate run is a row, every check result is a row -
so "when did calibration start degrading" is a sql query instead of a
search through ci logs.

storage is sqlite by default (zero setup, a file next to the repo). the
RUNS_DB environment variable is the seam: point it at another path for a
shared volume. moving to postgres means swapping _connect() for a psycopg
connection and the ? placeholders for %s - the ddl below is deliberately
plain (TEXT / INTEGER / REAL, no sqlite-specific types) so it runs on
postgres as written.
"""
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

from evalgates.runner import RunResult

DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    suite       TEXT NOT NULL,
    suite_version INTEGER NOT NULL,
    model_version TEXT NOT NULL,
    passes      INTEGER NOT NULL,
    fails       INTEGER NOT NULL,
    errors      INTEGER NOT NULL,
    gate_exit   INTEGER,
    duration_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    run_id      TEXT NOT NULL,
    check_id    TEXT NOT NULL,
    family      TEXT NOT NULL,
    status      TEXT NOT NULL,
    measured    TEXT NOT NULL,
    message     TEXT,
    elapsed_ms  INTEGER NOT NULL,
    PRIMARY KEY (run_id, check_id)
);
"""


def db_path() -> str:
    return os.environ.get("RUNS_DB", ".evalgates/runs.db")


def _connect():
    path = db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(DDL)
    return con


def record(run: RunResult, gate_exit: int | None = None) -> str:
    # timestamp for humans, random suffix for uniqueness - two runs in the
    # same second must not overwrite each other, and plain INSERT (not
    # INSERT OR REPLACE) means an actual collision raises instead of
    # silently rewriting history
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    run_id = f"{stamp}-{uuid.uuid4().hex[:8]}-{run.suite}"
    c = run.counts
    with _connect() as con:
        con.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, run.started_at, run.suite, run.suite_version,
             run.model_version, c["pass"], c["fail"], c["error"],
             gate_exit, run.duration_ms))
        con.executemany(
            "INSERT INTO results VALUES (?,?,?,?,?,?,?)",
            [(run_id, r.id, r.family, r.status, json.dumps(r.measured),
              r.message, r.elapsed_ms) for r in run.results])
    return run_id


def recent_runs(limit: int = 20) -> list[dict]:
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,)).fetchall()
    return [dict(r) for r in rows]


def results_for(run_id: str) -> list[dict]:
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM results WHERE run_id = ? ORDER BY check_id",
            (run_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["measured"] = json.loads(d["measured"])
        out.append(d)
    return out
