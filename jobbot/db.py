"""SQLite tracker. One row per job; `status` moves through the pipeline:

new -> filtered_out | scored -> low_score | tailored -> applied | skipped
applied -> interview -> offer, or rejected / withdrawn at any stage
Applications made outside job-bot are added with source='manual'. Every
application status change and user note is logged in `events`.
"""
import csv
import json
import sqlite3
import uuid
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

EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL REFERENCES jobs(id),
  at TEXT NOT NULL, kind TEXT NOT NULL, text TEXT
);
CREATE INDEX IF NOT EXISTS events_job ON events(job_id);
"""
# columns added after the first release; connect() adds them to older databases
EXTRA_COLS = {"contact": "TEXT", "salary": "TEXT", "next_step": "TEXT", "follow_up": "TEXT"}
DETAIL_FIELDS = ["company", "title", "location", "url", "applied_at", "contact", "salary",
                 "next_step", "follow_up"]
APPLICATION_STATUSES = ["applied", "interview", "offer", "rejected", "withdrawn"]
TRACKED = set(APPLICATION_STATUSES) | {"skipped", "tailored"}

FIELDS = ["source", "ext_id", "board", "company", "title", "location", "url",
          "apply_url", "description", "remote_hint"]


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect(path="jobs.db"):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA + EVENTS_SCHEMA)
    have = {r["name"] for r in con.execute("PRAGMA table_info(jobs)")}
    for col, typ in EXTRA_COLS.items():
        if col not in have:
            con.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
    # applications made before the events table existed get an 'applied' entry
    con.execute("INSERT INTO events (job_id, at, kind, text) SELECT id, applied_at, 'status', 'applied' "
                "FROM jobs WHERE applied_at IS NOT NULL AND id NOT IN (SELECT job_id FROM events)")
    con.commit()
    return con


def add_event(con, job_id, kind, text, at=None):
    con.execute("INSERT INTO events (job_id, at, kind, text) VALUES (?, ?, ?, ?)",
                (job_id, at or now(), kind, text))
    con.commit()


def events(con, job_id):
    return con.execute("SELECT at, kind, text FROM events WHERE job_id=? ORDER BY at, id",
                       (job_id,)).fetchall()


def set_status(con, job_id, status, note=None):
    """Change an application's status and log it (sets applied_at on first 'applied')."""
    row = get(con, job_id)
    fields = {"status": status}
    if status == "applied" and not row["applied_at"]:
        fields["applied_at"] = now()
    update(con, job_id, **fields)
    if row["status"] != status:
        add_event(con, job_id, "status", status)
    if note:
        add_event(con, job_id, "note", note)


def add_manual(con, company, title, url="", location="", applied_at=None, status="applied",
               **details):
    """Record an application made outside job-bot. Returns its id."""
    at = applied_at or now()
    cur = con.execute(
        "INSERT INTO jobs (source, ext_id, board, company, title, location, url, apply_url, "
        "description, remote_hint, status, applied_at, created_at, updated_at) "
        "VALUES ('manual', ?, '', ?, ?, ?, ?, ?, '', 0, ?, ?, ?, ?)",
        (f"manual-{uuid.uuid4().hex[:12]}", company, title, location, url, url, status,
         at if status in APPLICATION_STATUSES else None, now(), now()))
    job_id = cur.lastrowid
    extra = {k: v for k, v in details.items() if k in DETAIL_FIELDS and v not in (None, "")}
    if extra:
        update(con, job_id, **extra)
    add_event(con, job_id, "status", status, at=at)
    con.commit()
    return job_id


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
            "applied_at", "contact", "salary", "next_step", "follow_up", "notes", "source",
            "packet_dir", "created_at"]
    rows = con.execute(
        f"SELECT {','.join(cols)} FROM jobs WHERE status NOT IN ('filtered_out') "
        "ORDER BY COALESCE(score,-1) DESC, id").fetchall()
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows([list(r) for r in rows])
    return len(rows)
