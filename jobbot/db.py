"""SQLite tracker. One row per job; `status` moves through the pipeline:

new -> filtered_out | scored -> low_score | tailored -> applied | skipped
"""
import csv
import json
import sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  source TEXT, ext_id TEXT, board TEXT, company TEXT, title TEXT, location TEXT,
  url TEXT, apply_url TEXT, description TEXT, remote_hint INTEGER,
  status TEXT DEFAULT 'new', filter_reason TEXT,
  score INTEGER, score_json TEXT, packet_dir TEXT, notes TEXT,
  created_at TEXT, updated_at TEXT, applied_at TEXT,
  UNIQUE(source, ext_id)
);
"""

FIELDS = ["source", "ext_id", "board", "company", "title", "location", "url",
          "apply_url", "description", "remote_hint"]


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect(path="jobs.db"):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert(con, job):
    """Insert a job if unseen. Returns True if it was new."""
    cur = con.execute(
        f"INSERT OR IGNORE INTO jobs ({','.join(FIELDS)}, created_at, updated_at) "
        f"VALUES ({','.join('?' * len(FIELDS))}, ?, ?)",
        [int(job[f]) if f == "remote_hint" else job.get(f, "") for f in FIELDS] + [now(), now()],
    )
    return cur.rowcount == 1


def update(con, job_id, **fields):
    if "score_json" in fields and not isinstance(fields["score_json"], str):
        fields["score_json"] = json.dumps(fields["score_json"])
    fields["updated_at"] = now()
    cols = ", ".join(f"{k}=?" for k in fields)
    con.execute(f"UPDATE jobs SET {cols} WHERE id=?", [*fields.values(), job_id])
    con.commit()


def by_status(con, status, order="id", limit=None):
    q = f"SELECT * FROM jobs WHERE status=? ORDER BY {order}"
    if limit:
        q += f" LIMIT {int(limit)}"
    return con.execute(q, (status,)).fetchall()


def get(con, job_id):
    return con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def counts(con):
    return dict(con.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())


def export_csv(con, path):
    cols = ["id", "status", "score", "company", "title", "location", "url", "apply_url",
            "packet_dir", "applied_at", "notes", "created_at"]
    rows = con.execute(
        f"SELECT {','.join(cols)} FROM jobs WHERE status NOT IN ('filtered_out') "
        "ORDER BY COALESCE(score,-1) DESC, id").fetchall()
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows([list(r) for r in rows])
    return len(rows)
